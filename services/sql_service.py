"""
SQL Server Service
Connects to SQL Server via pyodbc, introspects the schema to provide context
for T-SQL generation, and executes read-only SELECT queries safely.
"""

from __future__ import annotations

import re

import pyodbc

from config import (
    SQL_SERVER,
    SQL_DATABASE,
    SQL_DRIVER,
    SQL_USERNAME,
    SQL_PASSWORD,
    SQL_AUTHENTICATION,
    SQL_ENCRYPT,
    SQL_TRUST_SERVER_CERTIFICATE,
    SQL_CONNECTION_TIMEOUT,
    MAX_SQL_ROWS,
)

_NOT_CONFIGURED = "YOUR_SQL_SERVER_HERE"

# Only these statement types are permitted for execution
_ALLOWED_STMT_PATTERN = re.compile(
    r"^\s*(SELECT|WITH|EXEC\s+sp_help|EXECUTE\s+sp_help)\b",
    re.IGNORECASE,
)

_LOOKUP_COL_RE = re.compile(
    r"\[?([A-Za-z0-9_]+)\]?\.\[?([A-Za-z0-9_]+)\]?\.\[?([A-Za-z0-9_]+)\]?"
)


def _parse_lookup_columns(agents_md: str) -> list[tuple[str, str, str]]:
    """Extract (schema, table, column) triples from the #Lookups section of AGENTS.md."""
    cols: list[tuple[str, str, str]] = []
    in_lookups = False
    for line in agents_md.splitlines():
        stripped = line.strip()
        if re.match(r"^#{1,3}\s+Lookups?\b", stripped, re.IGNORECASE):
            in_lookups = True
            continue
        if in_lookups and re.match(r"^#{1,3}\s+", stripped):
            break
        if in_lookups:
            m = _LOOKUP_COL_RE.search(stripped)
            if m:
                cols.append((m.group(1), m.group(2), m.group(3)))
    return cols


