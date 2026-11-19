import pytest

from tce.production import qc


@pytest.mark.asyncio
async def test_reviewing_decoded_caption_frames_requires_the_visible_phrase():
    words = {
        "cues": [
            {"start": i, "end": i + 0.9, "text": s}
            for i, s in enumerate(
                ["Before you start", "choose another take", "keep the whole word"]
            )
        ]
    }

    async def read(path, at, language, region):
        return words["cues"][int(at)]["text"] if at < 1 else "Before you start"

    outcome = await qc.sample_caption_frames("unused", words, "en", reader=read)
    assert outcome["state"] == "fail"
    assert outcome["samples"] == 3


@pytest.mark.asyncio
async def test_decoding_unavailable_never_proves_visible_captions():
    async def unavailable(*args, **kwargs):
        return None

    outcome = await qc.sample_caption_frames(
        "unused", {"cues": [{"start": 0, "end": 1, "text": "all words"}]}, "en", reader=unavailable
    )
    assert outcome["state"] == "skipped"


def test_a_partial_new_preview_does_not_get_a_pass_badge():
    result = qc.decide(
        {
            "captions": {
                "state": "pass",
                "problems": [],
                "playback_state": "pass",
                "frames": {"state": "skipped"},
            }
        },
        round_no=0,
    )
    assert result["state"] == "report"
