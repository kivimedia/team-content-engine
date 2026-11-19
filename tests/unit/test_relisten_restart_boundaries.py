"""Restart evidence at an opening and a later cut boundary."""

from tce.production import relisten
from tce.production.retakes import plan_edit


def words(tokens):
    return [dict(text=t, start_s=s, end_s=e, precision="word") for t, s, e in tokens]


FIRST = words(
    [
        ("Your", 3.47, 4.01),
        ("childhood", 4.01, 7.11),
        ("origin", 7.11, 7.73),
        ("story", 7.73, 8.33),
        ("is", 8.33, 9.03),
        ("making", 9.03, 9.37),
        ("buyers", 9.37, 9.91),
        ("trust", 9.91, 10.27),
        ("you", 10.27, 10.53),
        ("less.", 10.53, 10.89),
    ]
)
REGIONS = [(3.45, 4.48), (5.80, 8.33), (8.38, 9.02), (9.05, 10.91)]


def hearing(win, tokens, *, start=None):
    base = win.start if start is None else start
    return {
        "language": "en",
        "language_probability": 0.99,
        "words": [{"word": w, "start": s - base, "end": e - base} for w, s, e in tokens],
    }


def test_opening_exposes_the_partial_and_full_take_with_the_source_timings():
    (win,) = relisten.restart_windows(FIRST, REGIONS)
    assert (win.first, win.last) == (0, 3)
    left = hearing(win, [("your", 3.47, 4.0), ("child", 4.0, 4.44)])
    right = hearing(
        win,
        [
            ("your", 5.85, 6.60),
            ("childhood", 6.60, 7.14),
            ("origin", 7.14, 7.71),
            ("story", 7.71, 8.33),
        ],
        start=win.split_s,
    )
    changed, report = relisten.merge_restarts(FIRST, [win], [(left, right)], REGIONS)
    assert [w["text"].lower() for w in changed[:6]] == [
        "your",
        "child",
        "your",
        "childhood",
        "origin",
        "story",
    ]
    assert changed[2]["start_s"] >= 5.8
    assert changed[6:] == FIRST[4:]
    assert report[0]["result"] == "more words"
    plan = plan_edit(changed, [])
    assert plan["kept_text"].startswith("Your childhood origin story")
    assert not any(a <= 4.10 <= b for a, b in plan["keep"])
    assert any(a <= 5.90 <= b for a, b in plan["keep"])
    # A reviewer can instead choose the earlier take; dropping the complete one must
    # not also drop the first. Source-clock overrides remain authoritative.
    swapped = plan_edit(changed, [], overrides={"cut": [[5.80, 7.15]]})
    assert swapped["kept_text"].lower().startswith("your child origin")


def test_later_join_and_wind_guard_and_preserve_uncertain_original_words():
    seq = words(
        [
            ("He", 0, 0.2),
            ("asks.", 0.2, 0.5),
            ("Many", 14.23, 14.39),
            ("owners", 14.39, 14.73),
            ("I", 14.73, 14.95),
            ("talked", 14.95, 15.47),
            ("to", 15.47, 18.29),
            ("skip", 18.29, 18.61),
            ("this", 18.61, 18.89),
            ("number.", 18.89, 19.31),
        ]
    )
    speech = [(0, 0.5), (14.23, 15.9), (16.9, 19.31)]
    (win,) = relisten.restart_windows(seq, speech)
    assert (win.first, win.last) == (2, 8)
    assert not relisten.restart_windows(seq, [(14.23, 19.31)])
    # A longer transcription that drops a meaningful word or inserts unrelated content cannot
    # displace the original, even if most of the original words match in order.
    got = hearing(
        win,
        [
            ("Many", 14.23, 14.39),
            ("owners", 14.39, 14.73),
            ("I", 14.73, 14.95),
            ("never", 14.95, 15.47),
            ("talked", 15.48, 15.83),
            ("to", 16.9, 17.1),
            ("skip", 18.29, 18.61),
            ("this", 18.61, 18.89),
        ],
    )
    out, _ = relisten.merge_restarts(seq, [win], [(got, got)], speech)
    assert out == seq
    assert relisten.merge_restarts(seq, [win], [(None, None)], speech)[0] == seq


