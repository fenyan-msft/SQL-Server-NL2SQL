"""
Orchestrator Agent Tools
========================
One tool: chat_with_history — answers general (non-SQL) questions via the
LLMService, which retains full conversational context across turns.

The Orchestrator Agent calls this tool when it classifies intent as "llm"
(general knowledge question that does not require database access).
"""

from __future__ import annotations

from langchain_core.tools import tool


def make_orchestrator_tools(llm_svc) -> list:
    """Return tools for the Orchestrator Agent.

    Returns an empty list when llm_svc is unavailable so the agent still
    works for intent classification even without a chat-history backend.
    """
    if llm_svc is None:
        return []

    @tool
    def chat_with_history(question: str) -> str:
        """Answer a general (non-SQL, non-data) question.

        Uses the LLM conversation service which retains full conversational
        context across turns. Call this tool when the user asks something that
        does not require querying the database — e.g. explanations, policies,
        definitions, or follow-up questions about a previous answer.
        """
        return llm_svc.chat(question)

    return [chat_with_history]
