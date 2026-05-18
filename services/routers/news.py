from __future__ import annotations

from datetime import datetime, date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from services.database import get_db
from services.models import MonitoringTask, CrawlResult
from services.llm_factory import get_llm_gateway
from core.skill_engine.base import SkillContext

router = APIRouter()


class MonitorTaskCreate(BaseModel):
    name: str
    keywords: str
    exclude_keywords: str = ""
    must_contain_keywords: str = ""
    sites: list[str] = []
    interval_minutes: int = 60


@router.get("/tasks")
async def list_monitor_tasks(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MonitoringTask).order_by(MonitoringTask.created_at.desc()))
    tasks = result.scalars().all()
    return {"tasks": [
        {
            "id": str(t.id),
            "name": t.name,
            "keywords": t.keywords,
            "exclude_keywords": t.exclude_keywords,
            "must_contain_keywords": t.must_contain_keywords,
            "sites": t.sites,
            "interval_minutes": t.interval_minutes,
            "enabled": t.enabled,
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
        }
        for t in tasks
    ]}


@router.post("/tasks")
async def create_monitor_task(task: MonitorTaskCreate, db: AsyncSession = Depends(get_db)):
    new_task = MonitoringTask(
        user_id="00000000-0000-0000-0000-000000000000",
        name=task.name,
        keywords=task.keywords,
        exclude_keywords=task.exclude_keywords,
        must_contain_keywords=task.must_contain_keywords,
        sites=task.sites,
        interval_minutes=task.interval_minutes,
    )
    db.add(new_task)
    await db.flush()
    return {
        "id": str(new_task.id),
        "name": new_task.name,
        "keywords": new_task.keywords,
        "enabled": new_task.enabled,
    }


@router.patch("/tasks/{task_id}")
async def update_monitor_task(
    task_id: str,
    enabled: bool | None = None,
    name: str | None = None,
    keywords: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonitoringTask).where(MonitoringTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="监控任务不存在")

    if enabled is not None:
        task.enabled = enabled
    if name is not None:
        task.name = name
    if keywords is not None:
        task.keywords = keywords
    await db.flush()

    return {"id": str(task.id), "name": task.name, "enabled": task.enabled}


@router.delete("/tasks/{task_id}")
async def delete_monitor_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MonitoringTask).where(MonitoringTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="监控任务不存在")

    await db.delete(task)
    await db.flush()
    return {"success": True}


async def _save_crawl_results(db: AsyncSession, task_id: str, items: list[dict]):
    for item in items:
        existing = await db.execute(
            select(CrawlResult).where(CrawlResult.url == item.get("url", ""))
        )
        if existing.scalar_one_or_none():
            continue

        title = item.get("title", "")
        hot_score = item.get("keyword_score", 0) * 0.4 + item.get("relevance_score", 0) * 0.6
        is_hot = hot_score >= 0.5

        category = "general"
        hot_keywords = ["紧急", "限时", "截止", "今日", "最新", "公告", "变更", "更正"]
        biz_keywords = ["招标", "采购", "中标", "成交", "询价", "竞争性", "磋商", "邀请"]
        for kw in hot_keywords:
            if kw in title:
                category = "hot"
                break
        if category == "general":
            for kw in biz_keywords:
                if kw in title:
                    category = "business"
                    break

        crawl_item = CrawlResult(
            task_id=task_id,
            title=title,
            url=item.get("url", ""),
            source=item.get("source", ""),
            pub_date=item.get("pub_date", ""),
            content=item.get("content", ""),
            keyword_score=item.get("keyword_score", 0),
            relevance_score=item.get("relevance_score", 0),
            category=category,
            is_hot=is_hot,
            hot_score=hot_score,
        )
        db.add(crawl_item)
    await db.flush()


@router.post("/tasks/{task_id}/run")
async def run_monitor_task(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MonitoringTask).where(MonitoringTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="监控任务不存在")

    from services.news.skills.news_crawler_skill import NewsCrawlerSkill

    gateway = get_llm_gateway()
    skill = NewsCrawlerSkill()
    ctx = SkillContext(
        project_id="",
        db=db,
        llm=gateway,
        parameters={
            "task_id": task_id,
            "keywords": task.keywords,
            "exclude_keywords": task.exclude_keywords,
            "must_contain_keywords": task.must_contain_keywords,
            "sites": task.sites,
            "max_pages": 3,
        },
    )
    skill_result = await skill.safe_execute(ctx)

    if skill_result.success:
        task.last_run_at = datetime.now()
        items = skill_result.data.get("results", []) if skill_result.data else []
        await _save_crawl_results(db, task_id, items)
        await db.flush()

    return {
        "success": skill_result.success,
        "data": skill_result.data,
        "error": skill_result.error,
    }


