from __future__ import annotations

import math
import re
from collections import Counter
from typing import List

import numpy as np

from core.rag_engine.embedder import Embedder
from core.rag_engine.vector_store import VectorStore


class HybridRetriever:
    def __init__(self, vector_store: VectorStore, embedder: Embedder):
        self.vector_store = vector_store
        self.embedder = embedder
        self._documents: list[str] = []
        self._doc_metadatas: list[dict] = []
        self._tfidf_matrix: np.ndarray | None = None
        self._idf: np.ndarray | None = None
        self._vocab: dict[str, int] = {}

    async def retrieve(
        self,
        query: str,
        collection_name: str,
        top_k: int = 5,
    ) -> list[dict]:
        vector_results = await self._vector_search(query, collection_name, top_k)
        keyword_results = self._bm25_search(query, top_k)
        fused = self._rrf_fusion(vector_results, keyword_results, k=60)
        return fused[:top_k]

    async def _vector_search(
        self,
        query: str,
        collection_name: str,
        top_k: int,
    ) -> list[dict]:
        query_embeddings = await self.embedder.embed([query])
        if not query_embeddings:
            return []

        results = await self.vector_store.query(
            collection_name=collection_name,
            query_embedding=query_embeddings[0],
            top_k=top_k * 3,
        )

        if not results.get("documents") or not results["documents"][0]:
            return []

        scored = []
        for i, doc in enumerate(results["documents"][0]):
            dist = results["distances"][0][i] if results.get("distances") else 0
            metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
            similarity = max(0.0, 1 - dist) if dist is not None else 0.0
            scored.append({
                "text": doc,
                "score": similarity,
                "metadata": metadata,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def _tokenize(self, text: str) -> list[str]:
        tokens: list[str] = []
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                tokens.append(char)
            else:
                for word in re.findall(r"[a-zA-Z0-9]+", char):
                    tokens.append(word.lower())
        return tokens

    def _build_tfidf(self, docs: list[str]) -> None:
        if not docs:
            self._tfidf_matrix = None
            self._idf = None
            self._vocab = {}
            return

        tokenized_docs = [self._tokenize(doc) for doc in docs]

        vocab: dict[str, int] = {}
        for tokens in tokenized_docs:
            for t in tokens:
                if t not in vocab:
                    vocab[t] = len(vocab)
        self._vocab = vocab

        n_docs = len(docs)
        n_terms = len(vocab)

        if n_terms == 0:
            self._tfidf_matrix = np.zeros((n_docs, 1), dtype=np.float32)
            self._idf = np.zeros(1, dtype=np.float32)
            return

        tf_matrix = np.zeros((n_docs, n_terms), dtype=np.float32)
        for i, tokens in enumerate(tokenized_docs):
            counts = Counter(tokens)
            total = len(tokens) if tokens else 1
            for token, count in counts.items():
                if token in vocab:
                    tf_matrix[i, vocab[token]] = count / total

        df = np.sum(tf_matrix > 0, axis=0)
        idf = np.log((n_docs + 1) / (df + 1)) + 1
        self._idf = idf

        self._tfidf_matrix = tf_matrix * idf

        norms = np.linalg.norm(self._tfidf_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._tfidf_matrix = self._tfidf_matrix / norms

    def _bm25_search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        if self._tfidf_matrix is None or not self._documents:
            return []

        query_tokens = self._tokenize(query)
        if not query_tokens or not self._vocab:
            return []

        n_terms = len(self._vocab)
        query_vec = np.zeros(n_terms, dtype=np.float32)
        counts = Counter(query_tokens)
        total = len(query_tokens)
        for token, count in counts.items():
            if token in self._vocab:
                query_vec[self._vocab[token]] = count / total

        if self._idf is not None:
            query_vec = query_vec * self._idf

        norm = np.linalg.norm(query_vec)
        if norm > 0:
            query_vec = query_vec / norm

        scores = self._tfidf_matrix @ query_vec

        top_indices = np.argsort(scores)[::-1][:top_k]

        results: list[tuple[str, float]] = []
        for idx in top_indices:
            if scores[idx] > 0:
                results.append((self._documents[idx], float(scores[idx])))
        return results

    def _rrf_fusion(
        self,
        vector_results: list[dict],
        keyword_results: list[tuple[str, float]],
        k: int = 60,
    ) -> list[dict]:
        rrf_scores: dict[str, float] = {}
        text_meta: dict[str, dict] = {}

        for rank, item in enumerate(vector_results):
            text = item["text"]
            rrf_scores[text] = rrf_scores.get(text, 0.0) + 1.0 / (k + rank + 1)
            if text not in text_meta:
                text_meta[text] = item.get("metadata", {})

        for rank, (text, _score) in enumerate(keyword_results):
            rrf_scores[text] = rrf_scores.get(text, 0.0) + 1.0 / (k + rank + 1)
            if text not in text_meta:
                text_meta[text] = {}

        fused = [
            {"text": text, "score": score, "metadata": text_meta.get(text, {})}
            for text, score in rrf_scores.items()
        ]
        fused.sort(key=lambda x: x["score"], reverse=True)
        return fused

    async def add_documents(
        self,
        collection_name: str,
        texts: List[str],
        metadatas: List[dict] | None = None,
    ):
        if not texts:
            return

        self._documents.extend(texts)
        if metadatas:
            self._doc_metadatas.extend(metadatas)
        else:
            self._doc_metadatas.extend([{}] * len(texts))

        self._build_tfidf(self._documents)

        embeddings = await self.embedder.embed(texts)
        ids = [f"doc_{i}" for i in range(len(texts))]
        await self.vector_store.add_documents(
            collection_name=collection_name,
            ids=ids,
            texts=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
