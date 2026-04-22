"""
LLM Service
Wraps the OpenAI client (compatible with Azure OpenAI and standard OpenAI).
Provides:
  • chat()             – maintain a multi-turn conversation with the LLM.
  • create_embedding() – embed text with text-embedding-3-small for vector search.
"""

from __future__ import annotations

import os

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI, OpenAI

from config import (
    LLM_ENDPOINT,
    LLM_API_KEY,
    LLM_MODEL,
    LLM_API_VERSION,
    LLM_TENANT_ID,
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_ENDPOINT,
)

_NOT_CONFIGURED = "YOUR_LLM_ENDPOINT_HERE"


def _is_azure_endpoint(endpoint: str) -> bool:
    """Return True for Azure OpenAI-compatible endpoint hostnames."""
    endpoint_l = endpoint.lower()
    return (
        "openai.azure.com" in endpoint_l
        or "cognitiveservices.azure.com" in endpoint_l
        or "services.ai.azure.com" in endpoint_l
    )


class LLMService:
    """Thin wrapper around the OpenAI chat-completions API."""

    def __init__(self):
        if LLM_ENDPOINT == _NOT_CONFIGURED:
            raise RuntimeError(
                "LLM_ENDPOINT is not configured in config.py. "
                "Please replace the placeholder with your actual endpoint."
            )

        if LLM_TENANT_ID:
            os.environ.setdefault("AZURE_TENANT_ID", LLM_TENANT_ID)

        credential = DefaultAzureCredential() if not LLM_API_KEY else None

        def _token_provider_for(scope: str):
            return get_bearer_token_provider(credential, scope)

        def _make_azure_client(endpoint: str, scope: str) -> AzureOpenAI:
            if LLM_API_KEY:
                return AzureOpenAI(
                    azure_endpoint=endpoint,
                    api_key=LLM_API_KEY,
                    api_version=LLM_API_VERSION,
                )
            return AzureOpenAI(
                azure_endpoint=endpoint,
                azure_ad_token_provider=_token_provider_for(scope),
                api_version=LLM_API_VERSION,
            )

        _COG_SCOPE = "https://cognitiveservices.azure.com/.default"
        _AI_SCOPE  = "https://ai.azure.com/.default"

        # Chat client — standard Azure OpenAI resource uses cognitiveservices scope
        if _is_azure_endpoint(LLM_ENDPOINT):
            self._client = _make_azure_client(LLM_ENDPOINT, _COG_SCOPE)
        else:
            self._client = OpenAI(
                base_url=LLM_ENDPOINT,
                api_key=LLM_API_KEY,
            )

        self._model = LLM_MODEL

        # Embedding client — supports three cases:
        #   1. Empty EMBEDDING_ENDPOINT → reuse the chat client
        #   2. Foundry project endpoint (services.ai.azure.com) → use ai.azure.com scope
        #      but talk to the resource's openai.azure.com hostname (project acts as router)
        #   3. Plain Azure OpenAI endpoint → standard cognitiveservices scope
        emb_endpoint = EMBEDDING_ENDPOINT.strip() if EMBEDDING_ENDPOINT else ""
        if not emb_endpoint:
            self._emb_client = self._client
        elif "services.ai.azure.com" in emb_endpoint.lower():
            # Foundry project: use ai.azure.com scope against the hub's openai.azure.com
            # Extract hub name from the project URL and build the openai.azure.com URL
            # e.g. https://sqlbitsfoundry.services.ai.azure.com/... → sqlbitsfoundry.openai.azure.com
            hub = emb_endpoint.lower().split(".services.ai.azure.com")[0].split("//")[-1]
            openai_ep = f"https://{hub}.openai.azure.com"
            self._emb_client = _make_azure_client(openai_ep, _AI_SCOPE)
        elif _is_azure_endpoint(emb_endpoint):
            self._emb_client = _make_azure_client(emb_endpoint, _COG_SCOPE)
        else:
            self._emb_client = OpenAI(
                base_url=emb_endpoint,
                api_key=LLM_API_KEY,
            )

        # Running conversation history (user + assistant turns)
        self._history: list[dict[str, str]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(self, user_message: str) -> str:
        """
        Send *user_message* to the LLM in the context of the ongoing
        conversation and return the assistant's reply.
        """
        self._history.append({"role": "user", "content": user_message})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a helpful, knowledgeable assistant. "
                        "Give clear, concise answers. "
                        "Format code blocks with markdown fences."
                    ),
                },
                *self._history,
            ],
        )

        reply = response.choices[0].message.content or ""
        self._history.append({"role": "assistant", "content": reply})
        return reply

    def create_embedding(self, text: str) -> list[float]:
        """
        Embed *text* using the configured embedding model.
        Returns a list of floats representing the embedding vector.
        Uses a dedicated client when EMBEDDING_ENDPOINT differs from LLM_ENDPOINT.
        """
        kwargs: dict = {"model": EMBEDDING_MODEL, "input": text}
        # text-embedding-3-* supports custom dimensions; ada-002 and older do not
        if EMBEDDING_MODEL.startswith("text-embedding-3"):
            kwargs["dimensions"] = EMBEDDING_DIMENSIONS
        response = self._emb_client.embeddings.create(**kwargs)
        return response.data[0].embedding

    def clear_history(self) -> None:
        """Reset the conversation history."""
        self._history.clear()
