"""
Validate Node Tools
===================
Two tools used directly by the Validate node (no LLM agent in the loop):

  safety_check_sql   — static regex checks that reject any non-SELECT statement
  compile_check_sql  — dry-runs the query against SQL Server with SET NOEXEC ON

The Validate node calls both tools synchronously.  The compile check is
blocking (pyodbc) and must be wrapped in _in_thread by the caller.
"""

from __future__ import annotations

import re

from langchain_core.tools import tool

_READONLY_RE     = re.compile(r"^\s*(SELECT|WITH|EXEC(?:UTE)?\s+sp_help)\b", re.I)
_FORBIDDEN_KW_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|GRANT|REVOKE)\b", re.I
)
_FORBIDDEN_EX_RE = re.compile(r"\bEXEC(?:UTE)?\s+(?!sp_help\b)", re.I)
# Strip bracket-quoted identifiers and single-quoted string literals before
# keyword scanning to avoid false positives on aliases/values like
# [Last Inventory Update] or 'last update'.
_BRACKET_QUOTED_RE = re.compile(r"\[[^\]]*\]")
_STRING_LITERAL_RE = re.compile(r"'[^']*'")


def make_validate_tools(sql_svc) -> list:
    """Return tools for the Validate node."""

    @tool
    def safety_check_sql(tsql: str) -> str:
        """Run static safety-regex checks against a T-SQL query.

        Returns an empty string when the query is safe to proceed.
        Returns a human-readable violation description if the query
        attempts any write operation or begins with a forbidden keyword.
        """
        if not _READONLY_RE.match(tsql):
            return "Query does not begin with SELECT / WITH / sp_help."
        # Remove bracket-quoted identifiers and string literals before keyword
        # scanning to avoid false positives on aliases/values containing
        # reserved words (e.g. [Last Inventory Update], 'last update').
        stripped = _BRACKET_QUOTED_RE.sub("[]", tsql)
        stripped = _STRING_LITERAL_RE.sub("''", stripped)
        m = _FORBIDDEN_KW_RE.search(stripped)
        if m:
            return f"Forbidden keyword: {m.group(0).upper()}"
        m = _FORBIDDEN_EX_RE.search(stripped)
        if m:
            return "EXEC / EXECUTE of a non-sp_help procedure is forbidden."
        return ""

    @tool
    def compile_check_sql(tsql: str) -> str:
        """Dry-run a T-SQL statement using SET NOEXEC ON.

        Sends the query to SQL Server for compilation without executing it.
        Returns an empty string when the SQL compiles without errors.
        Returns the SQL Server error message string on failure.

        WARNING: This call is blocking (pyodbc).  The caller must use
        asyncio.run_in_executor (via _in_thread) to avoid blocking the event loop.
        """
        conn   = sql_svc.get_connection()
        cursor = conn.cursor()
        db_err = None
        try:
            cursor.execute("SET NOEXEC ON")
            try:
                cursor.execute(tsql)
            except Exception as exc:
                db_err = str(exc)
            finally:
                cursor.execute("SET NOEXEC OFF")
        finally:
            try:
                cursor.cancel()
            except Exception:
                pass
            cursor.close()
        return db_err or ""

    return [safety_check_sql, compile_check_sql]