class SQLService:
    """Manages a lazy connection to SQL Server and exposes query execution."""

    def __init__(self, person_id: int | None = None):
        if SQL_SERVER == _NOT_CONFIGURED:
            raise RuntimeError(
                "SQL_SERVER is not configured in config.py. "
                "Please replace the placeholder with your actual server name."
            )
        self._person_id = person_id
        self._connection: pyodbc.Connection | None = None
        self._schema_cache: str | None = None
        self._agent_notes_cache: str | None = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connection_string(self) -> str:
        encrypt    = "yes" if SQL_ENCRYPT else "no"
        trust_cert = "yes" if SQL_TRUST_SERVER_CERTIFICATE else "no"
        auth_mode  = (SQL_AUTHENTICATION or "").strip()
        username   = (SQL_USERNAME or "").strip()
        password   = SQL_PASSWORD or ""
        parts = [
            f"DRIVER={SQL_DRIVER}",
            f"SERVER={SQL_SERVER}",
            f"DATABASE={SQL_DATABASE}",
            f"Encrypt={encrypt}",
            f"TrustServerCertificate={trust_cert}",
            "MARS_Connection=yes",
        ]
        if auth_mode:
            parts.append(f"Authentication={auth_mode}")
            if username:
                parts.append(f"UID={username}")
            if password:
                parts.append(f"PWD={password}")
        else:
            if username:
                parts.append(f"UID={username}")
                parts.append(f"PWD={password}")
            else:
                parts.append("Trusted_Connection=yes")
        return ";".join(parts) + ";"

    def get_connection(self) -> pyodbc.Connection:
        """Return the active connection, reconnecting if necessary."""
        if self._connection is None:
            self._connection = pyodbc.connect(
                self._connection_string(),
                timeout=SQL_CONNECTION_TIMEOUT,
            )
            if self._person_id is not None:
                self._apply_session_context(self._connection)
        return self._connection

    def _apply_session_context(self, conn: pyodbc.Connection) -> None:
        """Set PersonID in SQL Server session context for this connection."""
        cursor = conn.cursor()
        try:
            cursor.execute(
                "EXEC sp_set_session_context @key = N'PersonID', @value = ?",
                self._person_id,
            )
            conn.commit()
        finally:
            cursor.close()

    def close(self) -> None:
        """Close the database connection if open."""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            finally:
                self._connection = None

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

    # def get_schema(self) -> str:
    #     """
    #     Return a compact text description of all user tables and their columns.
    #     Result is cached for the lifetime of this service instance.
    #     """
    #     if self._schema_cache is not None:
    #         return self._schema_cache

    #     conn   = self.get_connection()
    #     cursor = conn.cursor()

    #     cursor.execute(
    #         """
    #         SELECT
    #             t.TABLE_SCHEMA,
    #             t.TABLE_NAME,
    #             c.COLUMN_NAME,
    #             c.DATA_TYPE,
    #             c.CHARACTER_MAXIMUM_LENGTH,
    #             c.IS_NULLABLE
    #         FROM INFORMATION_SCHEMA.TABLES  AS t
    #         JOIN INFORMATION_SCHEMA.COLUMNS AS c
    #           ON  c.TABLE_SCHEMA = t.TABLE_SCHEMA
    #           AND c.TABLE_NAME   = t.TABLE_NAME
    #         WHERE t.TABLE_TYPE = 'BASE TABLE'
    #         ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME, c.ORDINAL_POSITION
    #         """
    #     )

    #     lines: list[str] = []
    #     current_table: str | None = None

    #     for row in cursor.fetchall():
    #         full_name = f"[{row.TABLE_SCHEMA}].[{row.TABLE_NAME}]"
    #         if full_name != current_table:
    #             current_table = full_name
    #             lines.append(f"\nTable: {full_name}")

    #         max_len = (
    #             f"({row.CHARACTER_MAXIMUM_LENGTH})"
    #             if row.CHARACTER_MAXIMUM_LENGTH
    #             else ""
    #         )
    #         nullable = "NULL" if row.IS_NULLABLE == "YES" else "NOT NULL"
    #         lines.append(
    #             f"  {row.COLUMN_NAME}  {row.DATA_TYPE}{max_len}  {nullable}"
    #         )

    #     self._schema_cache = "\n".join(lines)
    #     return self._schema_cache

    # ------------------------------------------------------------------
    # Agent notes (extended property 'AGENTS.md')
    # ------------------------------------------------------------------

    def get_agent_notes(self) -> str:
        """
        Return the combined AGENTS.md guidance from:
          1. The database-level extended property (class = 0, name = 'AGENTS.md')
          2. All table-level extended properties (class = 1, name = 'AGENTS.md'),
             prefixed with the fully-qualified table name for each table that has one.
        Result is cached for the lifetime of this service instance.
        """
        if self._agent_notes_cache is not None:
            return self._agent_notes_cache

        conn   = self.get_connection()
        cursor = conn.cursor()

        try:
            # Database-level note
            cursor.execute(
                "SELECT CAST(value AS NVARCHAR(MAX)) "
                "FROM sys.extended_properties "
                "WHERE class = 0 AND name = N'AGENTS.md'"
            )
            row = cursor.fetchone()
            db_note = row[0] if row else ""

            # Table-level notes
            cursor.execute(
                "SELECT SCHEMA_NAME(t.schema_id) AS TableSchema, "
                "       t.name AS TableName, "
                "       CAST(ep.value AS NVARCHAR(MAX)) AS Note "
                "FROM sys.extended_properties AS ep "
                "JOIN sys.tables AS t ON t.object_id = ep.major_id "
                "WHERE ep.class = 1 AND ep.minor_id = 0 AND ep.name = N'AGENTS.md' "
                "ORDER BY TableSchema, TableName"
            )
            table_rows = cursor.fetchall()

            # Column-level notes: MS_Description only for columns listed under #Lookups in AGENTS.md
            lookup_cols = _parse_lookup_columns(db_note)
            column_rows: list = []
            if lookup_cols:
                where_parts = " OR ".join(
                    "(SCHEMA_NAME(t.schema_id) = ? AND t.name = ? AND c.name = ?)"
                    for _ in lookup_cols
                )
                params: list = []
                for schema, table, col in lookup_cols:
                    params.extend([schema, table, col])
                cursor.execute(
                    "SELECT SCHEMA_NAME(t.schema_id) AS TableSchema, "
                    "       t.name AS TableName, "
                    "       c.name AS ColumnName, "
                    "       CAST(ep.value AS NVARCHAR(MAX)) AS Note "
                    "FROM sys.extended_properties AS ep "
                    "JOIN sys.tables AS t ON t.object_id = ep.major_id "
                    "JOIN sys.columns AS c "
                    "  ON c.object_id = ep.major_id AND c.column_id = ep.minor_id "
                    f"WHERE ep.class = 1 AND ep.minor_id > 0 AND ep.name = N'MS_Description' "
                    f"  AND ({where_parts}) "
                    "ORDER BY TableSchema, TableName, ColumnName",
                    params,
                )
                column_rows = cursor.fetchall()

            parts = []
            if db_note:
                parts.append(db_note)
            for r in table_rows:
                parts.append(f"[{r.TableSchema}].[{r.TableName}]\n{r.Note}")
            for r in column_rows:
                parts.append(f"[{r.TableSchema}].[{r.TableName}].[{r.ColumnName}]\n{r.Note}")

            self._agent_notes_cache = "\n\n".join(parts)
            return self._agent_notes_cache
        finally:
            cursor.close()

    def get_table_schema(self, tables: list[str]) -> str:
        """
        Return live column definitions from INFORMATION_SCHEMA for the given tables.

        Each entry in *tables* must be in 'Schema.Table' or '[Schema].[Table]' format.
        Invalid or unrecognised table names are silently skipped.

        Returns a compact text block per table:
            [Schema].[Table]
              ColumnName  data_type[(len)]  NULL|NOT NULL
        """
        _valid = re.compile(r"^[A-Za-z0-9_]+$")
        pairs: list[tuple[str, str]] = []
        for raw in tables:
            clean = raw.replace("[", "").replace("]", "").strip()
            parts = clean.split(".", 1)
            if len(parts) != 2:
                continue
            schema, table = parts[0].strip(), parts[1].strip()
            if not (_valid.match(schema) and _valid.match(table)):
                continue
            pairs.append((schema, table))

        if not pairs:
            return ""

        where_clauses = " OR ".join(
            "(TABLE_SCHEMA = ? AND TABLE_NAME = ?)" for _ in pairs
        )
        params = [v for pair in pairs for v in pair]

        sql = (
            "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, "
            "       CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE {where_clauses} "
            "ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"
        )

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)

            lines: list[str] = []
            current_table: str | None = None
            for row in cursor.fetchall():
                full_name = f"[{row.TABLE_SCHEMA}].[{row.TABLE_NAME}]"
                if full_name != current_table:
                    current_table = full_name
                    lines.append(full_name)
                max_len = (
                    f"({row.CHARACTER_MAXIMUM_LENGTH})"
                    if row.CHARACTER_MAXIMUM_LENGTH
                    else ""
                )
                nullable = "NULL" if row.IS_NULLABLE == "YES" else "NOT NULL"
                lines.append(f"  {row.COLUMN_NAME}  {row.DATA_TYPE}{max_len}  {nullable}")

            return "\n".join(lines)
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    def execute_query(
        self, tsql: str
    ) -> tuple[list[str], list[tuple]]:
        """
        Execute *tsql* and return (column_names, rows).

        Raises:
            ValueError:  The query is not a read-only SELECT / WITH / sp_help.
            pyodbc.Error: Database error during execution.
        """
        self._assert_readonly(tsql)

        conn   = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(tsql)

            columns: list[str] = (
                [desc[0] for desc in cursor.description]
                if cursor.description
                else []
            )
            rows = cursor.fetchmany(MAX_SQL_ROWS)
            return columns, list(rows)
        finally:
            try:
                cursor.cancel()
            except Exception:
                pass
            cursor.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_readonly(tsql: str) -> None:
        """Raise ValueError if the statement is not a permitted read-only type."""
        if not _ALLOWED_STMT_PATTERN.match(tsql):
            raise ValueError(
                "Only SELECT / WITH / sp_help queries are permitted. "
                "The generated query was rejected for safety."
            )
