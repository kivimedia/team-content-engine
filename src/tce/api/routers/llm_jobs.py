"""/llm-jobs routes. Owned by its work package; every route depends on private access."""

from fastapi import APIRouter

router = APIRouter(prefix="/llm-jobs", tags=["llm-jobs"])
