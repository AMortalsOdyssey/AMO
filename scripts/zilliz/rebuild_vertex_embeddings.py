#!/usr/bin/env python3

import argparse
import asyncio
import json
import subprocess
import sys
import time
from dataclasses import dataclass

import httpx
from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

PRICE_PER_1M_TOKENS = 0.15
DEFAULT_TARGETS = {
    "event_embeddings": "event_embeddings_vtx3072",
    "persona_embeddings": "persona_embeddings_vtx3072",
    "technique_embeddings": "technique_embeddings_vtx3072",
    "text_chunks": "text_chunks_vtx3072",
}


@dataclass
class CollectionStats:
    rows: int = 0
    chars: int = 0
    max_len: int = 0

    @property
    def estimated_cost_usd(self) -> float:
        return (self.chars / 1_000_000) * PRICE_PER_1M_TOKENS


class VertexEmbedder:
    def __init__(self, project: str, location: str, model: str, output_dim: int, concurrency: int):
        self.project = project
        self.location = location
        self.model = model
        self.output_dim = output_dim
        self._token = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(concurrency)
        self._client = httpx.AsyncClient(timeout=120)

    async def close(self):
        await self._client.aclose()

    async def embed_batch(
        self,
        texts: list[str],
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> list[tuple[list[float], int]]:
        async with self._sem:
            url = (
                f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project}/"
                f"locations/{self.location}/publishers/google/models/{self.model}:predict"
            )
            payload = {
                "instances": [{"content": text, "task_type": task_type} for text in texts],
                "parameters": {
                    "autoTruncate": True,
                    "outputDimensionality": self.output_dim,
                },
            }

            for attempt in range(6):
                try:
                    token = await self._get_access_token()
                    resp = await self._client.post(
                        url,
                        headers={"Authorization": f"Bearer {token}"},
                        json=payload,
                    )
                    if resp.status_code != 429:
                        resp.raise_for_status()
                        data = resp.json()
                        results = []
                        for prediction in data["predictions"]:
                            embedding = prediction["embeddings"]["values"]
                            token_count = int(prediction["embeddings"]["statistics"].get("token_count", 0))
                            results.append((embedding, token_count))
                        return results

                    retry_after = resp.headers.get("retry-after")
                    if retry_after:
                        wait_seconds = float(retry_after)
                    else:
                        wait_seconds = min(2 ** attempt, 30)
                    await asyncio.sleep(wait_seconds)
                except (httpx.TimeoutException, httpx.TransportError):
                    wait_seconds = min(2 ** attempt, 30)
                    await asyncio.sleep(wait_seconds)

            raise RuntimeError("unreachable")

    async def _get_access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_expires_at:
            return self._token

        async with self._token_lock:
            now = time.time()
            if self._token and now < self._token_expires_at:
                return self._token

            proc = await asyncio.create_subprocess_exec(
                "gcloud",
                "auth",
                "print-access-token",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"failed to fetch access token: {stderr.decode().strip()}")
            self._token = stdout.decode().strip()
            self._token_expires_at = time.time() + 3000
            return self._token


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild Zilliz collections with Vertex AI embeddings")
    parser.add_argument("--zilliz-uri", required=True)
    parser.add_argument("--zilliz-token", required=True)
    parser.add_argument("--zilliz-db", default="ai_social_memory")
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--model", default="gemini-embedding-001")
    parser.add_argument("--output-dim", type=int, default=3072)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--drop-target-if-exists", action="store_true")
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def clone_schema(source: Collection, target_name: str, output_dim: int) -> Collection:
    description = source.schema.description.replace("4096", str(output_dim))
    fields = []
    for field in source.schema.fields:
        kwargs = {"description": field.description}
        if field.dtype == DataType.VARCHAR:
            kwargs["max_length"] = int(field.params["max_length"])
        if getattr(field, "is_primary", False):
            kwargs["is_primary"] = True
        if getattr(field, "auto_id", False):
            kwargs["auto_id"] = True
        if field.dtype == DataType.FLOAT_VECTOR:
            kwargs["dim"] = output_dim
        fields.append(FieldSchema(name=field.name, dtype=field.dtype, **kwargs))

    schema = CollectionSchema(
        fields=fields,
        description=description,
        enable_dynamic_field=source.schema.enable_dynamic_field,
    )
    target = Collection(name=target_name, schema=schema)
    for index in source.indexes:
        if index.field_name != "embedding":
            continue
        target.create_index(field_name=index.field_name, index_params=index.params)
    target.load()
    return target


