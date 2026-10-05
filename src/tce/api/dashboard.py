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
_WORKSPACE_SW_PATH = Path(__file__).parent / "workspace-sw.js"
# Talk to the editor (1-Oct): the hold-to-talk half of the notes sheet. Its own files,
# so the call's code stays apart from the workspace it is drawn into.
_TALK_VOICE_JS_PATH = Path(__file__).parent / "talk-voice.js"
_TALK_VOICE_CSS_PATH = Path(__file__).parent / "talk-voice.css"
_I18N_HE_JS_PATH = Path(__file__).parent / "i18n-he.js"
_I18N_HE_CSS_PATH = Path(__file__).parent / "i18n-he.css"
_CACHE: str | None = None

# 5-Oct: a Hebrew workspace's own login gets its screens right to left, with a
# Hebrew-capable face and the Hebrew UI layer, loaded before the page's scripts.
# Only a scoped editor key (a client login) can switch this on: the owner's pages
# are never rewritten, so they stay byte for byte the files on disk.
HE_HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Heebo:wght@400;700;800;900&display=swap">'
    '<link rel="stylesheet" href="i18n-he.css">'
    '<script src="i18n-he.js"></script>'
    "</head>"
)


def _scoped_workspace(request: Request):
    from tce.api.private_access import scoped_editor_workspace

    return scoped_editor_workspace(request.headers.get("x-tce-editor-key"))


def _page_language(request: Request) -> str:
    ws = _scoped_workspace(request)
    if ws is None:
        return "en"
    from tce.db.workspace_filter import workspace_language

    return workspace_language(ws)


def _localize(html: str, request: Request) -> str:
    if _page_language(request) != "he":
        return html
    html = html.replace('<html lang="en">', '<html lang="he" dir="rtl">', 1)
    return html.replace("</head>", HE_HEAD, 1)

# Every editorial workspace path serves the same shell; the page reads the URL
# and renders itself. They are real paths, not hash fragments, so the back
# button, a bookmark and a link in a message all behave the way he expects.
WORKSPACE_PATHS = ("/today", "/topics", "/week", "/library", "/settings")


def _load_html() -> str:
    global _CACHE
    if _CACHE is None:
        _CACHE = _HTML_PATH.read_text(encoding="utf-8")
    return _CACHE


@router.get("/", include_in_schema=False)
async def root_redirect(request: Request):
    # A client login has no operator dashboard; its home is its own Today.
    if _scoped_workspace(request) is not None:
        return RedirectResponse(url="/today")
    # Keep the query (e.g. ?week=2026-09-07) so deep links survive; the page validates it.
    # The path is fixed, so the query can never redirect anywhere else.
    query = request.url.query
    return RedirectResponse(url="/dashboard" + (f"?{query}" if query else ""))


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return _load_html()


@router.get("/record", response_class=HTMLResponse)
async def recording_studio(request: Request):
    return HTMLResponse(_localize(_RECORDING_HTML_PATH.read_text(encoding="utf-8"), request))


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


async def _workspace_page(request: Request | None = None) -> HTMLResponse | RedirectResponse:
    if not await _workspace_enabled():
        return RedirectResponse(url="/record")
    # Read fresh each request, like /record. The dashboard's in-process cache
    # is why a dashboard edit needs a restart, and this surface changes often.
    html = _WORKSPACE_HTML_PATH.read_text(encoding="utf-8")
    return HTMLResponse(_localize(html, request) if request is not None else html)


@router.get("/today", response_class=HTMLResponse, include_in_schema=False)
@router.get("/topics", response_class=HTMLResponse, include_in_schema=False)
@router.get("/week", response_class=HTMLResponse, include_in_schema=False)
@router.get("/library", response_class=HTMLResponse, include_in_schema=False)
@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def workspace_shell(request: Request):
    return await _workspace_page(request)


@router.get("/topics/{candidate_id}", response_class=HTMLResponse, include_in_schema=False)
async def workspace_topic(candidate_id: str, request: Request):
    return await _workspace_page(request)


@router.get("/scripts/{packet_id}", response_class=HTMLResponse, include_in_schema=False)
async def workspace_script(packet_id: str, request: Request):
    return await _workspace_page(request)


# 1-Oct final review: the notes sheet's own address. Without it a reload of the sheet, a
# phone restoring the tab, a pasted link or the Back link of the voice's sign-in page
# all landed on {"detail":"Not Found"}. The shell's <base> keeps its assets working here.
@router.get("/library/{upload_id}/talk", response_class=HTMLResponse, include_in_schema=False)
async def workspace_notes_sheet(upload_id: str, request: Request):
    return await _workspace_page(request)


# 3-Oct: "Jennifer's rules", the rules she learned from his notes, each with the video it
# came from and a Delete button. Its own address, so a reload or a pasted link lands on it.
@router.get("/library/rules", response_class=HTMLResponse, include_in_schema=False)
async def workspace_rules(request: Request):
    return await _workspace_page(request)


@router.get("/workspace.css", include_in_schema=False)
async def workspace_css():
    from fastapi.responses import Response

    return Response(_WORKSPACE_CSS_PATH.read_text(encoding="utf-8"), media_type="text/css")


@router.get("/workspace-sw.js", include_in_schema=False)
async def workspace_sw():
    """The push service worker.

    `Service-Worker-Allowed: /` lets it control the whole app even though it is
    served from a path, which is what makes a notification tap reuse the tab he
    already has open instead of stacking windows.
    """
    from fastapi.responses import Response

    return Response(
        _WORKSPACE_SW_PATH.read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@router.get("/workspace.webmanifest", include_in_schema=False)
async def workspace_manifest():
    """Makes the workspace installable.

    This is not decoration on iOS: Safari only delivers web push to a site that
    has been added to the Home Screen, so without a manifest the notification
    feature would silently do nothing on the one device he actually uses.
    """
    from fastapi.responses import JSONResponse

    return JSONResponse(
        {
            "name": "TCE editorial workspace",
            "short_name": "TCE",
            "start_url": "today",
            "scope": "./",
            "display": "standalone",
            "background_color": "#f7f3e8",
            "theme_color": "#10213b",
        },
        media_type="application/manifest+json",
    )


@router.get("/workspace.js", include_in_schema=False)
async def workspace_js():
    from fastapi.responses import Response

    return Response(
        _WORKSPACE_JS_PATH.read_text(encoding="utf-8"),
        media_type="application/javascript",
    )


@router.get("/talk-voice.js", include_in_schema=False)
async def talk_voice_js():
    from fastapi.responses import Response

    return Response(
        _TALK_VOICE_JS_PATH.read_text(encoding="utf-8"),
        media_type="application/javascript",
    )


@router.get("/talk-voice.css", include_in_schema=False)
async def talk_voice_css():
    from fastapi.responses import Response

    return Response(_TALK_VOICE_CSS_PATH.read_text(encoding="utf-8"), media_type="text/css")


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


@router.get("/i18n-he.js", include_in_schema=False)
async def i18n_he_js():
    from fastapi.responses import Response

    return Response(_I18N_HE_JS_PATH.read_text(encoding="utf-8"), media_type="application/javascript")


@router.get("/i18n-he.css", include_in_schema=False)
async def i18n_he_css():
    from fastapi.responses import Response

    return Response(_I18N_HE_CSS_PATH.read_text(encoding="utf-8"), media_type="text/css")
