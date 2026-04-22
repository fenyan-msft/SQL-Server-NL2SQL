"""
Agent Orchestrator — LangGraph
================================

Three-level LangGraph StateGraph implementing the NL→SQL pipeline.

Parent graph (6 nodes):
  Node 1  orchestrator_node        — classifies intent; routes to domain agent or END
  Node 2  customer_service_node    — self-grounds schema; generates T-SQL for orders / loyalty / profile queries
  Node 3  product_recommender_node — self-grounds schema; generates T-SQL for product / stock queries
  Node 4  sql_pipeline             — sub-graph: validate → repair → query_runner → summarizer
  Node 5  sql_fallback             — resets state when sql_pipeline returns no rows; routes to vector_pipeline
  Node 6  vector_pipeline          — sub-graph: vector_search → validate → repair → run → summarize

sql_pipeline sub-graph (4 nodes + max_repairs):
  validate_node  — safety check + compile test (SET NOEXEC ON)
  repair_node    — LLM repairs faulty SQL (up to _MAX_REPAIR_ATTEMPTS)
  query_runner   — executes validated SQL (pure tool; no LLM)
  summarizer     — turns rows into a business answer + assumptions + query

vector_pipeline sub-graph (5 nodes + max_repairs):
  vector_search  — rewrites LIKE queries as VECTOR_DISTANCE cosine
  validate_node  — safety check + compile test
  repair_node    — LLM repairs faulty SQL
  query_runner   — executes validated SQL
  summarizer     — turns rows into a business answer

Each LLM-driven agent is created with langchain.agents.create_agent
combining a .prompty system prompt with per-agent tools from the tools/ package.
Validate and query_runner nodes call their tools directly without an LLM agent.
The validate, repair, query_runner, vector_search, and summarizer node functions
are shared between both execution sub-graphs.

Routing: after a domain agent generates SQL, the parent graph checks for LIKE
in the WHERE clause — LIKE present → vector_pipeline, otherwise → sql_pipeline.

Uses AzureChatOpenAI (langchain-openai) with LLM_ENDPOINT / LLM_MODEL from config.py.

Install:
    pip install langgraph>=0.2.0 langchain-openai>=0.1.0 langchain-core>=0.2.0 \\
                azure-identity>=1.16.0
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
from collections.abc import Callable
from typing import TypedDict

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, ChatOpenAI
from langchain.agents import create_agent
from langgraph.graph import END, START, StateGraph

from config import LLM_ENDPOINT, LLM_API_KEY, LLM_API_VERSION, LLM_MODEL, LLM_TENANT_ID, MAX_SQL_ROWS, MAX_VECTOR_ROWS

_LLM_PLACEHOLDER = "YOUR_LLM_ENDPOINT_HERE"
_SQL_PLACEHOLDER = "YOUR_SQL_SERVER_HERE"

_PROMPTS_DIR = pathlib.Path(__file__).parent.parent / "prompts"

_MAX_REPAIR_ATTEMPTS = 3
_MAX_CONV_HISTORY    = 10             # max Q&A turns kept in conversation history
_CLARIFY_PREFIX      = "[CLARIFY]:"   # sentinel prepended to clarifying questions


def _is_azure_endpoint(endpoint: str) -> bool:
    """Return True for Azure OpenAI-compatible endpoint hostnames."""
    endpoint_l = endpoint.lower()
    return (
        "openai.azure.com" in endpoint_l
        or "cognitiveservices.azure.com" in endpoint_l
    )

_REPAIR_PROMPT = """\
You are a T-SQL Repair Specialist. Your sole job is to produce a corrected version of a broken SELECT query.

You will receive:
  • The original user question
  • The faulty T-SQL query
  • An error message — either a SQL Server compile error or a safety violation

REPAIR RULES:
  • Return ONLY the corrected raw T-SQL — no explanation, no markdown fences.
  • Always produce a SELECT or WITH statement as the outermost query.
  • Forbidden keywords (never emit): INSERT, UPDATE, DELETE, DROP, TRUNCATE, ALTER,
    CREATE, GRANT, REVOKE, or EXEC / EXECUTE (except sp_help).
  • Preserve TOP {max_sql_rows} on the outermost SELECT — add it if missing.
  • Qualify every table reference with its named schema (e.g., Production.Product, Sales.SalesOrder).
    NEVER use 'dbo' — AdventureWorks uses named schemas: Sales, Person, Production, HumanResources, Purchasing.
  • Fix the specific error reported; do not rewrite the whole query unnecessarily.
  • If the error is a safety violation, remove or replace the offending keyword or clause.
  • If the error is a SQL Server compile error, correct the offending syntax, column name,
    or table reference while keeping the rest of the query unchanged.
  • Preserve all original column aliases and the semantic intent of the question.
"""

_VECTOR_GENERATE_PROMPT = """\
You are an expert T-SQL developer targeting Microsoft SQL Server 2025.

