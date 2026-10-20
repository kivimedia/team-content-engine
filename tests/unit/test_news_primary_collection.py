"""Regression cases from the 20-Oct audit. Entirely offline, no model calls."""
from datetime import datetime
from types import SimpleNamespace
import uuid
import socket

import httpx
import pytest

from tce.news.feeds import parse_feed
from tce.news.matcher import match_item
from tce.services import url_fetcher


def anchor(kind, term):
    return SimpleNamespace(id=uuid.uuid4(), kind=kind, term=term, weight=1)


def test_anthropic_html_collects_direct_announcements_and_real_dates():
    html = """<main><a href="/news/claude-haiku-5-5">
    <div>Announcements</div><time datetime="2026-10-07">Oct 7, 2026</time>
    <h3>Claude Haiku 5.5</h3></a>
    <a href="/news">All news</a><a href="https://evil.test/news/claude">Fake</a></main>"""
    items = parse_feed("html", html, source_url="https://www.anthropic.com/news")
    assert [(i.title, i.url, i.published_at) for i in items] == [
        ("Claude Haiku 5.5", "https://www.anthropic.com/news/claude-haiku-5-5",
         datetime(2026, 10, 7))
    ]


def test_broken_html_feed_is_failure_not_a_quiet_day():
    with pytest.raises(ValueError, match="announcement"):
        parse_feed("html", "<html>Access denied</html>",
                   source_url="https://www.anthropic.com/news")


def test_current_anthropic_root_release_and_list_card_markup():
    html = """<a href="/claude-haiku-5-5"><span>Announcements</span>
    <time>Oct 7, 2026</time><h4>Introducing Claude Haiku 5.5</h4>
    <p>Designed for high-volume, cost-sensitive work.</p></a>
    <a href="/news/public-benefit-fund"><time>Oct 18, 2026</time>
    <span class="PublicationList__title">Investing in the public benefit</span></a>"""
    items = parse_feed("html", html, source_url="https://www.anthropic.com/news")
    assert len(items) == 2
    assert items[1].url == "https://www.anthropic.com/claude-haiku-5-5"
    assert items[1].published_at == datetime(2026, 10, 7)
    assert items[0].title == "Investing in the public benefit"


