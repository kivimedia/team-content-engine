"""TCE_SCHEDULE_WORKSPACES lives in .env for scripts/tce-schedule-tick.sh.

Settings forbids unknown TCE_ keys, so an undeclared one crash-looped the API on
5-Oct-2026 (pydantic extra_forbidden). The app must accept the line.
"""
from tce.settings import Settings


def test_schedule_workspaces_line_does_not_crash_settings(monkeypatch):
    monkeypatch.setenv("TCE_SCHEDULE_WORKSPACES", "3e8c3f9c-0213-57cd-ab30-173d5700090f,40c0f179-7d5e-4397-b4de-b0b2f3e96fc2")
    s = Settings()
    assert "40c0f179" in s.schedule_workspaces