You will receive:
  • The user's natural-language question
  • Database schema guidance (AGENTS.md) — use this to find the correct tables, columns, and the embedding column
  • A pre-computed CAST embedding expression for the user's query

GENERATE a complete T-SQL SELECT query using vector similarity search.

RULES:
  • Find the embedding column name from AGENTS.md — use it exactly as specified there.
  • Use the literal token __CAST_EXPR__ as the embedding CAST expression — do NOT substitute or modify it.
  • Structure the query using a CTE that computes the distance ONCE as [Relevance Score]:

      WITH candidates AS (
          SELECT <all needed columns>,
                 VECTOR_DISTANCE('cosine', __CAST_EXPR__, <embedding_column>) AS [Relevance Score]
          FROM <tables with joins>
      )
      SELECT TOP {max_vector_rows} *
      FROM candidates
      ORDER BY [Relevance Score] ASC

  • NEVER put TOP inside the CTE — TOP belongs only on the outer SELECT.
  • NEVER add a WHERE filter on [Relevance Score] — always return the TOP N closest results regardless of distance.
  • NEVER call VECTOR_DISTANCE more than once — reference the [Relevance Score] alias in ORDER BY.
  • Apply ALL mandatory filters documented in AGENTS.md (e.g. CultureID = 'en' when joining ProductModelProductDescriptionCulture). These filters belong inside the CTE.
  • Always include Production.Product.Name, Production.Product.ProductNumber, and Production.Product.ListPrice in the SELECT list (join to Production.Product if not already joined).
  • Alias all other columns with descriptive friendly names.
  • NEVER use MATCH, CONTAINS, FREETEXT, LIKE, or any full-text syntax.
  • Output ONLY the raw T-SQL — no explanation, no markdown fences.
  • SELECT only — never INSERT / UPDATE / DELETE / DROP / TRUNCATE / ALTER / CREATE / GRANT / REVOKE.
  • Qualify all table names with their schema (Production, Sales, Person, etc.). NEVER use 'dbo'.
"""

_VECTOR_REWRITE_PROMPT = """\
You are a T-SQL rewriter for Microsoft SQL Server 2025.

You will receive an exact-match T-SQL query that returned no rows, a pre-computed CAST embedding
expression, and the user's original question.

REWRITE RULES:
  • Identify the embedding column from the SQL or AGENTS.md guidance
    (look for a column named with 'embedding' or 'vector',
    e.g. Production.ProductDescription.DescriptionEmbedding).
    Use that exact column reference — do NOT guess or substitute another column.
  • Remove any equality or LIKE filter on the product name / description column.
  • Rewrite using a CTE that computes the distance ONCE as [Relevance Score]:

      WITH candidates AS (
          SELECT <all existing columns>,
                 VECTOR_DISTANCE('cosine', __CAST_EXPR__, <embedding_column>) AS [Relevance Score]
          FROM <existing tables and joins — preserve all non-text filters>
      )
      SELECT TOP {max_vector_rows} *
      FROM candidates
      ORDER BY [Relevance Score] ASC

  • NEVER put TOP inside the CTE — TOP belongs only on the outer SELECT.
  • NEVER add a WHERE filter on [Relevance Score] — always return the TOP N closest results regardless of distance.
  • NEVER call VECTOR_DISTANCE more than once — reference the [Relevance Score] alias in ORDER BY.
  • Preserve ALL mandatory filters from the original SQL (e.g. CultureID = 'en') inside the CTE.
  • Always include Production.Product.Name, Production.Product.ProductNumber, and Production.Product.ListPrice in the SELECT list (join to Production.Product if not already joined).
  • Use the literal token __CAST_EXPR__ as the embedding CAST expression — do NOT substitute or modify it.
  • NEVER use MATCH, CONTAINS, FREETEXT, or any full-text syntax.
  • Output ONLY the raw T-SQL — no explanation, no markdown fences.
  • SELECT only — never INSERT / UPDATE / DELETE / DROP / TRUNCATE / ALTER / CREATE / GRANT / REVOKE.
  • Qualify all table names with their schema (Production, Sales, Person, etc.). NEVER use 'dbo'.
