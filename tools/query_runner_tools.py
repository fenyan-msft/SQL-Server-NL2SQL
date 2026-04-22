"""
Query Runner Node Tools
=======================
One tool: execute_sql_query — executes a validated T-SQL SELECT statement
against SQL Server and returns the result as a JSON object containing
'columns' (list of strings) and 'rows' (list of lists).

The Query Runner node calls this tool directly (no LLM agent in the loop).
The call is blocking (pyodbc) and must be wrapped in _in_thread by the caller.
"""

from __future__ import annotations

import datetime
import decimal
import json

from langchain_core.tools import tool


class _SqlEncoder(json.JSONEncoder):
    """Serialise SQL Server types that the default encoder cannot handle."""

    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, datetime.timedelta):
            return str(obj)
        if isinstance(obj, bytes):
            return obj.hex()
        return super().default(obj)


def make_query_runner_tools(sql_svc) -> list:
    """Return tools for the Query Runner node."""

    @tool
    def execute_sql_query(tsql: str) -> str:
        """Execute a validated T-SQL SELECT query against SQL Server.

        Returns a JSON string with two keys:
          "columns" — list of column name strings
          "rows"    — list of rows, where each row is a list of values

        Raises on execution error.

        WARNING: This call is blocking (pyodbc).  The caller must use
        asyncio.run_in_executor (via _in_thread) to avoid blocking the event loop.
        """
        columns, rows = sql_svc.execute_query(tsql)
        return json.dumps(
            {
                "columns": list(columns),
                "rows":    [list(row) for row in rows],
            },
            cls=_SqlEncoder,
        )

    return [execute_sql_query]