@router.post("/tasks/{task_id}/semantic-filter")
async def semantic_filter_results(
    task_id: str,
    company_profile: str = "",
    threshold: float = 0.6,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(MonitoringTask).where(MonitoringTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="监控任务不存在")

    crawler_skill = NewsCrawlerSkill()
    gateway = get_llm_gateway()
    ctx = SkillContext(
        project_id="",
        db=db,
        llm=gateway,
        parameters={
            "task_id": task_id,
            "keywords": task.keywords,
            "exclude_keywords": task.exclude_keywords,
            "must_contain_keywords": task.must_contain_keywords,
            "sites": task.sites,
        },
    )
    crawl_result = await crawler_skill.safe_execute(ctx)

    if not crawl_result.success:
        return {"success": False, "error": crawl_result.error}

    items = crawl_result.data.get("results", [])

    from services.news.skills.news_crawler_skill import AISemanticFilterSkill

    filter_skill = AISemanticFilterSkill()
    filter_ctx = SkillContext(
        project_id="",
        db=db,
        llm=gateway,
        parameters={
            "items": items,
            "company_profile": company_profile,
            "threshold": threshold,
        },
    )
    filter_result = await filter_skill.safe_execute(filter_ctx)

    if filter_result.success and filter_result.data:
        filtered_items = filter_result.data.get("filtered", [])
        await _save_crawl_results(db, task_id, filtered_items)

    return {
        "success": filter_result.success,
        "data": filter_result.data,
        "error": filter_result.error,
    }


@router.get("/tasks/{task_id}/results")
async def list_task_results(task_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(CrawlResult)
        .where(CrawlResult.task_id == task_id)
        .order_by(CrawlResult.created_at.desc())
        .limit(100)
    )
    items = result.scalars().all()
    return {
        "task_id": task_id,
        "results": [
            {
                "id": str(r.id),
                "title": r.title,
                "url": r.url,
                "source": r.source,
                "pub_date": r.pub_date,
                "content": r.content[:200] if r.content else "",
                "keyword_score": r.keyword_score,
                "relevance_score": r.relevance_score,
                "category": r.category,
                "is_hot": r.is_hot,
                "hot_score": r.hot_score,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in items
        ],
    }


@router.get("/today-hot")
async def get_today_hot(
    category: str = Query("all", description="all|hot|business"),
    limit: int = Query(50, description="返回条数"),
    db: AsyncSession = Depends(get_db),
):
    today_start = datetime.combine(date.today(), datetime.min.time())

    conditions = [CrawlResult.created_at >= today_start]
    if category == "hot":
        conditions.append(CrawlResult.category == "hot")
    elif category == "business":
        conditions.append(CrawlResult.category == "business")

    count_result = await db.execute(
        select(func.count(CrawlResult.id)).where(and_(*conditions))
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(CrawlResult)
        .where(and_(*conditions))
        .order_by(CrawlResult.hot_score.desc(), CrawlResult.created_at.desc())
        .limit(limit)
    )
    items = result.scalars().all()

    hot_count_result = await db.execute(
        select(func.count(CrawlResult.id)).where(
            and_(CrawlResult.created_at >= today_start, CrawlResult.category == "hot")
        )
    )
    hot_count = hot_count_result.scalar() or 0

    biz_count_result = await db.execute(
        select(func.count(CrawlResult.id)).where(
            and_(CrawlResult.created_at >= today_start, CrawlResult.category == "business")
        )
    )
    biz_count = biz_count_result.scalar() or 0

    return {
        "date": date.today().isoformat(),
        "total": total,
        "hot_count": hot_count,
        "business_count": biz_count,
        "category": category,
        "items": [
            {
                "id": str(r.id),
                "title": r.title,
                "url": r.url,
                "source": r.source,
                "pub_date": r.pub_date,
                "content": r.content[:300] if r.content else "",
                "keyword_score": r.keyword_score,
                "relevance_score": r.relevance_score,
                "category": r.category,
                "is_hot": r.is_hot,
                "hot_score": round(r.hot_score, 2),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in items
        ],
    }


@router.post("/refresh-hot")
async def refresh_today_hot(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MonitoringTask).where(MonitoringTask.enabled == True)
    )
    tasks = result.scalars().all()

    if not tasks:
        return {"success": True, "message": "没有启用的监控任务", "items_count": 0}

    gateway = get_llm_gateway()
    total_new = 0

    for task in tasks:
        try:
            from services.news.skills.news_crawler_skill import NewsCrawlerSkill

            skill = NewsCrawlerSkill()
            ctx = SkillContext(
                project_id="",
                db=db,
                llm=gateway,
                parameters={
                    "task_id": str(task.id),
                    "keywords": task.keywords,
                    "exclude_keywords": task.exclude_keywords,
                    "must_contain_keywords": task.must_contain_keywords,
                    "sites": task.sites,
                    "max_pages": 2,
                },
            )
            skill_result = await skill.safe_execute(ctx)

            if skill_result.success and skill_result.data:
                items = skill_result.data.get("results", [])
                await _save_crawl_results(db, str(task.id), items)
                total_new += len(items)

                task.last_run_at = datetime.now()
        except Exception:
            continue

    await db.flush()

    return {
        "success": True,
        "message": f"已刷新 {len(tasks)} 个监控任务，获取 {total_new} 条新结果",
        "tasks_count": len(tasks),
        "items_count": total_new,
    }
