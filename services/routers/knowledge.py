from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import KnowledgeBase as KnowledgeBaseModel
from services.llm_factory import get_llm_gateway
from core.rag_engine import Embedder, VectorStore, HybridRetriever
from core.settings import get_settings
from services.middleware.api_key import require_any_auth, AuthPrincipal

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_any_auth)])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".html"}

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB

_embedder_instance: Embedder | None = None
_vector_store_instance: VectorStore | None = None


def _get_embedder() -> Embedder:
    global _embedder_instance
    if _embedder_instance is None:
        settings = get_settings()
        _embedder_instance = Embedder({
            "mode": settings.embedding_mode,
            "model": settings.embedding_model,
            "api_key": settings.embedding_api_key,
            "api_base": settings.embedding_api_base,
        })
    return _embedder_instance


def _get_vector_store() -> VectorStore:
    global _vector_store_instance
    if _vector_store_instance is None:
        settings = get_settings()
        _vector_store_instance = VectorStore(persist_dir=settings.chroma_dir)
    return _vector_store_instance


def _get_retriever() -> HybridRetriever:
    return HybridRetriever(vector_store=_get_vector_store(), embedder=_get_embedder())


class KnowledgeBaseCreate(BaseModel):
    name: str
    embedding_model: str = "text-embedding-v3"


def _smart_chunk(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    if not text.strip():
        return []

    sentence_endings = re.compile(r"(?<=[。！？.!?])")

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current_chunk = ""
    overlap_text = ""

    for para in paragraphs:
        if len(para) > chunk_size:
            if current_chunk:
                chunks.append(current_chunk)
                overlap_text = current_chunk[-overlap:] if len(current_chunk) >= overlap else current_chunk
                current_chunk = ""

            sentences = sentence_endings.split(para)
            sentences = [s for s in sentences if s.strip()]

            sub_chunk = overlap_text
            for sent in sentences:
                if len(sub_chunk) + len(sent) > chunk_size and len(sub_chunk) > len(overlap_text):
                    chunks.append(sub_chunk)
                    overlap_text = sub_chunk[-overlap:] if len(sub_chunk) >= overlap else sub_chunk
                    sub_chunk = overlap_text
                sub_chunk += sent

            if sub_chunk.strip():
                current_chunk = sub_chunk
                overlap_text = ""
        else:
            candidate = (current_chunk + "\n\n" + para).strip() if current_chunk else para
            if len(candidate) > chunk_size and current_chunk:
                chunks.append(current_chunk)
                overlap_text = current_chunk[-overlap:] if len(current_chunk) >= overlap else current_chunk
                current_chunk = overlap_text + "\n\n" + para if overlap_text else para
            else:
                current_chunk = candidate

    if current_chunk.strip():
        chunks.append(current_chunk)

    return [c for c in chunks if c.strip()]


@router.get("/")
async def list_knowledge_bases(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KnowledgeBaseModel).order_by(KnowledgeBaseModel.created_at.desc()))
    kbs = result.scalars().all()
    return {"knowledge_bases": [
        {
            "id": str(kb.id),
            "name": kb.name,
            "doc_count": kb.doc_count,
            "embedding_model": kb.embedding_model,
            "collection_name": kb.collection_name,
            "created_at": kb.created_at.isoformat() if kb.created_at else None,
        }
        for kb in kbs
    ]}


@router.post("/")
async def create_knowledge_base(kb: KnowledgeBaseCreate, db: AsyncSession = Depends(get_db)):
    collection_name = f"kb_{uuid.uuid4().hex[:12]}"
    new_kb = KnowledgeBaseModel(
        name=kb.name,
        embedding_model=kb.embedding_model,
        collection_name=collection_name,
    )
    db.add(new_kb)
    await db.flush()

    vs = _get_vector_store()
    vs.get_or_create_collection(collection_name)

    return {
        "id": str(new_kb.id),
        "name": new_kb.name,
        "collection_name": collection_name,
    }


