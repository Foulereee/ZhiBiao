from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from services.database import get_db
from services.models import Project, ProjectStatus, Document, DocumentType, User, iso_utc
from services.middleware.rbac_middleware import get_current_user, require_permission
from services.middleware.api_key import require_any_auth

router = APIRouter()

MAX_FILE_SIZE = 100 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".wps", ".md"}


def _safe_upload_name(filename: str | None) -> str:
    """清洗上传文件名: 只取基名、过滤非法字符, 防 `../` 路径穿越。

    与 format_doc.py 的 _save_upload 保持一致(中文属 isalnum, 不会被过滤)。
    """
    base = Path((filename or "").replace("\\", "/")).name
    safe = "".join(c for c in base if c.isalnum() or c in ("-", "_", "."))
    if safe in ("", ".", ".."):
        return "upload"
    return safe


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
            "created_at": iso_utc(p.created_at),
        }
        for p in projects
    ]}


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除项目及其全部关联数据(工作台「删除项目」按钮用)。

    projects 有 5 张子表且外键都是 NO ACTION(无级联),还存在两处循环引用,
    所以必须按依赖顺序删(已用事务空跑在真机上验证过):
      chapters.outline_id -> outlines            => chapters 必须先于 outlines
      projects.tender_doc_id -> documents 且
      documents.project_id -> projects            => 先置空 tender_doc_id,
                                                     再删 documents,最后删 projects
    整个过程放在一个事务里,任一步失败整体回滚,不会删一半。
    """
    import shutil
    from pathlib import Path as _Path

    from sqlalchemy import delete as sa_delete, update as sa_update

    from services.models import Analysis, Chapter, CheckReport, HotspotItem, Outline

    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在或无权删除")
    project_name = project.name

    try:
        await db.execute(sa_delete(CheckReport).where(CheckReport.project_id == project_id))
        await db.execute(sa_delete(Chapter).where(Chapter.project_id == project_id))
        await db.execute(sa_delete(Outline).where(Outline.project_id == project_id))
        await db.execute(sa_delete(Analysis).where(Analysis.project_id == project_id))
        await db.execute(
            sa_update(Project).where(Project.id == project_id).values(tender_doc_id=None)
        )
        await db.execute(sa_delete(Document).where(Document.project_id == project_id))
        await db.execute(
            sa_update(HotspotItem)
            .where(HotspotItem.converted_project_id == project_id)
            .values(converted_project_id="", project_code="")
        )
        await db.execute(sa_delete(Project).where(Project.id == project_id))
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败,已整体回滚:{exc}") from exc

    # 清理磁盘上的项目文件(章节内容/导出文件);失败不影响数据库删除结果
    removed_dirs = []
    for base in ("projects", "uploads"):
        target = _Path(base) / project_id
        if target.exists():
            try:
                shutil.rmtree(target, ignore_errors=True)
                removed_dirs.append(str(target))
            except OSError:
                pass

    return {
        "success": True,
        "deleted_project_id": project_id,
        "name": project_name,
        "removed_dirs": removed_dirs,
    }


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
        # 只取清洗后的基名, 防止 `../` 或绝对路径把文件写到项目目录之外
        safe_name = _safe_upload_name(tender_file.filename)
        file_path = upload_dir / safe_name
        # 同名文件已存在时加随机前缀, 避免覆盖
        if file_path.exists():
            file_path = upload_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"
        # 先按 Content-Length 拦一道：否则 100MB 文件会先被完整读进内存才报错
        if tender_file.size and tender_file.size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件大小超过限制({MAX_FILE_SIZE // 1024 // 1024}MB)")
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


@router.get("/{project_id}/export/word")
async def export_project_word(
    project_id: str,
    fmt: str = "docx",
    apply_format: bool = False,
    db: AsyncSession = Depends(get_db),
    _principal=Depends(require_any_auth),
):
    """导出项目标书为 Word(.docx) / PDF。

    浏览器端「下载Word」按钮请求的正是这个地址(原先该路由不存在,
    直接返回 {"detail":"Not Found"})。这里复用正文生成模块的导出实现,
    避免两处各写一份 docx 拼装逻辑。
    """
    from services.routers.generate import export_docx

    # 归属校验：与 get_project 一致 —— 登录用户只能导出自己的项目（admin 例外）。
    # 之前这个端点只校验"登录了没"，任何登录用户拿到 project_id 就能下载别人的整份标书。
    # API Key（桌面端）主体没有 user，按其已有权限放行。
    _user = getattr(_principal, "user", None)
    if _user is not None:
        _row = await db.execute(select(Project).where(Project.id == project_id))
        _proj = _row.scalar_one_or_none()
        if not _proj:
            raise HTTPException(status_code=404, detail="项目不存在")
        if _proj.user_id != _user.id and _user.role != "admin":
            raise HTTPException(status_code=403, detail="无权导出该项目")

    return await export_docx(
        project_id=project_id,
        fmt="pdf" if fmt.lower() == "pdf" else "docx",
        template="default",
        apply_format=apply_format,
        # 直接调用时 FastAPI 不会解析 export_docx 的 Query 默认值,必须显式传
        # 目录默认生成:投标文件没有目录不合规范,前端「下载Word」也按有目录走
        toc=True,
        toc_levels=3,
        db=db,
    )


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
        "created_at": iso_utc(project.created_at),
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


@router.delete("/{project_id}/gate/{stage}")
async def reset_gate(
    project_id: str,
    stage: str,
    current_user: User = Depends(get_current_user),
):
    from core.agent_engine.gate_keeper import GateKeeper
    gk = GateKeeper()
    gk.reset(project_id, stage)
    return {"project_id": project_id, "stage": stage, "gate_passed": False}


@router.get("/{project_id}/gate")
async def list_gates(
    project_id: str,
    current_user: User = Depends(get_current_user),
):
    from core.agent_engine.gate_keeper import GateKeeper
    gk = GateKeeper()
    passed_stages = gk.list_passed_stages(project_id)

    gate_definitions = [
        {
            "stage": "outline",
            "label": "大纲审核",
            "items": ["大纲结构完整性", "评分项覆盖对齐", "章节层级合理性"],
        },
        {
            "stage": "generate",
            "label": "正文审核",
            "items": ["内容完整性", "一致性检查", "评分点响应"],
        },
        {
            "stage": "check",
            "label": "合规审核",
            "items": ["废标项检查", "强制性要求响应", "资质证书核查"],
        },
        {
            "stage": "format",
            "label": "格式审核",
            "items": ["排版规范性", "页码连续性", "目录生成"],
        },
    ]

    gates = []
    for gate_def in gate_definitions:
        stage = gate_def["stage"]
        is_passed = stage in passed_stages
        gate_info = gk.get_gate_info(project_id, stage)
        gates.append({
            "stage": stage,
            "label": gate_def["label"],
            "status": "confirmed" if is_passed else "pending",
            "items": gate_def["items"],
            "reviewer": gate_info.get("reviewer", "") if gate_info else "",
            "timestamp": gate_info.get("timestamp", "") if gate_info else "",
        })

    return {"project_id": project_id, "gates": gates}
