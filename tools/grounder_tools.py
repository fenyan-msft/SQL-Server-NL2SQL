"""
Grounder Tools
==============
Two tools:
  get_agent_notes   — fetches the AGENTS.md guidance document from SQL Server,
                      which contains the full database schema, table descriptions,
                      column definitions, primary/foreign key relationships,
                      embedding columns, and example T-SQL query patterns.
  get_table_schema  — fetches live column definitions from INFORMATION_SCHEMA
                      for a specific list of tables identified as relevant to
                      the user's question.

The Grounder calls get_agent_notes first to identify relevant tables,
then calls get_table_schema to retrieve their exact live column definitions.
"""

from __future__ import annotations

from langchain_core.tools import tool


def make_grounder_tools(sql_svc) -> list:
    """Return tools for the Grounder."""

    @tool
    def get_agent_notes() -> str:
        """Retrieve the AGENTS.md guidance document from SQL Server.

        This document contains the complete database schema, table and column
        descriptions, primary/foreign key relationships, embedding column names,
        business rules, and example T-SQL query patterns needed to answer
        natural-language questions about the data.

        Always call this tool before attempting to extract schema context.
        """
        return sql_svc.get_agent_notes()

    @tool
    def get_table_schema(tables: str) -> str:
        """Retrieve live column definitions from the database for specific tables.

        Call this after get_agent_notes, once you have identified which tables
        are needed to answer the user's question. Returns the exact column names,
        data types, lengths, and nullability from INFORMATION_SCHEMA.

        Args:
            tables: Comma-separated list of fully-qualified table names in
                    'Schema.Table' format, e.g. 'Person.Person,Person.EmailAddress'.
        """
        table_list = [t.strip() for t in tables.split(",") if t.strip()]
        return sql_svc.get_table_schema(table_list)

    return [get_agent_notes, get_table_schema]
