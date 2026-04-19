"""Operator dashboard - serves pre-rendered HTML from file.

The HTML was extracted from the original inline Python string to avoid
escape sequence corruption. Edit dashboard.html directly for changes.
"""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(tags=["dashboard"])

_HTML_PATH = Path(__file__).parent / "dashboard.html"
_CACHE: str | None = None


def _load_html() -> str:
    global _CACHE
    if _CACHE is None:
        _CACHE = _HTML_PATH.read_text(encoding="utf-8")
    return _CACHE


@router.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/dashboard")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return _load_html()
