"""
SQL Generator Agent Tools
=========================
Domain agents (customer_service, customer, product_recommender) self-ground
using get_agent_notes + get_table_schema so no separate grounder node is
needed in the graph.
"""

from __future__ import annotations


def make_sql_generator_tools(sql_svc) -> list:
    """Return grounding tools for domain SQL-generator agents."""
    from tools.grounder_tools import make_grounder_tools
    return make_grounder_tools(sql_svc) if sql_svc else []
