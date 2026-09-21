"""Operator dashboard - serves pre-rendered HTML from file.

The HTML was extracted from the original inline Python string to avoid
escape sequence corruption. Edit dashboard.html directly for changes.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(tags=["dashboard"])

_HTML_PATH = Path(__file__).parent / "dashboard.html"
_RECORDING_HTML_PATH = Path(__file__).parent / "recording.html"
_RECORDING_CSS_PATH = Path(__file__).parent / "recording.css"
_RECORDING_JS_PATH = Path(__file__).parent / "recording.js"
_WORKSPACE_HTML_PATH = Path(__file__).parent / "workspace.html"
_WORKSPACE_CSS_PATH = Path(__file__).parent / "workspace.css"
_WORKSPACE_JS_PATH = Path(__file__).parent / "workspace.js"
_CACHE: str | None = None

# Every editorial workspace path serves the same shell; the page reads the URL
# and renders itself. They are real paths, not hash fragments, so the back
# button, a bookmark and a link in a message all behave the way he expects.
WORKSPACE_PATHS = ("/today", "/topics", "/week", "/library")


def _load_html() -> str:
    global _CACHE
    if _CACHE is None:
        _CACHE = _HTML_PATH.read_text(encoding="utf-8")
    return _CACHE


@router.get("/", include_in_schema=False)
async def root_redirect(request: Request):
    # Keep the query (e.g. ?week=2026-09-07) so deep links survive; the page validates it.
    # The path is fixed, so the query can never redirect anywhere else.
    query = request.url.query
    return RedirectResponse(url="/dashboard" + (f"?{query}" if query else ""))


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return _load_html()


@router.get("/record", response_class=HTMLResponse)
async def recording_studio():
    return _RECORDING_HTML_PATH.read_text(encoding="utf-8")


async def _workspace_enabled() -> bool:
    """Is the editorial workspace on for this install?

    Fail-closed on a database problem: the studio still works without any of
    this, and sending him to a half-loaded new surface when the DB is unhappy is
    worse than sending him to the one that has been working for weeks.
    """
    try:
        from tce.db.session import async_session
        from tce.services.feature_flags import FeatureFlagService

        async with async_session() as db:
            enabled = await FeatureFlagService(db).is_enabled("editorial_workspace_v2")
            await db.commit()
            return bool(enabled)
    except Exception:
        return False


async def _workspace_page() -> HTMLResponse | RedirectResponse:
    if not await _workspace_enabled():
        return RedirectResponse(url="/record")
    # Read fresh each request, like /record. The dashboard's in-process cache
    # is why a dashboard edit needs a restart, and this surface changes often.
    return HTMLResponse(_WORKSPACE_HTML_PATH.read_text(encoding="utf-8"))


@router.get("/today", response_class=HTMLResponse, include_in_schema=False)
@router.get("/topics", response_class=HTMLResponse, include_in_schema=False)
@router.get("/week", response_class=HTMLResponse, include_in_schema=False)
@router.get("/library", response_class=HTMLResponse, include_in_schema=False)
async def workspace_shell():
    return await _workspace_page()


@router.get("/topics/{candidate_id}", response_class=HTMLResponse, include_in_schema=False)
async def workspace_topic(candidate_id: str):
    return await _workspace_page()


@router.get("/scripts/{packet_id}", response_class=HTMLResponse, include_in_schema=False)
async def workspace_script(packet_id: str):
    return await _workspace_page()


@router.get("/workspace.css", include_in_schema=False)
async def workspace_css():
    from fastapi.responses import Response

    return Response(_WORKSPACE_CSS_PATH.read_text(encoding="utf-8"), media_type="text/css")


@router.get("/workspace.js", include_in_schema=False)
async def workspace_js():
    from fastapi.responses import Response

    return Response(
        _WORKSPACE_JS_PATH.read_text(encoding="utf-8"),
        media_type="application/javascript",
    )


@router.get("/recording.css", include_in_schema=False)
async def recording_css():
    from fastapi.responses import Response

    return Response(_RECORDING_CSS_PATH.read_text(encoding="utf-8"), media_type="text/css")


@router.get("/recording.js", include_in_schema=False)
async def recording_js():
    from fastapi.responses import Response

    return Response(
        _RECORDING_JS_PATH.read_text(encoding="utf-8"),
        media_type="application/javascript",
    )