"""


def _load_prompt(name: str, **vars: object) -> str:
    """Read a .prompty file, strip its YAML frontmatter, and substitute {{variable}} placeholders."""
    text = (_PROMPTS_DIR / f"{name}.prompty").read_text(encoding="utf-8")
    parts = text.split("---", 2)
    body = parts[2] if len(parts) >= 3 else parts[-1]
    for key, value in vars.items():
        body = body.replace("{{" + key + "}}", str(value))
    return body.strip()


_FENCE_RE = re.compile(r"```(?:sql|tsql|SQL|TSQL)?\s*(.*?)\s*```", re.DOTALL)

# ---------------------------------------------------------------------------
# Pipeline state — TypedDict passed through all LangGraph nodes
# ---------------------------------------------------------------------------


class State(TypedDict):
    """Typed state bag flowing through all LangGraph nodes."""

    person_id:       int        # PersonID of the logged-in customer (from Sales.Customer)
    user_input:      str
    agent_type:      str        # "customer_service" | "product_recommender" | "clarify" | "llm"
    tsql:            str        # SQL from Generator (possibly rewritten by VectorSearch)
    use_vector:      bool       # True when agent requests vector_pipeline (--VECTOR sentinel)
    columns:         list[str]
    rows:            list[list]  # list-of-list for JSON-safety
    final_answer:    str        # set when pipeline terminates early
    repair_attempts: int        # validator repair loop counter
    validate_error:       str        # last safety/compile error; empty = SQL is valid
    conversation_history: list[dict[str, str]]  # [{"user": ..., "assistant": ...}, ...]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _strip_fence(text: str) -> str:
    """Remove ```sql ... ``` fences the LLM sometimes emits around SQL."""
    m = _FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _history_messages(state: State) -> list:
    """Convert conversation_history to alternating HumanMessage / AIMessage objects."""
    msgs = []
    for turn in state.get("conversation_history", []):
        msgs.append(HumanMessage(content=turn["user"]))
        msgs.append(AIMessage(content=turn["assistant"]))
    return msgs


def _last_ai_content(result: dict) -> str:
    """Extract the text content of the last AIMessage from a create_agent result."""
    messages = result.get("messages", [])
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        if content and not getattr(msg, "tool_calls", None):
            return str(content).strip()
    return ""


async def _in_thread(fn, *args):
    """Run a blocking synchronous function in the default thread-pool executor."""
    return await asyncio.get_event_loop().run_in_executor(None, fn, *args)


# ---------------------------------------------------------------------------
# LLM client factory
# ---------------------------------------------------------------------------

def _make_llm():
    """
    Return a LangChain chat model configured from config.py.
    Supports Azure OpenAI (key or Entra) and standard OpenAI-compatible endpoints.
    """
    if _is_azure_endpoint(LLM_ENDPOINT):
        if LLM_API_KEY:
            return AzureChatOpenAI(
                azure_endpoint=LLM_ENDPOINT,
                api_key=LLM_API_KEY,
                api_version=LLM_API_VERSION,
                azure_deployment=LLM_MODEL,
            )
        if LLM_TENANT_ID:
            os.environ.setdefault("AZURE_TENANT_ID", LLM_TENANT_ID)
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(),
            "https://cognitiveservices.azure.com/.default",
        )
        return AzureChatOpenAI(
            azure_endpoint=LLM_ENDPOINT,
            azure_ad_token_provider=token_provider,
            api_version=LLM_API_VERSION,
            azure_deployment=LLM_MODEL,
        )
    return ChatOpenAI(
        base_url=LLM_ENDPOINT,
        api_key=LLM_API_KEY,
        model=LLM_MODEL,
    )


# ===========================================================================
# Agent factory — builds every create_agent instance + direct tool lists
# ===========================================================================

def _build_agents(llm, llm_svc, sql_svc) -> dict:
    """
    Create all agents using create_agent(llm, tools, system_prompt=prompt).

    Returns a dict with:
      "agents"             — named create_agent instances (LLM-driven nodes)
      "validate_tools"     — [safety_check_sql, compile_check_sql] for direct call
      "query_runner_tools" — [execute_sql_query] for direct call
    """
    from tools.orchestrator_tools  import make_orchestrator_tools
    from tools.sql_generator_tools import make_sql_generator_tools
    from tools.validate_tools      import make_validate_tools
    from tools.query_runner_tools  import make_query_runner_tools

    orchestrator_agent = create_agent(
        llm,
        make_orchestrator_tools(llm_svc),
        system_prompt=_load_prompt("orchestrator_agent"),
    )

    customer_service_agent = create_agent(
        llm,
        make_sql_generator_tools(sql_svc),
        system_prompt=_load_prompt("customer_service_agent", max_sql_rows=MAX_SQL_ROWS),
    )

    product_recommender_agent = create_agent(
        llm,
        make_sql_generator_tools(sql_svc),
        system_prompt=_load_prompt("product_recommender_agent", max_sql_rows=MAX_SQL_ROWS),
    )

    loyalty_programme_agent = create_agent(
        llm,
        make_sql_generator_tools(sql_svc),
        system_prompt=_load_prompt("loyalty_programme_agent", max_sql_rows=MAX_SQL_ROWS),
    )

    return {
        "agents": {
            "orchestrator":         orchestrator_agent,
            "customer_service":     customer_service_agent,
            "product_recommender":  product_recommender_agent,
            "loyalty_programme":    loyalty_programme_agent,
        },
        "validate_tools":     make_validate_tools(sql_svc)     if sql_svc else [],
        "query_runner_tools": make_query_runner_tools(sql_svc)  if sql_svc else [],
    }


# ===========================================================================
# Graph node factory — closes over agents, tools, and the trace callback
# ===========================================================================

def _build_orchestrator_node(orchestrator_agent, trace_fn: Callable) -> Callable:
    """Return the orchestrator async node function (parent graph node 1)."""

    async def orchestrator_node(state: State) -> dict:
        trace_fn("[Node 1: Orchestrator] routing to agent")
        result = await orchestrator_agent.ainvoke({
            "messages": [HumanMessage(content=state["user_input"])]
        })
        raw = _last_ai_content(result)

        # Try to parse a JSON routing decision
        try:
            data         = json.loads(_strip_fence(raw))
            agent_type   = str(data.get("agent_type", "")).lower()
            clarifying_q = str(data.get("clarifying_question", ""))

            if agent_type in {"customer_service", "product_recommender", "loyalty_programme"}:
                trace_fn(f"[Node 1: Orchestrator] agent_type={agent_type!r}")
                return {"agent_type": agent_type, "final_answer": ""}

            if agent_type == "clarify":
                trace_fn("[Node 1: Orchestrator] agent_type=clarify")
                return {"agent_type": agent_type, "final_answer": f"{_CLARIFY_PREFIX}{clarifying_q}"}

        except (json.JSONDecodeError, AttributeError):
            pass

        # Non-JSON: the agent answered the general question directly
        # (called chat_with_history tool or responded conversationally)
        trace_fn("[Node 1: Orchestrator] agent_type=llm (direct answer)")
        return {"agent_type": "llm", "final_answer": raw}

    return orchestrator_node


def _build_domain_node(sql_agent, label: str, trace_fn: Callable) -> Callable:
    """Return a domain SQL-generator node function (parent graph nodes 3–5)."""

    _VECTOR_SENTINEL = re.compile(r"^--VECTOR\b", re.IGNORECASE)
    # Matches a valid SQL start at the beginning of the string
    _SQL_START = re.compile(r"^(SELECT|WITH|--VECTOR)\b", re.IGNORECASE)
    # Finds embedded SQL after a natural-language preamble (SELECT/WITH at a line boundary)
    _SQL_EXTRACT = re.compile(r"(?:^|\n)((?:SELECT|WITH)\b.*)", re.IGNORECASE | re.DOTALL)

    async def domain_node(state: State) -> dict:
        trace_fn(f"[{label}] grounding schema and generating T-SQL")
        result = await sql_agent.ainvoke({
            "messages": [*_history_messages(state), HumanMessage(content=state["user_input"])]
        })
        tsql = _strip_fence(_last_ai_content(result))
        # If the output doesn't start with SQL, try to extract an embedded SQL block
        # (the agent sometimes emits a natural-language preamble before the query)
        if not tsql.startswith(_CLARIFY_PREFIX) and not _SQL_START.match(tsql):
            m = _SQL_EXTRACT.search(tsql)
            if m:
                tsql = m.group(1).strip()
        # After extraction, anything that still isn't SQL is a clarifying question
        is_clarify = tsql.startswith(_CLARIFY_PREFIX) or not _SQL_START.match(tsql)
        if is_clarify:
            question = tsql[len(_CLARIFY_PREFIX):].strip() if tsql.startswith(_CLARIFY_PREFIX) else tsql
            trace_fn(f"[{label}] clarifying question: {question!r}")
            return {"tsql": "", "use_vector": False, "repair_attempts": 0,
                    "validate_error": "", "final_answer": f"{_CLARIFY_PREFIX}{question}"}
        use_vector = bool(_VECTOR_SENTINEL.match(tsql))
        if use_vector:
            tsql = ""  # vector_search_node generates the SQL directly
            trace_fn(f"[{label}] --VECTOR sentinel detected; routing to vector_pipeline")
        else:
            trace_fn(f"[{label}] SQL:\n{tsql}")
        return {"tsql": tsql, "use_vector": use_vector, "repair_attempts": 0, "validate_error": ""}

    return domain_node


def _build_execution_nodes(
    llm,
    llm_svc,
    sql_svc,
    domain_agents:      dict,
    validate_tools:     list,
    query_runner_tools: list,
    trace_fn:           Callable,
) -> dict:
    """
    Return the shared execution node functions used by both sub-graphs.
    Nodes: validate, repair, vector_search, query_runner, responder.
    The same callables are registered in both sql_pipeline and vector_pipeline.
    """
    _vtool  = {t.name: t for t in validate_tools}
    _qrtool = {t.name: t for t in query_runner_tools}

    # ── Validate ──────────────────────────────────────────────────────────────

    async def validate_node(state: State) -> dict:
        trace_fn(f"[Validate] checking SQL (repair_attempts={state['repair_attempts']})")

        safety_tool  = _vtool.get("safety_check_sql")
        compile_tool = _vtool.get("compile_check_sql")

        if safety_tool:
            safety_err = safety_tool.invoke({"tsql": state["tsql"]})
            if safety_err:
                trace_fn(f"[Validate] safety violation: {safety_err}")
                return {"validate_error": f"safety:{safety_err}"}

        if compile_tool:
            try:
                db_err = await _in_thread(compile_tool.invoke, {"tsql": state["tsql"]})
            except Exception as exc:
                db_err = str(exc)

            if db_err:
                trace_fn(f"[Validate] compile error: {db_err}")
                return {"validate_error": db_err}

        trace_fn("[Validate] SQL is valid")
        return {"validate_error": ""}

    # ── Repair ────────────────────────────────────────────────────────────────

    _TABLE_REF_RE = re.compile(
        r'\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b'
    )
    _SCHEMA_NAMES = frozenset({
        "Sales", "Person", "Production", "HumanResources", "Purchasing", "Loyalty"
    })

    async def repair_node(state: State) -> dict:
        attempt = state["repair_attempts"] + 1
        trace_fn(f"[Repair] attempt {attempt}/{_MAX_REPAIR_ATTEMPTS}")
        error = state["validate_error"]

        # Fetch live schema for tables referenced in the faulty SQL so the LLM
        # can correct column/table names without falling back on hallucinated knowledge
        schema_context = ""
        if sql_svc:
            try:
                refs = [
                    f"{m.group(1)}.{m.group(2)}"
                    for m in _TABLE_REF_RE.finditer(state["tsql"])
                    if m.group(1) in _SCHEMA_NAMES
                ]
                if refs:
                    schema_context = await _in_thread(
                        sql_svc.get_table_schema, refs
                    )
            except Exception:
                pass  # schema fetch is best-effort; proceed without it

        if error.startswith("safety:"):
            violation = error[len("safety:"):]
            user_msg = (
                f"Question: {state['user_input']}\n\n"
                f"Faulty SQL:\n{state['tsql']}\n\n"
                f"Safety violation to fix: {violation}"
            )
        else:
            user_msg = (
                f"Question: {state['user_input']}\n\n"
                f"Faulty SQL:\n{state['tsql']}\n\n"
                f"Error: {error}"
            )

        if schema_context:
            user_msg += f"\n\nLive table schema (use ONLY these column names):\n{schema_context}"

        repair_prompt = _REPAIR_PROMPT.format(max_sql_rows=MAX_SQL_ROWS)
        result = await llm.ainvoke([
            SystemMessage(content=repair_prompt),
            HumanMessage(content=user_msg),
        ])
        tsql = _strip_fence(result.content)
        return {"tsql": tsql, "repair_attempts": attempt}

    # ── Vector Search ─────────────────────────────────────────────────────────

    async def vector_search_node(state: State) -> dict:
        from tools.vector_search_tools import create_embedding_cast
        try:
            if not state["tsql"]:
                # Direct vector path: generate SQL from scratch using AGENTS.md
                trace_fn("[Vector Search] generating vector SQL from scratch")
                async def _empty(): return ""
                _VECTOR_SCHEMA_TABLES = [
                    "Production.Product",
                    "Production.ProductDescription",
                    "Production.ProductModel",
                    "Production.ProductModelProductDescriptionCulture",
                    "Production.ProductSubcategory",
                    "Production.ProductCategory",
                ]
                t0 = time.perf_counter()
                trace_fn("[Vector Search]   step 1/3 — embedding query + fetching schema (parallel)...")
                cast_expr, agent_notes, table_schema = await asyncio.gather(
                    _in_thread(create_embedding_cast, state["user_input"], llm_svc),
                    _in_thread(sql_svc.get_agent_notes) if sql_svc else _empty(),
                    _in_thread(sql_svc.get_table_schema, _VECTOR_SCHEMA_TABLES) if sql_svc else _empty(),
                )
                trace_fn(f"[Vector Search]   step 1/3 done in {time.perf_counter() - t0:.1f}s")
                t1 = time.perf_counter()
                trace_fn("[Vector Search]   step 2/3 — generating SQL with LLM...")
                user_msg = (
                    f"User question: {state['user_input']}\n\n"
                    f"AGENTS.md guidance:\n{agent_notes}\n\n"
                    f"Live table schema (use ONLY these column names — do not invent others):\n{table_schema}\n\n"
                    f"CAST expression: use the placeholder __CAST_EXPR__ wherever the embedding CAST is needed."
                )
                result = await llm.ainvoke([
                    SystemMessage(content=_VECTOR_GENERATE_PROMPT.format(max_vector_rows=MAX_VECTOR_ROWS)),
                    HumanMessage(content=user_msg),
                ])
                trace_fn(f"[Vector Search]   step 2/3 done in {time.perf_counter() - t1:.1f}s")
                trace_fn(f"[Vector Search]   step 3/3 — total so far: {time.perf_counter() - t0:.1f}s (SQL execution next)")
            else:
                # Fallback path: rewrite exact-match SQL that returned no rows
                trace_fn("[Vector Search] rewriting exact-match SQL for vector similarity")
                cast_expr = await _in_thread(create_embedding_cast, state["user_input"], llm_svc)
                user_msg = (
                    f"User question: {state['user_input']}\n\n"
                    f"CAST expression: use the placeholder __CAST_EXPR__ wherever the embedding CAST is needed.\n\n"
                    f"T-SQL to rewrite:\n{state['tsql']}"
                )
                result = await llm.ainvoke([
                    SystemMessage(content=_VECTOR_REWRITE_PROMPT.format(max_vector_rows=MAX_VECTOR_ROWS)),
                    HumanMessage(content=user_msg),
                ])

            raw_tsql = _strip_fence(result.content)
            placeholder_found = "__CAST_EXPR__" in raw_tsql
            tsql = raw_tsql.replace("__CAST_EXPR__", cast_expr)
            if not placeholder_found:
                trace_fn("[Vector Search] WARNING: __CAST_EXPR__ placeholder not found in LLM output — SQL may be invalid")
            trace_fn(f"[Vector Search] SQL:\n{raw_tsql}")
            return {"tsql": tsql}
        except Exception as exc:
            trace_fn(f"[Vector Search] failed ({exc})")
            return {}

    # ── Query Runner ──────────────────────────────────────────────────────────

    async def query_runner_node(state: State) -> dict:
        trace_fn("[Query Runner] executing SQL via execute_sql_query tool")
        exec_tool = _qrtool.get("execute_sql_query")
        if not exec_tool:
            return {"final_answer": "[Configuration Error] SQL service not available."}
        try:
            result_json = await _in_thread(exec_tool.invoke, {"tsql": state["tsql"]})
            data        = json.loads(result_json)
            cols        = data["columns"]
            rws         = data["rows"]
            trace_fn(f"[Query Runner] {len(rws)} row(s), {len(cols)} col(s)")
            return {"columns": cols, "rows": rws, "final_answer": ""}
        except Exception as exc:
            trace_fn(f"[Query Runner] error: {exc}")
            return {"final_answer": f"[Execution Error]\n{exc}"}

    # ── Responder ─────────────────────────────────────────────────────────────

    async def responder_node(state: State) -> dict:
        trace_fn("[Responder] returning query results to domain agent for response")
        if not state["rows"]:
            return {
                "final_answer": (
                    f"The query returned no results.\n\n"
                    f"QUERY\n```sql\n{state['tsql']}\n```\n\nDATA\n(no rows returned)"
                )
            }
        agent = domain_agents.get(state["agent_type"]) or domain_agents["customer_service"]
        # Redact the embedding vector from the SQL shown to the agent — it's
        # thousands of tokens of floats that serve no purpose in the response step.
        _CAST_RE = re.compile(r"CAST\s*\(\s*'\[[\d.,\s\-e]+\]'\s*AS\s*VECTOR\s*\(\d+\)\s*\)", re.IGNORECASE)
        display_tsql = _CAST_RE.sub("CAST(<embedding> AS VECTOR)", state["tsql"])
        user_msg = (
            f"The following SQL query was executed to answer the user's question.\n\n"
            f"Question: {state['user_input']}\n\n"
            f"SQL:\n{display_tsql}\n\n"
            f"Results ({len(state['rows'])} rows):\n"
            f"columns={json.dumps(state['columns'])}\n"
            f"rows={json.dumps(state['rows'])}"
        )
        result = await agent.ainvoke({
            "messages": [HumanMessage(content=user_msg)]
        })
        answer = _last_ai_content(result)
        trace_fn("[Responder] done")
        return {"final_answer": answer}

    return {
        "validate":      validate_node,
        "repair":        repair_node,
        "vector_search": vector_search_node,
        "query_runner":  query_runner_node,
        "responder":     responder_node,
    }


# ===========================================================================
# Graph builder
# ===========================================================================

def _build_sql_subgraph(exec_nodes: dict):
    """Compile the exact-SQL execution pipeline: validate → repair → query_runner → summarizer."""

    async def max_repairs_node(state: State) -> dict:
        return {
            "final_answer": (
                f"[SQL Error] Could not produce a valid query after "
                f"{_MAX_REPAIR_ATTEMPTS} repair attempts."
            )
        }

    def route_after_validate(state: State) -> str:
        if not state["validate_error"]:
            return "query_runner"
        if state["repair_attempts"] < _MAX_REPAIR_ATTEMPTS:
            return "repair"
        return "max_repairs"

    def route_after_query_runner(state: State) -> str:
        return END if state["final_answer"] else "responder"

    sg = StateGraph(State)
    sg.add_node("validate",     exec_nodes["validate"])
    sg.add_node("repair",       exec_nodes["repair"])
    sg.add_node("query_runner", exec_nodes["query_runner"])
    sg.add_node("responder",    exec_nodes["responder"])
    sg.add_node("max_repairs",  max_repairs_node)

    sg.add_edge(START, "validate")
    sg.add_conditional_edges(
        "validate",
        route_after_validate,
        {"query_runner": "query_runner", "repair": "repair", "max_repairs": "max_repairs"},
    )
    sg.add_edge("repair", "validate")
    sg.add_conditional_edges(
        "query_runner",
        route_after_query_runner,
        {END: END, "responder": "responder"},
    )
    sg.add_edge("responder", END)
    sg.add_edge("max_repairs", END)

    return sg.compile()


def _build_vector_subgraph(exec_nodes: dict):
    """Compile the vector-search pipeline: vector_search → validate → repair → query_runner → summarizer."""

    async def max_repairs_node(state: State) -> dict:
        return {
            "final_answer": (
                f"[SQL Error] Could not produce a valid query after "
                f"{_MAX_REPAIR_ATTEMPTS} repair attempts."
            )
        }

    def route_after_validate(state: State) -> str:
        if not state["validate_error"]:
            return "query_runner"
        if state["repair_attempts"] < _MAX_REPAIR_ATTEMPTS:
            return "repair"
        return "max_repairs"

    def route_after_query_runner(state: State) -> str:
        return END if state["final_answer"] else "responder"

    sg = StateGraph(State)
    sg.add_node("vector_search", exec_nodes["vector_search"])
    sg.add_node("validate",      exec_nodes["validate"])
    sg.add_node("repair",        exec_nodes["repair"])
    sg.add_node("query_runner",  exec_nodes["query_runner"])
    sg.add_node("responder",     exec_nodes["responder"])
    sg.add_node("max_repairs",   max_repairs_node)

    sg.add_edge(START, "vector_search")
    sg.add_edge("vector_search", "validate")
    sg.add_conditional_edges(
        "validate",
        route_after_validate,
        {"query_runner": "query_runner", "repair": "repair", "max_repairs": "max_repairs"},
    )
    sg.add_edge("repair", "validate")
    sg.add_conditional_edges(
        "query_runner",
        route_after_query_runner,
        {END: END, "responder": "responder"},
    )
    sg.add_edge("responder", END)
    sg.add_edge("max_repairs", END)

    return sg.compile()


def _build_graph(
    orchestrator_node: Callable,
    domain_nodes:      dict,
    sql_subgraph,
    vector_subgraph,
) -> object:
    """
    Wire the parent StateGraph (8 nodes).

    Flow:
      START → orchestrator → <domain agent> → sql_pipeline → sql_fallback ─┐
                           ↘ END  (clarify / llm / direct answers)         │ (no rows)
                                                                            ↓
                                                               vector_pipeline → END
                                              sql_pipeline → END  (rows found or error)
    """

    def route_after_orchestrator(state: State) -> str:
        if state["final_answer"]:
            return END
        agent_type = state["agent_type"]
        if agent_type == "product_recommender":
            return "product_recommender"
        if agent_type == "loyalty_programme":
            return "loyalty_programme"
        return "customer_service"

    def route_after_domain(state: State) -> str:
        if state["final_answer"]:
            return END
        return "vector_pipeline" if state["use_vector"] else "sql_pipeline"

    async def sql_fallback_node(state: State) -> dict:
        """Reset pipeline state so vector_pipeline can run cleanly after a sql_pipeline no-rows result."""
        return {"final_answer": "", "repair_attempts": 0, "validate_error": "", "use_vector": True}

    def route_after_sql_pipeline(state: State) -> str:
        """Fall back to vector_pipeline when sql_pipeline returned no rows and no error.

        The responder inside sql_pipeline sets final_answer to a human-readable
        'no results' message (does NOT start with '[').  Error/repair failures
        always start with '[', so we use that to distinguish them.
        """
        if not state["rows"] and not state["final_answer"].startswith("["):
            return "sql_fallback"
        return END

    g = StateGraph(State)
    g.add_node("orchestrator",        orchestrator_node)
    g.add_node("customer_service",    domain_nodes["customer_service"])
    g.add_node("product_recommender", domain_nodes["product_recommender"])
    g.add_node("loyalty_programme",   domain_nodes["loyalty_programme"])
    g.add_node("sql_pipeline",        sql_subgraph)
    g.add_node("sql_fallback",        sql_fallback_node)
    g.add_node("vector_pipeline",     vector_subgraph)

    g.add_edge(START, "orchestrator")
    g.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
            END:                   END,
            "customer_service":    "customer_service",
            "product_recommender": "product_recommender",
            "loyalty_programme":   "loyalty_programme",
        },
    )
    for domain in ("customer_service", "product_recommender", "loyalty_programme"):
        g.add_conditional_edges(
            domain,
            route_after_domain,
            {"sql_pipeline": "sql_pipeline", "vector_pipeline": "vector_pipeline", END: END},
        )
    g.add_conditional_edges(
        "sql_pipeline",
        route_after_sql_pipeline,
        {END: END, "sql_fallback": "sql_fallback"},
    )
    g.add_edge("sql_fallback",    "vector_pipeline")
    g.add_edge("vector_pipeline", END)

    return g.compile()


# ===========================================================================
# AgentOrchestrator — public synchronous entry point
# ===========================================================================

class AgentOrchestrator:
    """
    Builds a LangGraph StateGraph workflow at init time and runs it on every call.
    The synchronous `process()` API bridges to the async graph via asyncio.run(),
    which is safe to call from the background worker thread the Tkinter UI uses.
    """

    def __init__(self, trace_callback: Callable[[str], None] | None = None, person_id: int = 0) -> None:
        from config import SQL_SERVER

        self._person_id = person_id
        self._cb  = trace_callback or (lambda _: None)
        self._pending_question: str | None = None
        self._conversation_history: list[dict[str, str]] = []

        self._llm_ok = LLM_ENDPOINT != _LLM_PLACEHOLDER and bool(LLM_ENDPOINT)
        self._sql_ok = SQL_SERVER   != _SQL_PLACEHOLDER  and bool(SQL_SERVER)

        self._llm_svc = None
        self._sql_svc = None
        self._graph   = None

        if self._llm_ok:
            from services.llm_service import LLMService
            self._llm_svc = LLMService()

        if self._sql_ok:
            from services.sql_service import SQLService
            self._sql_svc = SQLService(person_id=self._person_id)

        if self._llm_ok:
            llm       = _make_llm()
            artifacts = _build_agents(llm, self._llm_svc, self._sql_svc)
            agents    = artifacts["agents"]

            orch_node    = _build_orchestrator_node(agents["orchestrator"], self._cb)
            domain_nodes = {
                "customer_service":    _build_domain_node(agents["customer_service"],    "Customer Service",    self._cb),
                "product_recommender": _build_domain_node(agents["product_recommender"], "Product Recommender", self._cb),
                "loyalty_programme":   _build_domain_node(agents["loyalty_programme"],   "Loyalty Programme",   self._cb),
            }
            exec_nodes      = _build_execution_nodes(
                llm,
                self._llm_svc,
                self._sql_svc,
                {
                    "customer_service":    agents["customer_service"],
                    "product_recommender": agents["product_recommender"],
                    "loyalty_programme":   agents["loyalty_programme"],
                },
                artifacts["validate_tools"],
                artifacts["query_runner_tools"],
                self._cb,
            )
            sql_subgraph    = _build_sql_subgraph(exec_nodes)
            vector_subgraph = _build_vector_subgraph(exec_nodes)
            self._graph     = _build_graph(
                orch_node, domain_nodes, sql_subgraph, vector_subgraph
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, user_input: str) -> str:
        """Synchronous entry point — bridges to the async LangGraph pipeline."""
        user_input = user_input.strip()
        if not user_input:
            return ""

        # Merge a clarification answer with the original pending question
        if self._pending_question is not None:
            user_input = (
                f"{self._pending_question}\n"
                f"Clarification from user: {user_input}\n"
                f"You now have enough information — generate the T-SQL query."
            )
            self._pending_question = None

        result = asyncio.run(self._run_workflow(user_input))

        # Orchestrator asked a clarifying question — save state for next turn
        if isinstance(result, str) and result.startswith(_CLARIFY_PREFIX):
            self._pending_question = user_input
            return result[len(_CLARIFY_PREFIX):]

        # Store the completed turn in conversation history
        self._conversation_history.append({"user": user_input, "assistant": result})
        if len(self._conversation_history) > _MAX_CONV_HISTORY:
            self._conversation_history.pop(0)

        return result

    def clear_conversation(self) -> None:
        """Reset pending clarification state and LLM conversation history."""
        self._pending_question = None
        self._conversation_history.clear()
        if self._llm_svc:
            self._llm_svc.clear_history()

    # ── Async workflow ────────────────────────────────────────────────────────

    async def _run_workflow(self, user_input: str) -> str:
        if not self._llm_ok or self._graph is None:
            return "No LLM is configured — set LLM_* values in config.py."

        initial_state: State = {
            "person_id":            self._person_id,
            "user_input":           user_input,
            "agent_type":           "",
            "tsql":                 "",
            "use_vector":           False,
            "columns":              [],
            "rows":                 [],
            "final_answer":         "",
            "repair_attempts":      0,
            "validate_error":       "",
            "conversation_history": list(self._conversation_history),
        }

        result = await self._graph.ainvoke(initial_state)
        return result.get("final_answer") or "[No response from pipeline]"
