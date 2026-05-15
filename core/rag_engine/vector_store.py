from __future__ import annotations

from typing import List

import chromadb


class VectorStore:
    def __init__(self, persist_dir: str = "./chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_dir)

    def get_or_create_collection(self, name: str) -> chromadb.Collection:
        return self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    async def add_documents(
        self,
        collection_name: str,
        ids: List[str],
        texts: List[str],
        embeddings: List[List[float]],
        metadatas: List[dict] | None = None,
    ):
        collection = self.get_or_create_collection(collection_name)
        collection.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    async def query(
        self,
        collection_name: str,
        query_embedding: List[float],
        top_k: int = 10,
        where: dict | None = None,
    ) -> dict:
        collection = self.get_or_create_collection(collection_name)
        kwargs: dict = {"query_embeddings": [query_embedding], "n_results": top_k}
        if where:
            kwargs["where"] = where
        return collection.query(**kwargs)

    async def delete_collection(self, name: str):
        try:
            self.client.delete_collection(name)
        except Exception:
            pass

    def list_collections(self) -> list[str]:
        return [c.name for c in self.client.list_collections()]
