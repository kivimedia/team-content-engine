"""A client workspace's own persona (5-Oct, Matan): every prompt that named Ziv, his
coaching or his dogs speaks about the client instead, in his language. Owner workspaces
keep every prompt byte for byte. Synthetic data only.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from tce.db.base import Base
from tce.db.workspace_filter import set_workspace_context
from tce.editorial import persona as persona_mod
from tce.settings import settings

MATAN = uuid.UUID("40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
OWNER = uuid.UUID("30c13a7e-432f-4c3a-bade-52483262d793")
OWNER_DEFAULT = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
T0 = datetime(2026, 10, 1, 12, 0, 0)


@compiles(ARRAY, "sqlite")
def _array_sqlite(_type, _compiler, **_kw):  # pragma: no cover - DDL only
    return "TEXT"


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover - DDL only
    return "TEXT"


@pytest.fixture(autouse=True)
def owners(monkeypatch):
    monkeypatch.setattr(settings, "owner_workspace_ids", "", raising=False)
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(OWNER_DEFAULT), raising=False)
    monkeypatch.setattr(settings, "workspace_aside_names", "", raising=False)
    yield
    set_workspace_context(None)


@pytest.fixture
def hebrew(monkeypatch):
    monkeypatch.setattr(settings, "workspace_languages", f"{MATAN}:he", raising=False)


@pytest.fixture
def lanes(monkeypatch):
    monkeypatch.setattr(settings, "workspace_lane_profiles", f"{MATAN}:performer", raising=False)


def matan(**over) -> persona_mod.Persona:
    """What load_persona builds from his live rows (shape, synthetic text)."""
    creator = SimpleNamespace(
        creator_name="Matan Rosenberg",
        style_notes="מנטליסט וקוסם לאירועים מכפר סבא.",
        top_patterns=["פתיחה בשאלה אישית"],
    )
    voice = SimpleNamespace(
        vocabulary_signature={"phrases": ["מה חוגגים?", "וואי וואי"], "samples": ["אני קוסם אבל לא עד כדי כך"],
                              "avoided_words": ["סוד הקסם"]},
        sentence_rhythm_profile={"register": "warm spoken Israeli Hebrew"},
        values_and_beliefs=["קסם הוא חוויה של אנשים, לא טריק"],
        taboos=["לעולם לא לחשוף או להסביר שיטה של קסם", "לא לדבר על מצב כספי"],
        recurring_themes=["אבא טרי"],
        humor_type="playful self-deprecating",
    )
    brand = SimpleNamespace(description="צוחקים. נדהמים. נהנים. נקודה.", name="Matan Rosenberg - אמן החושים")
    p = persona_mod.persona_from_rows(MATAN, creator, brand, voice, language="he")
    return p if not over else persona_mod.Persona(**{**p.__dict__, **over})


@pytest.fixture
async def profile_sm(editorial_sessionmaker):
    """The editorial database plus the three profile tables."""
    engine = editorial_sessionmaker.kw["bind"]
    tables = [Base.metadata.tables[n] for n in ("creator_profiles", "brand_profiles", "founder_voice_profiles")]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    return editorial_sessionmaker


async def seed_profiles(sm) -> None:
    from tce.models.brand_profile import BrandProfile
    from tce.models.creator_profile import CreatorProfile
    from tce.models.founder_voice_profile import FounderVoiceProfile

    async with sm() as s:
        s.add_all([
            # The owner's global rows, newer than the client's: never his persona.
            CreatorProfile(workspace_id=None, creator_name="Ziv Raviv", created_at=T0 + timedelta(days=3)),
            FounderVoiceProfile(workspace_id=None, humor_type="owner humour", created_at=T0 + timedelta(days=3)),
            CreatorProfile(workspace_id=MATAN, creator_name="Matan Rosenberg",
                           style_notes="מנטליסט לאירועים", created_at=T0),
            BrandProfile(workspace_id=MATAN, name="Matan Rosenberg - אמן החושים",
                         description="צוחקים. נדהמים.", created_at=T0),
            FounderVoiceProfile(workspace_id=MATAN, humor_type="playful", created_at=T0),
        ])
        await s.commit()


# ---------------------------------------------------------------- 1. the persona


async def test_owner_workspaces_never_get_a_persona(profile_sm):
    await seed_profiles(profile_sm)
    async with profile_sm() as s:
        assert await persona_mod.load_persona(s, OWNER) is None
        assert await persona_mod.load_persona(s, OWNER_DEFAULT) is None
        assert await persona_mod.load_persona(s, None) is None


async def test_client_persona_comes_from_its_own_rows_never_the_global_ones(profile_sm, hebrew):
    await seed_profiles(profile_sm)
    async with profile_sm() as s:
        p = await persona_mod.load_persona(s, MATAN)
        nobody = await persona_mod.load_persona(s, uuid.uuid4())
    assert p is not None and p.name == "Matan" and p.full_name == "Matan Rosenberg"
    assert p.humor == "playful" and p.language == "he" and "צוחקים" in p.brand
    assert "Ziv" not in p.voice_block() and "owner humour" not in p.voice_block()
    # A workspace with no rows of its own: no persona (the global rows are the owner's).
    assert nobody is None


def test_aside_names_are_per_workspace(monkeypatch):
    monkeypatch.setattr(settings, "workspace_aside_names", f"{MATAN}:Bamba|Lucky, {OWNER}:X", raising=False)
    assert persona_mod.workspace_aside_names(MATAN) == ("Bamba", "Lucky")
    assert persona_mod.workspace_aside_names(uuid.uuid4()) == ()
    assert "workspace_aside_names" in type(settings).model_fields


def test_the_voice_block_carries_his_taboos_and_phrases():
    block = matan().voice_block()
    assert "HIS TABOOS" in block and "לעולם לא לחשוף" in block
    assert "מה חוגגים?" in block and "Matan Rosenberg" in block


# ---------------------------------------------------------------- 2. the editorial chat (phase 4)


async def _turn(sm, ws, monkeypatch):
    from tce.editorial import conversation
    from tce.llm import LLMResult

    captured: dict = {}

    async def _complete(request, **kwargs):
        captured["request"] = request
        return LLMResult(job_id=uuid.uuid4(), text="", structured={"reply": "ok", "proposal": None},
                         model="claude-opus-5-5")

    monkeypatch.setattr(conversation._llm, "complete", _complete)
    async with sm() as s:
        thread = await conversation.ensure_thread(s, ws, context_type="room", context_id=ws)
        _editor, assistant = await conversation.post_message(s, ws, thread, text="מה דעתך על הרעיון?", mode="discuss")
        await s.commit()
        ids = (thread.id, assistant.id)
    await conversation.run_turn(sm, ws, *ids)
    return captured["request"]


async def test_owner_chat_prompt_is_byte_for_byte(profile_sm, monkeypatch):
    from tce.editorial import conversation

    await seed_profiles(profile_sm)
    req = await _turn(profile_sm, OWNER, monkeypatch)
    assert req.system == conversation.SYSTEM
    assert req.output_schema == conversation.SCHEMA
    assert req.prompt_version == conversation.PROMPT_VERSION
    assert "Ziv says:" in req.messages[0]["content"]


async def test_matan_talks_ideas_through_in_hebrew_with_his_own_assistant(profile_sm, monkeypatch, hebrew):
    from tce.llm.provider import HEBREW_STYLE, localize_request

    await seed_profiles(profile_sm)
    req = await _turn(profile_sm, MATAN, monkeypatch)
    assert "Ziv" not in req.system and "business coach" not in req.system
    assert "Matan's editorial assistant" in req.system and "Answer Matan in Hebrew" in req.system
    assert "Never explain or hint at how" in req.system
    assert "Ziv" not in req.messages[0]["content"] and "Matan says:" in req.messages[0]["content"]
    assert "Ziv" not in str(req.output_schema)
    stored = localize_request(req)
    assert HEBREW_STYLE in stored.system and stored.prompt_version.endswith(".he")


# ---------------------------------------------------------------- 3. Jennifer (phase 7)


def test_owner_jennifer_prompts_are_unchanged():
    from tce.production import autoedit, qc
    from tce.production import rules as rule_text

    skill = autoedit.EDITOR_SKILL_PATH.read_text(encoding="utf-8").strip()
    assert autoedit.editor_skill() == skill and autoedit.editor_skill(None) == skill
    for lang in ("en", "he"):
        assert autoedit.review_system(["Maple", "Rain"], "R", language=lang) == autoedit.review_system(
            ["Maple", "Rain"], "R", language=lang, persona=None
        )
        assert qc.asides_system(["Maple", "Rain"], skill=skill, language=lang) == qc.asides_system(
            ["Maple", "Rain"], skill=skill, language=lang, persona=None
        )
    en = autoedit.review_system(["Maple", "Rain"])
    assert "You edit Ziv Raviv's walking videos." in en and "Maple and Rain" in en and skill in en
    assert autoedit.edit_request_system() == autoedit.EDIT_REQUEST_SYSTEM + "\n\n" + skill
    assert autoedit.edit_batch_system() == autoedit.edit_request_system() + "\n\n" + autoedit.EDIT_BATCH_RULES
    assert rule_text.distill_system() is rule_text.DISTILL_SYSTEM


@pytest.mark.parametrize("lang", ["en", "he"])
def test_matan_jennifer_never_names_ziv_his_coaching_or_his_dogs(lang):
    from tce.production import autoedit, qc
    from tce.production import rules as rule_text

    p = matan()
    texts = {
        "review": autoedit.review_system(["Maple", "Rain"], "", language=lang, persona=p),
        "asides": qc.asides_system(["Maple", "Rain"], skill=autoedit.editor_skill(p), language=lang, persona=p),
        "request": autoedit.edit_request_system(p),
        "batch": autoedit.edit_batch_system(p),
        "distill": rule_text.distill_system(p),
        "skill": autoedit.editor_skill(p),
    }
    for name, text in texts.items():
        for banned in ("Ziv", "Maple", "Rain", "two dogs", "his dogs", "coaching and selling"):
            assert banned not in text, f"{name} still says {banned!r}"
    assert "Matan" in texts["review"] and "Matan" in texts["asides"] and "Matan" in texts["request"]
    assert "Matan" in texts["distill"] and "Matan" in texts["skill"]


def test_matan_asides_name_who_he_really_talks_to():
    from tce.production import autoedit, qc

    p = matan(aside_names=("Bamba",))
    review = autoedit.review_system([], "", language="he", persona=p)
    asides = qc.asides_system([], language="he", persona=p)
    assert "Bamba" in review and "Bamba" in asides and "Maple" not in review + asides


def test_the_router_gives_jennifer_his_persona(monkeypatch, hebrew):
    from tce.api.routers import production as prod

    p = matan(aside_names=("Bamba",))
    words = [{"text": "שלום", "start_s": 0.0, "end_s": 0.3, "precision": "word"}]
    _prompt, system = prod._review_request(words, "", language="he", persona=p)
    assert "Ziv" not in system and "Matan" in system
    assert prod.aside_names(p) == ["Bamba"]
    assert prod.aside_names() == [n.strip() for n in settings.production_aside_names.split(",") if n.strip()]
    _prompt, owner = prod._review_request(words, "", language="en")
    assert "Ziv Raviv" in owner
    # An owner workspace never even opens a session for a persona.
    monkeypatch.setattr(prod, "session_factory", lambda: (_ for _ in ()).throw(AssertionError("no db")))
    assert asyncio.run(prod._persona(OWNER)) is None
    assert asyncio.run(prod._persona(OWNER_DEFAULT)) is None


# ---------------------------------------------------------------- 4. Hebrew post copy (phase 8)


def test_owner_post_copy_is_unchanged():
    from tce.production import publishing

    assert publishing.copy_system() is publishing.COPY_SYSTEM
    assert publishing.copy_schema() is publishing.COPY_SCHEMA
    assert publishing.revise_system() == publishing.REVISE_SYSTEM
    assert publishing.platforms_for() == ("instagram", "facebook", "youtube", "linkedin")
    assert publishing.REVISE_SYSTEM.startswith(publishing.COPY_SYSTEM)


def test_matan_post_copy_is_his_four_platforms_in_his_voice():
    from tce.production import publishing

    p = matan()
    system = publishing.copy_system(p)
    assert "Ziv" not in system and "coaches" not in system and "linkedin" not in system.lower()
    assert "Matan" in system and "Israeli Hebrew" in system and "tiktok.caption" in system
    assert "how an effect is done" in system and "HIS TABOOS" in system
    schema = publishing.copy_schema(p)
    assert schema["required"] == ["instagram", "facebook", "youtube", "tiktok"]
    assert publishing.platforms_for(p) == ("instagram", "facebook", "youtube", "tiktok")
    assert publishing.LABELS["tiktok"] == "TikTok"
    assert "Matan" in publishing.revise_system(p) and "REVISING" in publishing.revise_system(p)


def test_matan_post_copy_keeps_each_platforms_limits():
    from tce.production import publishing

    tags = " ".join(f"#תג{i}" for i in range(14))
    out = publishing.clean_client_copy(
        {
            "instagram": {"caption": f"שורה — ראשונה\n{tags}"},
            "facebook": {"message": "פוסט " + tags},
            "youtube": {"title": "כ" * 120, "description": "תיאור #shorts", "tags": [f"t{i}" for i in range(12)]},
            "tiktok": {"caption": "קצר וחד " + tags},
            "linkedin": {"message": "never"},
        }
    )
    assert set(out) == {"instagram", "facebook", "youtube", "tiktok"}
    assert out["instagram"]["caption"].count("#") == 10 and "—" not in out["instagram"]["caption"]
    assert out["facebook"]["message"].count("#") == 3
    assert out["tiktok"]["caption"].count("#") == 5
    assert len(out["youtube"]["title"]) <= 95 and len(out["youtube"]["tags"]) == 8
    assert publishing.missing("tiktok", {"caption": ""}) == "TikTok has no caption"
    flagged = publishing.copy_problems({"tiktok": {"caption": "הסוד של הטריק הזה"}, "facebook": {"message": "פוסט"}})
    assert "tiktok" in flagged and "facebook" not in flagged


async def test_matan_posts_are_drafted_with_his_system_and_never_posted_by_tce(
    editorial_sessionmaker, monkeypatch, lanes, hebrew
):
    from tce.api.routers import production as prod
    from tce.llm.provider import LLMResult
    from tce.models.editorial import RecordingUpload, TopicCandidate
    from tce.production import publishing

    monkeypatch.setattr(prod, "session_factory", lambda: editorial_sessionmaker)
    p = matan()

    async def fake_persona(ws, db=None):
        return p if ws == MATAN else None

    asked: list = []

    async def fake_ask(kind, prompt, system, schema, ws, key, **kw):
        asked.append((system, schema, kw))
        return LLMResult(job_id=uuid.uuid4(), text="", model="claude-opus-5-5", structured={
            "instagram": {"caption": "כיתוב"}, "facebook": {"message": "פוסט"},
            "youtube": {"title": "כותרת", "description": "תיאור #shorts", "tags": ["shorts"]},
            "tiktok": {"caption": "טיקטוק #קסם"},
        })

    monkeypatch.setattr(prod, "_persona", fake_persona)
    monkeypatch.setattr(prod, "_ask", fake_ask)
    async with editorial_sessionmaker() as s:
        cand = TopicCandidate(workspace_id=MATAN, week_start=datetime(2026, 10, 5), moment_ids=["m"], title="קסם",
                              lesson="l", audience="a", public_angle="p", gates={}, status="recorded")
        s.add(cand)
        await s.flush()
        up = RecordingUpload(workspace_id=MATAN, candidate_id=cand.id, original_filename="w.mp4",
                             storage_path="/tmp/w.mp4", sha256=uuid.uuid4().hex * 2, status="edited",
                             edited_path="/tmp/w-edited.mp4",
                             transcript=[{"text": "שלום", "start_s": 0.0, "end_s": 0.5, "precision": "word"}],
                             edit_plan={"keep": [[0.0, 1.0]]})
        s.add(up)
        await s.commit()
        uid = up.id
    await prod.draft_posts(uid, MATAN)
    system, schema, kw = asked[0]
    assert system == publishing.copy_system(p) and schema == publishing.copy_schema(p)
    assert kw == {"prompt_version": publishing.CLIENT_PROMPT_VERSION}
    async with editorial_sessionmaker() as s:
        pubs = await prod._publications(s, MATAN, uid)
    assert sorted(pubs) == ["facebook", "instagram", "tiktok", "youtube"]
    assert pubs["tiktok"].copy == {"caption": "טיקטוק #קסם"}
    # The schedule-* skills post to the owner's accounts: never for his workspace.
    assert prod._posts_from_tce(MATAN, None) is False
    assert prod._posts_from_tce(MATAN, p) is False
    assert prod._posts_from_tce(OWNER, None) is True
    assert prod._posts_from_tce(uuid.uuid4(), None) is True  # an unknown workspace, as before


# ---------------------------------------------------------------- 5. jobs with no request context


def test_job_workspace_carries_only_a_workspace_with_its_own_language(hebrew):
    from tce.llm.provider import job_workspace

    assert job_workspace(MATAN) == MATAN and job_workspace(str(MATAN)) == MATAN
    assert job_workspace(OWNER) is None and job_workspace(None) is None and job_workspace("x") is None


def test_shim_client_carries_the_workspace(monkeypatch, hebrew):
    from tce.llm import provider

    seen: list = []

    async def fake_complete(req, **kw):
        seen.append(req)
        return provider.LLMResult(job_id=uuid.uuid4(), text="t", structured=None, model="claude-opus-5-5")

    monkeypatch.setattr(provider, "complete", fake_complete)
    for ws in (MATAN, OWNER, None):
        client = provider.get_llm_client("calendar_topics", workspace_id=ws)
        asyncio.run(client.messages.create(messages=[{"role": "user", "content": "x"}], system="s"))
    assert [r.workspace_id for r in seen] == [MATAN, None, None]
    assert "LANGUAGE: this workspace works in Hebrew" in provider.localize_request(seen[0]).system
    assert provider.localize_request(seen[1]) is seen[1]


def test_an_old_agent_carries_its_runs_workspace(monkeypatch, hebrew):
    from tce.agents import base

    seen: list = []

    async def fake_complete(req, **kw):
        seen.append(req)
        from tce.llm import LLMResult

        return LLMResult(job_id=uuid.uuid4(), text="{}", structured=None, model="claude-opus-5-5")

    class Tracker:
        async def record(self, **kw):
            return None

    class Agent(base.AgentBase):
        name = "persona_probe"

        async def _execute(self, context):
            await self._call_llm([{"role": "user", "content": "x"}], system="s")
            return {}

    monkeypatch.setattr(base, "complete", fake_complete)
    for ws in (str(MATAN), str(OWNER), None):
        agent = Agent(db=None, settings=settings, cost_tracker=Tracker(), prompt_manager=None)
        asyncio.run(agent.run({"workspace_id": ws} if ws else {}))
    assert [r.workspace_id for r in seen] == [MATAN, None, None]


def test_the_weeks_final_ranking_is_his_not_ziv_coaching():
    import inspect

    from tce.editorial import lane_profile, selector

    assert selector.rank_system_for(None) is selector.RANK_SYSTEM_PROMPT
    lanes_text = selector.rank_system_for(lane_profile.PROFILES["performer"])
    for banned in ("Ziv", "coach", "four gates", "AI one"):
        assert banned not in lanes_text
    assert "mentalism" in lanes_text and "explains how an effect is done" in lanes_text
    src = inspect.getsource(selector._global_rank)
    assert "rank_system_for(lane_profile.profile_for(ws))" in src and "RANK_LANES_PROMPT_VERSION" in src


def test_the_orchestrator_hands_its_workspace_to_each_agent():
    import inspect

    from tce.orchestrator import engine

    assert "agent.workspace_id = self.workspace_id" in inspect.getsource(engine.PipelineOrchestrator._run_step)
