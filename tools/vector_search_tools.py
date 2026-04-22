"""
Vector Search Tools
===================
Two plain functions (no LangChain tool wrappers):

  create_embedding_cast(text, llm_svc) -> str
      Calls the embedding model and returns a T-SQL CAST expression:
          CAST('<embedding_json>' AS VECTOR(<dims>))
"""

from __future__ import annotations

import json


def create_embedding_cast(text: str, llm_svc) -> str:
    """Embed *text* and return a T-SQL CAST expression for use with VECTOR_DISTANCE."""
    emb  = llm_svc.create_embedding(text)
    dims = len(emb)
    return f"CAST('{json.dumps(emb)}' AS VECTOR({dims}))"
