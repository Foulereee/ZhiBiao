from __future__ import annotations

import asyncio
from typing import List


class Embedder:
    def __init__(self, config: dict):
        self.mode = config.get("mode", "api")
        self.model_name = config.get("model_name", "text-embedding-v3")
        self.api_key = config.get("api_key", "")
        self.api_base = config.get("api_base", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        self._local_model = None

    async def embed(self, texts: List[str]) -> List[List[float]]:
        if self.mode == "local":
            return await self._local_embed(texts)
        return await self._api_embed(texts)

    async def _local_embed(self, texts: List[str]) -> List[List[float]]:
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer("BAAI/bge-m3")
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None, lambda: self._local_model.encode(texts, normalize_embeddings=True)
        )
        return embeddings.tolist()

    async def _api_embed(self, texts: List[str]) -> List[List[float]]:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.api_base)
        response = await client.embeddings.create(model=self.model_name, input=texts)
        return [item.embedding for item in response.data]