def iter_rows(collection: Collection, batch_size: int):
    fields = [field.name for field in collection.schema.fields if field.name != "embedding"]
    iterator = collection.query_iterator(
        batch_size=batch_size,
        expr='id != ""',
        output_fields=fields,
    )
    try:
        while True:
            batch = iterator.next()
            if not batch:
                break
            yield batch
    finally:
        iterator.close()


def analyze_collection(collection: Collection, batch_size: int) -> CollectionStats:
    stats = CollectionStats()
    for batch in iter_rows(collection, batch_size):
        stats.rows += len(batch)
        for row in batch:
            content = row.get("content") or ""
            stats.chars += len(content)
            stats.max_len = max(stats.max_len, len(content))
    return stats


async def rebuild_collection(
    source_name: str,
    target_name: str,
    batch_size: int,
    embedder: VertexEmbedder,
    drop_target_if_exists: bool,
) -> dict:
    source = Collection(source_name)
    source.load()

    existing_ids: set[str] = set()
    if utility.has_collection(target_name):
        if drop_target_if_exists:
            utility.drop_collection(target_name)
            target = clone_schema(source, target_name, embedder.output_dim)
        else:
            target = Collection(target_name)
            target.load()
            id_iterator = target.query_iterator(
                batch_size=batch_size,
                expr='id != ""',
                output_fields=["id"],
            )
            try:
                while True:
                    batch = id_iterator.next()
                    if not batch:
                        break
                    existing_ids.update(row["id"] for row in batch)
            finally:
                id_iterator.close()
    else:
        target = clone_schema(source, target_name, embedder.output_dim)

    inserted = len(existing_ids)
    token_total = 0
    for batch in iter_rows(source, batch_size):
        batch = [row for row in batch if row["id"] not in existing_ids]
        if not batch:
            continue

        texts = [row.get("content") or "" for row in batch]
        embeddings = await embedder.embed_batch(texts)
        enriched = []
        for row, (embedding, token_count) in zip(batch, embeddings, strict=True):
            row = dict(row)
            row["embedding"] = embedding
            row["_token_count"] = token_count
            enriched.append(row)

        token_total += sum(row.pop("_token_count", 0) for row in enriched)
        target.insert(enriched)
        inserted += len(enriched)
        existing_ids.update(row["id"] for row in enriched)
        print(
            json.dumps(
                {
                    "collection": source_name,
                    "target": target_name,
                    "inserted": inserted,
                    "token_total": token_total,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    target.flush()
    return {
        "source": source_name,
        "target": target_name,
        "inserted": inserted,
        "token_total": token_total,
        "actual_cost_usd": round((token_total / 1_000_000) * PRICE_PER_1M_TOKENS, 6),
    }


async def main():
    args = parse_args()
    connections.connect(
        alias="default",
        uri=args.zilliz_uri,
        token=args.zilliz_token,
        db_name=args.zilliz_db,
    )

    stats = {}
    for source_name, target_name in DEFAULT_TARGETS.items():
        source = Collection(source_name)
        source.load()
        collection_stats = analyze_collection(source, args.batch_size)
        stats[source_name] = {
            "target": target_name,
            "rows": collection_stats.rows,
            "chars": collection_stats.chars,
            "avg_chars": round(collection_stats.chars / collection_stats.rows, 2)
            if collection_stats.rows
            else 0,
            "max_chars": collection_stats.max_len,
            "estimated_cost_usd": round(collection_stats.estimated_cost_usd, 6),
        }

    print(json.dumps({"mode": "analysis", "collections": stats}, ensure_ascii=False, indent=2))
    if not args.execute:
        return

    embedder = VertexEmbedder(
        project=args.project,
        location=args.location,
        model=args.model,
        output_dim=args.output_dim,
        concurrency=args.concurrency,
    )
    try:
        results = []
        for source_name, target_name in DEFAULT_TARGETS.items():
            result = await rebuild_collection(
                source_name=source_name,
                target_name=target_name,
                batch_size=args.batch_size,
                embedder=embedder,
                drop_target_if_exists=args.drop_target_if_exists,
            )
            results.append(result)
        print(json.dumps({"mode": "execute", "results": results}, ensure_ascii=False, indent=2))
    finally:
        await embedder.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