def test_disagreement_flags_both_audible_takes_without_changing_the_words():
    from tce.production import qc

    (win,) = relisten.restart_windows(FIRST, REGIONS)
    left = hearing(win, [("your", 3.47, 3.73), ("childhood", 3.76, 4.35), ("seemed", 4.35, 4.48)])
    right = hearing(
        win,
        [
            ("your", 5.85, 6.59),
            ("childhood", 6.60, 7.14),
            ("origin", 7.14, 7.71),
            ("story", 7.71, 8.33),
        ],
        start=win.split_s,
    )
    result, report = relisten.merge_restarts(FIRST, [win], [(left, right)], REGIONS)
    assert result == FIRST
    assert len(report) == 1 and report[0]["result"] == "restart needs review"
    info = {"restart_flags": report}
    original = [[3.4, 4.48], [5.8, 8.4]]
    outcome = relisten.check_restart_flags(info, original)
    assert qc.decide({"retakes": outcome}, round_no=0)["state"] == "held"
    assert "both takes still play" in outcome["problems"][0]["detail"]
    # Keeping only the second take resolves it automatically. Approving both covers
    # the exact heard sequence, including after unrelated video changes.
    assert relisten.check_restart_flags(info, [[5.8, 8.4]])["state"] == "pass"
    accepted = {**info, "accepted_restart_flags": [outcome["problems"][0]["restart_key"]]}
    assert relisten.check_restart_flags(accepted, original + [[9.4, 10.2]])["state"] == "pass"
    assert relisten.check_restart_flags(accepted, [[3.4, 4.42], [5.8, 8.4]])["state"] == "fail"


def test_shared_short_greeting_or_silence_does_not_create_a_restart_hold():
    assert relisten.check_restart_flags({}, [[0, 1]])["state"] == "pass"
    left = words([("I", 0, 0.1), ("am", 0.2, 0.3), ("here", 0.4, 0.5)])
    right = words([("I", 0.8, 0.9), ("am", 1, 1.2), ("ready", 1.3, 1.4)])
    assert relisten._restart_flag(left, right, 0.65) is None


async def test_releasing_the_held_render_remembers_accepted_source_joins(monkeypatch):
    import uuid
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from tce.api.routers import production

    ws, upload_id = uuid.uuid4(), uuid.uuid4()
    row = SimpleNamespace(
        id=upload_id,
        edit_plan={"second_listen": {"restart_flags": [{"split_s": 4.5}]}},
        render_ref="one",
        qc={
            "state": "held",
            "problems": [
                {"kind": "restart_uncertain", "restart_key": "verified-join"},
                {"kind": "gap"},
            ],
        },
    )
    db = SimpleNamespace(add=Mock(), commit=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(production, "_upload", AsyncMock(return_value=row))
    monkeypatch.setattr(production.library_service, "qc_hold", lambda _: "both takes still play")
    monkeypatch.setattr(production, "start_draft_posts", lambda *args: None)
    monkeypatch.setattr(production, "upload_json", lambda _: {"state": row.qc["state"]})
    assert await production.release_hold(upload_id, ws, db) == {"state": "released"}
    assert row.edit_plan["second_listen"]["accepted_restart_flags"] == ["verified-join"]
    assert row.edit_plan["second_listen"]["restart_flags"] == [{"split_s": 4.5}]


def test_angel_can_remove_the_second_i_see_this_a_lot_take():
    """Even a preceding AI review marked the first take for removal."""
    first = ["I", "see", "this", "a", "lot"]
    tokens = first + first + ["when", "I", "coach", "sales", "conversations."]
    source = words([(t, i * 0.4, i * 0.4 + 0.30) for i, t in enumerate(tokens)])
    source[0]["confirmed_restart"] = {"tokens": [t.lower() for t in first + first]}
    review = [{"start": 0.0, "end": 1.90, "kind": "retake", "keeper_start": 2.0}]
    chosen = plan_edit(source, [], removals=review, overrides={"cut": [[2.0, 3.90]]})
    assert chosen["kept_text"].startswith("I see this a lot when I coach")
    assert any(a <= 0.45 <= b for a, b in chosen["keep"])
    assert not any(a <= 2.45 <= b for a, b in chosen["keep"])
