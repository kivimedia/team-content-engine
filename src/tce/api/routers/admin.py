"""Admin endpoints — seeding, maintenance."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tce.db.session import get_db
from tce.services.seed import seed_database

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/seed")
async def trigger_seed(db: AsyncSession = Depends(get_db)) -> dict:
    """Manually seed the database with default data. Idempotent."""
    counts = await seed_database(db)
    return {"status": "ok", "seeded": counts}
