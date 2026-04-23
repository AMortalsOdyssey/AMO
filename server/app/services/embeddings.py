import asyncio
import logging
import time

import httpx

from app.core.config import settings

log = logging.getLogger("amo.embeddings")

_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)
_vertex_token: str | None = None
_vertex_token_expires_at = 0.0
_vertex_token_lock = asyncio.Lock()


def _fallback_vector() -> list[float]:
    dim = max(settings.embedding_output_dim, 1)
    return [0.0] * dim


async def get_embedding_vector(text: str, task_type: str = "RETRIEVAL_QUERY") -> list[float]:
    provider = settings.embedding_provider.strip().lower()

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if provider == "vertex_ai":
                return await _get_vertex_embedding(client, text, task_type)
            return await _get_openai_compatible_embedding(client, text)
    except Exception:
        log.warning(
            "embedding generation failed, using zero-vector fallback",
            extra={
                "provider": provider,
                "model": settings.embedding_model,
                "task_type": task_type,
                "text_len": len(text),
                "fallback_dim": settings.embedding_output_dim,
            },
            exc_info=True,
        )
        return _fallback_vector()


async def _get_openai_compatible_embedding(client: httpx.AsyncClient, text: str) -> list[float]:
    api_key = settings.embedding_api_key or settings.llm_api_key
    url = f"{settings.embedding_base_url.rstrip('/')}/embeddings"
    resp = await client.post(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": settings.embedding_model, "input": text},
    )
    resp.raise_for_status()
    data = resp.json()
    return data["data"][0]["embedding"]


async def _get_vertex_embedding(
    client: httpx.AsyncClient,
    text: str,
    task_type: str,
) -> list[float]:
    if not settings.vertex_ai_project:
        raise RuntimeError("VERTEX_AI_PROJECT is required when EMBEDDING_PROVIDER=vertex_ai")

    token = await _get_vertex_access_token(client)
    location = settings.vertex_ai_location
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/"
        f"{settings.vertex_ai_project}/locations/{location}/publishers/google/models/"
        f"{settings.embedding_model}:predict"
    )
    resp = await client.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "instances": [{"content": text, "task_type": task_type}],
            "parameters": {
                "autoTruncate": True,
                "outputDimensionality": settings.embedding_output_dim,
            },
        },
    )
    resp.raise_for_status()
    data = resp.json()
    return data["predictions"][0]["embeddings"]["values"]


async def _get_vertex_access_token(client: httpx.AsyncClient) -> str:
    global _vertex_token, _vertex_token_expires_at

    now = time.time()
    if _vertex_token and now < _vertex_token_expires_at:
        return _vertex_token

    async with _vertex_token_lock:
        now = time.time()
        if _vertex_token and now < _vertex_token_expires_at:
            return _vertex_token

        resp = await client.get(
            _METADATA_TOKEN_URL,
            headers={"Metadata-Flavor": "Google"},
        )
        resp.raise_for_status()
        data = resp.json()
        expires_in = int(data.get("expires_in", 300))
        _vertex_token = data["access_token"]
        _vertex_token_expires_at = time.time() + max(expires_in - 60, 60)
        return _vertex_token
