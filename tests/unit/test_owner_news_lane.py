"""The owner's week keeps room for one AI news idea (T-22611, 25-Nov).

Ziv, 18-Nov: "it didn't really have a good amount of topics related to code or related
to AI news ... we are not good at finding these." The builds half was fixed on 18-Nov
and proved on the week of 23 Nov. The news half was not: that week the best news idea
(Google Docs comparing Word files, 0.88, clear of the 0.70 floor and every gate) lost
the global ranking to coaching lessons and never reached his list. These tests pin the
net under the ranking: up to one news idea at or above the floor, displacing only the
weakest call idea, never a build idea, never a duplicate, never one under the floor.

Synthetic fixtures only; pure function, no database.
"""

from __future__ import annotations

from tce.editorial import selector


def _cand(key: str, title: str, score: float, *, news: bool = False, build: bool = False):
    kind = "news_item" if news else ("github_commit_group" if build else "fathom_meeting")
    return {
        "moment_ids": [key],
        "title": title,
        "lesson": "",
        "public_angle": "",
        "audience": "both",
        "gates": {"_primary_source_kind": kind},
        "citations_private": [{"source_kind": kind}],
        "rank_score": score,
        "news": {"story_weight": "small"} if news else None,
    }


def _set_aside(cand, code="not_selected_globally"):
    return {"moment_ids": cand["moment_ids"], "code": code, "title": cand["title"]}


CALLS = [_cand(f"c{i}", f"Coaching lesson {i}", 0.9 - 0.02 * i) for i in range(4)]
BUILD = _cand("b0", "Try a new AI agent on one account before every customer", 0.8, build=True)
DOCS = _cand("n0", "Google Docs now compares Word files directly", 0.8833, news=True)
SCRIPT = _cand("n1", "Gemini in Apps Script writes scripts for you", 0.72, news=True)
STUDIO = _cand("n2", "Workspace Studio flows can now be limited to drafts", 0.69, news=True)


def test_a_full_week_with_no_news_keeps_the_best_news_idea_above_the_floor():
    final = [*CALLS[:3], BUILD]
    rejected = [_set_aside(c) for c in (CALLS[3], DOCS, SCRIPT, STUDIO)]
    finalists = [*CALLS, BUILD, DOCS, SCRIPT, STUDIO]

    out, rej, report = selector.keep_news_lane(final, rejected, finalists, 4)

    titles = [c["title"] for c in out]
    assert DOCS["title"] in titles
    assert SCRIPT["title"] not in titles and STUDIO["title"] not in titles
    # The build idea is never the one that makes room; the weakest call pick is.
    assert BUILD["title"] in titles
    room = [r for r in rej if r["code"] == "lane_room"]
    assert [r["title"] for r in room] == [CALLS[2]["title"]]
    assert "news" in room[0]["reason"]
    assert report == {"slots": 1, "had": 0, "kept": 1}
    assert len(out) == 4


def test_a_week_that_already_holds_a_news_idea_is_left_alone():
    final = [*CALLS[:3], SCRIPT]
    rejected = [_set_aside(DOCS)]
    out, rej, report = selector.keep_news_lane(final, rejected, [*CALLS, DOCS, SCRIPT], 4)
    assert out == final and rej == rejected
    assert report["kept"] == 0 and report["had"] == 1


def test_news_under_the_floor_is_never_promoted():
    final = CALLS[:4]
    rejected = [_set_aside(STUDIO)]
    out, _, report = selector.keep_news_lane(final, rejected, [*CALLS, STUDIO], 4)
    assert [c["title"] for c in out] == [c["title"] for c in CALLS[:4]]
    assert report["kept"] == 0


def test_news_the_ranking_called_a_duplicate_or_a_repeat_is_never_promoted():
    final = CALLS[:4]
    dup = _set_aside(DOCS, code="duplicate_in_week")
    out, _, report = selector.keep_news_lane(final, [dup], [*CALLS, DOCS], 4)
    assert report["kept"] == 0 and DOCS["title"] not in [c["title"] for c in out]

    out, _, report = selector.keep_news_lane(
        final, [_set_aside(DOCS)], [*CALLS, DOCS], 4, is_repeat=lambda c: True
    )
    assert report["kept"] == 0


def test_a_week_of_only_builds_makes_no_room():
    builds = [
        _cand(f"b{i}", f"After an app update, check what reaches people {i}", 0.8, build=True)
        for i in range(2)
    ]
    out, _, report = selector.keep_news_lane(builds, [_set_aside(DOCS)], [*builds, DOCS], 2)
    assert [c["title"] for c in out] == [b["title"] for b in builds]
    assert report["kept"] == 0


def test_a_week_with_room_adds_the_news_idea_without_displacing_anyone():
    final = CALLS[:2]
    out, rej, report = selector.keep_news_lane(final, [_set_aside(DOCS)], [*CALLS, DOCS], 4)
    assert [c["title"] for c in out] == [CALLS[0]["title"], CALLS[1]["title"], DOCS["title"]]
    assert not [r for r in rej if r["code"] == "lane_room"]
    assert report["kept"] == 1
