"""Rendered captions and independent audio from the in-memory render used by flow tests."""

import uuid

from tce.api.routers import production as prod


def simulate_delivery(monkeypatch):
    rendered = {}

    def capture(row):
        row.render_ref = uuid.uuid4().hex[:16]
        row.rendered_keep = prod.frame_keep(row.edit_plan["keep"])
        words = prod.wordbox.on_edit_timeline(row.edit_plan.get("words") or [], row.rendered_keep)
        rendered[row.render_ref] = {
            "render_ref": row.render_ref,
            "duration": sum(b - a for a, b in row.rendered_keep),
            "keep": row.rendered_keep,
            "captions": {"mode": "wordbox", "words": words, "boxes": words},
            "heard": [dict(w) for w in words],
            "visible": {("caption", round((w["start"] + w["end"]) / 2, 2)): w["text"] for w in words},
            "levels": [-120.0] * (round(sum(b - a for a, b in row.rendered_keep) * 100) + 1),
        }

    async def read(row, ws, *, outcomes):
        return rendered.get(row.render_ref, {})

    monkeypatch.setattr(prod, "_delivery_evidence", read)
    return capture
