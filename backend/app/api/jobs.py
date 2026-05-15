from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.job import JobRun

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _job_to_dict(job: JobRun) -> dict:
    return {
        "id": job.id,
        "job_name": job.job_name,
        "status": job.status,
        "started_at": str(job.started_at) if job.started_at else None,
        "completed_at": str(job.completed_at) if job.completed_at else None,
        "error": job.error,
        "metadata": job.metadata_,
    }


@router.get("")
async def list_jobs(
    status: str | None = None,
    job_name: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    query = select(JobRun).order_by(JobRun.started_at.desc())
    if status:
        query = query.where(JobRun.status == status)
    if job_name:
        query = query.where(JobRun.job_name.ilike(f"%{job_name}%"))

    query = query.offset(offset).limit(limit)
    rows = (await db.execute(query)).scalars().all()
    return [_job_to_dict(r) for r in rows]


@router.get("/running")
async def list_running_jobs(limit: int = 100, db: AsyncSession = Depends(get_db)):
    query = (
        select(JobRun)
        .where(JobRun.status == "running")
        .order_by(JobRun.started_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(query)).scalars().all()
    return [_job_to_dict(r) for r in rows]


@router.get("/failed")
async def list_failed_jobs(limit: int = 100, db: AsyncSession = Depends(get_db)):
    query = (
        select(JobRun)
        .where(JobRun.status == "failed")
        .order_by(JobRun.started_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(query)).scalars().all()
    return [_job_to_dict(r) for r in rows]


@router.get("/{job_id}")
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(JobRun, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_to_dict(job)