@router.delete("/{kb_id}")
async def delete_knowledge_base(kb_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(KnowledgeBaseModel).where(KnowledgeBaseModel.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if kb.collection_name:
        vs = _get_vector_store()
        await vs.delete_collection(kb.collection_name)

    await db.delete(kb)
    await db.flush()
    return {"success": True}


@router.post("/{kb_id}/upload")
async def upload_documents(
    kb_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    from pathlib import Path
    import tempfile

    file_ext = Path(file.filename).suffix.lower() if file.filename else ""
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_ext}，仅支持: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    result = await db.execute(
        select(KnowledgeBaseModel).where(KnowledgeBaseModel.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限",
        )
    text = content.decode("utf-8", errors="ignore")

    parse_error = None
    with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        from core.doc_engine import get_parser
        parser = get_parser(file_ext)
        parsed = parser.parse(tmp_path)
        text = parsed.text
    except Exception as e:
        parse_error = str(e)
        logger.error(f"文档解析失败 [{file.filename}]: {e}", exc_info=True)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not text.strip():
        detail = "文档内容为空"
        if parse_error:
            detail += f"（解析错误: {parse_error}）"
        raise HTTPException(status_code=400, detail=detail)

    chunks = _smart_chunk(text, chunk_size=1000, overlap=200)
    if not chunks:
        raise HTTPException(status_code=400, detail="文档分块后无有效内容")

    chunk_ids = [f"{uuid.uuid4().hex}" for _ in chunks]
    chunk_metadatas = [{"source": file.filename, "kb_id": kb_id} for _ in chunks]

    try:
        retriever = _get_retriever()
        await retriever.add_documents(
            collection_name=kb.collection_name,
            texts=chunks,
            metadatas=chunk_metadatas,
        )
    except Exception as e:
        logger.error(f"向量入库失败 [{file.filename}]: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"向量入库失败: {e}")

    kb.doc_count += len(chunks)
    await db.flush()

    response = {
        "success": True,
        "chunks_added": len(chunks),
        "total_docs": kb.doc_count,
    }
    if parse_error:
        response["warnings"] = [f"文档解析部分失败: {parse_error}，已使用原始文本"]
    return response


@router.post("/{kb_id}/search")
async def search_knowledge_base(
    kb_id: str,
    query: str,
    top_k: int = 5,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeBaseModel).where(KnowledgeBaseModel.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    retriever = _get_retriever()

    results = await retriever.retrieve(
        query=query,
        collection_name=kb.collection_name,
        top_k=top_k,
    )

    return {"results": results}


# ─── 云端知识库同步（VIP） ───


class SyncPushItem(BaseModel):
    text: str
    metadata: dict[str, Any] = {}


class SyncPushRequest(BaseModel):
    items: list[SyncPushItem]
    replace_all: bool = False


@router.post("/{kb_id}/sync-push")
async def sync_push(
    kb_id: str,
    payload: SyncPushRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(require_any_auth),
):
    """桌面端 → 云端：批量推送本地 KB 的 chunks 到云端 KB"""
    result = await db.execute(
        select(KnowledgeBaseModel).where(KnowledgeBaseModel.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if not payload.items:
        return {"success": True, "pushed": 0, "total": kb.doc_count}

    vs = _get_vector_store()
    embedder = _get_embedder()

    if payload.replace_all:
        try:
            await vs.delete_collection(kb.collection_name)
        except Exception:
            pass
        kb.doc_count = 0

    collection = vs.get_or_create_collection(kb.collection_name)
    texts = [item.text for item in payload.items if item.text and item.text.strip()]
    if not texts:
        return {"success": True, "pushed": 0, "total": kb.doc_count}

    embeddings = await embedder.embed(texts)
    if not embeddings or len(embeddings) != len(texts):
        raise HTTPException(status_code=500, detail="Embedding 生成失败")

    sync_tag = principal.identifier if principal else "anonymous"
    metadatas = []
    ids = []
    for i, item in enumerate(payload.items):
        if not item.text or not item.text.strip():
            continue
        meta = dict(item.metadata or {})
        meta.setdefault("source", "desktop_sync")
        meta.setdefault("synced_by", sync_tag)
        meta.setdefault("synced_at", uuid.uuid4().hex)
        metadatas.append(meta)
        ids.append(f"sync_{uuid.uuid4().hex}")

    try:
        collection.add(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )
    except Exception as e:
        logger.error(f"云端同步入库失败 [kb={kb_id}]: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"同步入库失败: {e}")

    kb.doc_count += len(texts)
    await db.flush()

    return {
        "success": True,
        "pushed": len(texts),
        "total": kb.doc_count,
        "synced_by": sync_tag,
    }


@router.get("/{kb_id}/sync-pull")
async def sync_pull(
    kb_id: str,
    limit: int = 500,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """云端 → 桌面端：拉取云端 KB 的 chunks（带分页）"""
    result = await db.execute(
        select(KnowledgeBaseModel).where(KnowledgeBaseModel.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")

    if limit <= 0 or limit > 2000:
        limit = 500
    if offset < 0:
        offset = 0

    vs = _get_vector_store()
    try:
        collection = vs.get_or_create_collection(kb.collection_name)
        fetched = collection.get(
            limit=limit,
            offset=offset,
            include=["documents", "metadatas"],
        )
    except Exception as e:
        logger.error(f"云端拉取失败 [kb={kb_id}]: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"拉取失败: {e}")

    ids = fetched.get("ids") or []
    documents = fetched.get("documents") or []
    metadatas = fetched.get("metadatas") or []

    items = []
    for i, _id in enumerate(ids):
        items.append({
            "id": _id,
            "text": documents[i] if i < len(documents) else "",
            "metadata": metadatas[i] if i < len(metadatas) else {},
        })

    return {
        "success": True,
        "items": items,
        "count": len(items),
        "offset": offset,
        "limit": limit,
        "kb_total": kb.doc_count,
    }


@router.get("/{kb_id}/meta")
async def get_kb_meta(
    kb_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取云端 KB 元信息（用于同步前比对）"""
    result = await db.execute(
        select(KnowledgeBaseModel).where(KnowledgeBaseModel.id == kb_id)
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return {
        "id": str(kb.id),
        "name": kb.name,
        "doc_count": kb.doc_count,
        "embedding_model": kb.embedding_model,
        "collection_name": kb.collection_name,
        "created_at": kb.created_at.isoformat() if kb.created_at else None,
    }
