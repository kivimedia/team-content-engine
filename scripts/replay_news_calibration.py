"""Offline discovery replay. No network, database, or paid/subscription model call."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

from tce.news.matcher import match_item

DEFAULT = Path(__file__).resolve().parents[1] / "tests/fixtures/news/owner_calibration_20.json"


def replay(path: Path = DEFAULT) -> dict:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    anchors = [
        SimpleNamespace(id=uuid.uuid5(uuid.NAMESPACE_DNS, term), kind="vendor",
                        term=term, weight=1)
        for term in ("anthropic", "openai", "google workspace", "dubsado")
    ]
    rows = []
    for story in fixture["stories"]:
        result = match_item(title=story["title"], summary=story.get("summary"),
                            source_vendor=story.get("source_vendor"),
                            anchors=anchors, business_relevance=True)
        rows.append({"id": story["id"], "expected_match": story["expected_match"],
                     "actual_match": result.matched, "reason": result.reason,
                     "pass": result.matched == story["expected_match"],
                     "editorial_label": story["editorial_label"]})
    return {"label": fixture["label"], "scope": fixture["scope"],
            "total": len(rows), "passed": sum(row["pass"] for row in rows),
            "false_negatives": [row["id"] for row in rows
                                if row["expected_match"] and not row["actual_match"]],
            "false_positives": [row["id"] for row in rows
                                if not row["expected_match"] and row["actual_match"]],
            "results": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = replay(args.fixture)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    raise SystemExit(0 if result["passed"] == result["total"] else 1)
