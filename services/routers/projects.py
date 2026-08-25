from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import Project, ProjectStatus, Document, DocumentType, User
from services.middleware.rbac_middleware import get_current_user, require_permission

router = APIRouter()

MAX_FILE_SIZE = 100 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".wps", ".md"}


@router.get("/")
async def list_projects(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc())
    )
    projects = result.scalars().all()
    return {"projects": [
        {
            "id": str(p.id),
            "name": p.name,
            "status": p.status.value if isinstance(p.status, ProjectStatus) else p.status,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in projects
    ]}


@router.post("/")
async def create_project(
    name: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project.create")),
    tender_file: UploadFile | None = File(None),
):
    project = Project(name=name, status=ProjectStatus.CREATED.value, user_id=current_user.id)
    db.add(project)
    await db.flush()

    if tender_file:
        file_ext = Path(tender_file.filename).suffix.lower() if tender_file.filename else ""
        if file_ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件格式: {file_ext}")
        upload_dir = Path(f"./projects/{project.id}")
        upload_dir.mkdir(parents=True, exist_ok=True)
        file_path = upload_dir / tender_file.filename
        content = await tender_file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制({MAX_FILE_SIZE // 1024 // 1024}MB)")
        with open(file_path, "wb") as f:
            f.write(content)

        doc = Document(
            project_id=project.id,
            type=DocumentType.TENDER.value,
            file_path=str(file_path),
            original_name=tender_file.filename,
            file_size=len(content),
        )
        db.add(doc)
        await db.flush()
        project.tender_doc_id = doc.id

    await db.flush()
    return {
        "project_id": str(project.id),
        "name": project.name,
        "status": project.status if isinstance(project.status, str) else project.status.value,
    }


@router.get("/{project_id}")
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return {
        "id": str(project.id),
        "name": project.name,
        "status": project.status.value if isinstance(project.status, ProjectStatus) else project.status,
        "config": project.config,
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


@router.patch("/{project_id}/status")
async def update_project_status(
    project_id: str,
    status: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_permission("project.update")),
):
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if project.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无权修改该项目")
    try:
        project.status = ProjectStatus(status).value
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效状态: {status}")
    await db.flush()
    return {"project_id": str(project.id), "status": project.status}


@router.post("/{project_id}/gate/{stage}")
async def confirm_gate(
    project_id: str,
    stage: str,
    reviewer: str = "user",
    current_user: User = Depends(get_current_user),
):
    from core.agent_engine.gate_keeper import GateKeeper
    gk = GateKeeper()
    gk.mark_passed(project_id, stage, reviewer)
    return {"project_id": project_id, "stage": stage, "gate_passed": True}


@router.get("/{project_id}/gate")
async def list_gates(
    project_id: str,
    current_user: User = Depends(get_current_user),
):
    from core.agent_engine.gate_keeper import GateKeeper
    gk = GateKeeper()
    passed = gk.list_passed_stages(project_id)
    return {"project_id": project_id, "passed_stages": passed}