def test_atom_publication_date_beats_updated_date():
    atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>one</id>
    <title>Release</title><published>2026-10-05T10:00:00Z</published>
    <updated>2026-10-15T10:00:00Z</updated></entry></feed>"""
    assert parse_feed("atom", atom)[0].published_at == datetime(2026, 10, 5, 10)


def test_mixed_release_is_not_a_benchmark_story():
    result = match_item(title="Claude Haiku 5.5",
                        summary="Now available for fast customer support. Beats benchmarks.",
                        anchors=[anchor("vendor", "anthropic")],
                        source_vendor="anthropic", business_relevance=True)
    assert result.matched


@pytest.mark.parametrize("title", [
    "Anthropic raises $5 billion for customer support AI",
    "Anthropic tops the benchmark leaderboard",
    "OpenAI appoints a new chief executive",
])
def test_noise_stays_blocked_even_with_a_business_keyword(title):
    result = match_item(title=title, anchors=[anchor("vendor", "anthropic"),
                                             anchor("vendor", "openai")],
                        business_relevance=True)
    assert not result.matched
    assert result.blocked_shape


def test_specific_owner_capability_can_qualify_without_a_recent_commit():
    result = match_item(title="AI now drafts follow-up emails after client meetings",
                        anchors=[], business_relevance=True)
    assert result.matched
    assert result.reason == "business capability: client follow-up"


def test_owner_capability_does_not_change_client_workspace_policy():
    assert not match_item(title="AI now drafts follow-up emails after client meetings",
                          anchors=[]).matched


def test_new_primary_ai_release_is_appraised_without_claiming_vendor_is_in_stack():
    result = match_item(title="Introducing a new Gemini assistant",
                        source_vendor="google", anchors=[], business_relevance=True)
    assert result.matched
    assert result.reason == "official AI release for appraisal"
    assert result.matches == []
    assert not match_item(title="Introducing a new Gemini assistant",
                          source_vendor="google", anchors=[]).matched


def test_publication_metadata_is_not_modified_or_fetch_time():
    html = """<meta content="2026-10-05T09:00:00-04:00" property="article:published_time">
    <script type="application/ld+json">{"dateModified":"2026-10-15"}</script>"""
    assert url_fetcher.extract_publication_date(html) == datetime(2026, 10, 5, 13)
    assert url_fetcher.extract_publication_date(
        '<script type="application/ld+json">{"dateModified":"2026-10-15"}</script>') is None


def test_publication_jsonld_date_and_ambiguous_times():
    assert url_fetcher.extract_publication_date(
        '<script type="application/ld+json">{"@graph":[{"@type":"NewsArticle",'
        '"datePublished":"2026-10-05","dateModified":"2026-10-15"}]}</script>'
    ) == datetime(2026, 10, 5)
    assert url_fetcher.extract_publication_date(
        '<time datetime="2026-10-05"></time><time datetime="2026-10-15"></time>'
    ) is None


GOOGLE_ARTICLE = (
    "https://workspaceupdates.googleblog.com/2026/10/"
    "publish-interactive-apps-from-gemini-app-to-Google-Sites.html"
)


@pytest.mark.parametrize("date_html", [
    # Exact date-field markup read from the approved Google announcement.
    "<section class='blog-post-full__left-column'>"
    "<p class='blog-post-full__date'>\nOctober 19, 2026\n</p></section>",
    "<h2 class='date-header'><span>Monday, October 19, 2026</span></h2>",
])
def test_google_article_visible_publication_date_is_read(date_html):
    assert url_fetcher.extract_publication_date(
        date_html, source_url=GOOGLE_ARTICLE,
    ) == datetime(2026, 10, 19)


def test_google_visible_date_does_not_guess_navigation_or_other_pages():
    assert url_fetcher.extract_publication_date(
        "<nav>October 19, 2026</nav><footer>October 20, 2026</footer>",
        source_url=GOOGLE_ARTICLE,
    ) is None
    explicit = "<p class='blog-post-full__date'>October 19, 2026</p>"
    for url in (
        "https://workspaceupdates.googleblog.com/",
        "https://other.example/2026/10/story.html",
    ):
        assert url_fetcher.extract_publication_date(explicit, source_url=url) is None
    assert url_fetcher.extract_publication_date(
        explicit + "<p class='blog-post-full__date'>October 20, 2026</p>",
        source_url=GOOGLE_ARTICLE,
    ) is None


@pytest.mark.asyncio
async def test_google_fetch_returns_the_visible_announcement_date(monkeypatch):
    client_type = httpx.AsyncClient
    markup = (
        "<html><title>Publish interactive apps</title><main>"
        "<p class='blog-post-full__date'>October 19, 2026</p>"
        "<p>A new Google Sites capability.</p></main></html>"
    )
    monkeypatch.setattr(url_fetcher.httpx, "AsyncClient", lambda **kw: client_type(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, text=markup, headers={"content-type": "text/html"},
        )),
    ))
    result = await url_fetcher.fetch_url_text(GOOGLE_ARTICLE)
    assert result["source_verified"] is True
    assert result["published_at"] == datetime(2026, 10, 19)


def test_primary_source_allowlist_rejects_lookalikes_credentials_and_homepages():
    for url in ("https://openai.com.evil.test/index/story",
                "https://secret@openai.com/index/story", "https://openai.com/",
                "http://127.0.0.1/index/story"):
        assert not url_fetcher.is_primary_announcement(url)


@pytest.mark.parametrize("url", [
    "https://www.anthropic.com/news/claude-code",
    "https://openai.com/index/introducing-the-codex-app/",
    "https://deepmind.google/blog/veo-3/",
    "https://developers.googleblog.com/en/gemini-api-release/",
    "https://x.ai/news/grok-voice-3",
    "https://ai.meta.com/blog/meta-llama-3/",
    "https://fal.ai/learn/devs/nemotron-3-nano-omni-is-now-on-fal",
    "https://blog.fal.ai/introducing-h3-max-by-fal/",
    "https://runwayml.com/research/gen-1",
    "https://runway.com/research/gen-1",
    "https://higgsfield.ai/blog/introducing-higgsfield-apps",
    "https://suno.com/blog/introducing-speech-beta",
    "https://blog.suno.com/blog/suno-updates-tos",
    "https://seed.bytedance.com/en/blog/one-take-creation-flexible-referencing-introducing-seedance-2-5",
    "https://blog.modelcontextprotocol.io/posts/2026-07-28-specification/",
])
def test_named_scout_providers_have_explicit_primary_article_routes(url):
    # Providers come from KMBot's existing morning/evening AI-news beat.
    assert url_fetcher.is_primary_announcement(url)


@pytest.mark.parametrize("url", [
    "https://x.ai/",
    "https://x.ai/news/",
    "https://x.ai/pricing",
    "https://x.ai.evil.test/news/new-model",
    "https://unknown.example/blog/new-model",
    "https://user.fal.ai/learn/devs/new-model",
    "https://fal.ai/models/some-user/model",
    "https://blog.fal.ai/",
    "https://blog.fal.ai/tag/models/",
    "https://blog.fal.ai/author/team/",
    "https://ai.meta.com/research/",
    "https://runway.com/product",
    "https://runway.com.evil.test/research/gen-1",
    "https://higgsfield.ai/create",
    "https://suno.com/song/123",
    "https://seed.bytedance.com/en/",
    "https://bytedance.com/en/blog/new-model",
    "https://modelcontextprotocol.io/docs/introduction",
    "https://blog.modelcontextprotocol.io/posts/",
    "https://github.com/some-user/some-repo/releases/tag/v1",
    "https://secret@x.ai/news/new-model",
])
def test_scout_publisher_roots_do_not_trust_arbitrary_pages_or_subdomains(url):
    assert not url_fetcher.is_primary_announcement(url)


@pytest.mark.asyncio
async def test_new_primary_provider_without_date_still_waits_for_a_source_date(
    monkeypatch, editorial_session,
):
    from sqlalchemy import select
    from tce.models.news import NewsItem
    from tce.news import discovery
    from tce.settings import settings

    workspace = uuid.UUID("3e8c3f9c-0213-57cd-ab30-173d5700090f")
    monkeypatch.setattr(settings, "editor_default_workspace_id", str(workspace))
    monkeypatch.setattr(settings, "owner_workspace_ids", "")
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ])
    client_type = httpx.AsyncClient
    monkeypatch.setattr(url_fetcher.httpx, "AsyncClient", lambda **kw: client_type(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, text=(
                "<title>AI now drafts follow-up emails after client meetings</title>"
                "<main>An AI assistant can prepare client follow-up email drafts.</main>"
            ), headers={"content-type": "text/html"},
        )),
    ))
    result = await discovery.check_one(
        editorial_session, workspace, url="https://x.ai/news/assistant-release",
        fetch_text=url_fetcher.fetch_url_text, now=datetime(2026, 10, 20, 12),
    )
    item = (await editorial_session.execute(select(NewsItem))).scalars().one()
    assert result["item_id"] == str(item.id)
    assert item.editorial_meta["primary_source_verified"] is True
    assert item.published_at is None
    assert item.editorial_meta["appraisal_retry"]["state"] == "needs_source_date"


@pytest.mark.asyncio
async def test_secondary_story_resolves_and_fetches_primary_before_verification(monkeypatch):
    calls = []
    async def fake(url, **kwargs):
        calls.append(url)
        if "simonwillison" in url:
            return {"status": "ok", "url": url, "title": "Claude Haiku 5.5",
                    "outbound_links": ["https://www.anthropic.com/claude-haiku-5-5"],
                    "source_verified": False}
        return {"status": "ok", "url": url, "title": "Claude Haiku 5.5",
                "body_text": "Official release", "published_at": datetime(2026, 10, 7),
                "source_verified": True, "primary_url": url}
    monkeypatch.setattr(url_fetcher, "fetch_url_text", fake)
    result = await url_fetcher.resolve_primary_announcement("https://simonwillison.net/2026/Oct/7/haiku/")
    assert result["source_verified"] is True
    assert result["primary_url"] == "https://www.anthropic.com/claude-haiku-5-5"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_ambiguous_primary_links_do_not_become_verified(monkeypatch):
    async def fake(url, **kwargs):
        return {"status": "ok", "url": url, "source_verified": False,
                "outbound_links": ["https://openai.com/index/one", "https://openai.com/index/two"]}
    monkeypatch.setattr(url_fetcher, "fetch_url_text", fake)
    result = await url_fetcher.resolve_primary_announcement("https://simonwillison.net/roundup")
    assert result["status"] == "primary_unresolved"
    assert result["source_verified"] is False


@pytest.mark.asyncio
async def test_public_news_fetch_refuses_private_dns_before_request(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ])
    calls = []
    client_type = httpx.AsyncClient
    monkeypatch.setattr(url_fetcher.httpx, "AsyncClient", lambda **kw: client_type(
        transport=httpx.MockTransport(lambda request: calls.append(request)),
    ))
    result = await url_fetcher.fetch_url_text("https://looks-public.example/news", public_only=True)
    assert result["status"] == "unsafe_url"
    assert calls == []


@pytest.mark.asyncio
async def test_public_news_fetch_pins_address_and_checks_redirects(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
    ])
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8200/private"})

    client_type = httpx.AsyncClient
    monkeypatch.setattr(url_fetcher.httpx, "AsyncClient", lambda **kw: client_type(
        transport=httpx.MockTransport(transport),
    ))
    result = await url_fetcher.fetch_url_text("https://public.example/news", public_only=True)
    assert result["status"] == "unsafe_url"
    assert len(calls) == 1
    assert calls[0].url.host == "93.184.216.34"
    assert calls[0].headers["host"] == "public.example"
    assert calls[0].extensions["sni_hostname"] == "public.example"
