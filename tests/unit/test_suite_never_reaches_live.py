"""The suite can never reach the live box (integrated review, 5-Oct).

On the VPS the settings defaults ARE the live services: the default database URL is
the live TCE database on this box, production_self_url is the
live API on :8200, and production_skills_dir is /home/ziv/skills, whose schedule-*
CLIs post to the owner's real accounts. Before this, only a hand-sourced env file
kept a pytest run off them. tests/conftest.py now points every one of them at a dead
address before any tce module is imported, and refuses to run against the live
database even when it is exported explicitly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import conftest


def test_the_settings_the_suite_runs_with_reach_nothing_live():
    from tce.settings import settings

    assert not conftest.is_live_database(settings.database_url), settings.database_url
    assert ":8200" not in settings.production_self_url
    assert settings.production_skills_dir != "/home/ziv/skills"
    assert not Path(settings.production_skills_dir).exists()
    assert ":8300" not in settings.cutsense_api_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://tce:tce@localhost:5432/tce",
        "postgresql+asyncpg://tce:other@127.0.0.1/tce",
        "postgresql://tce:x@localhost:5432/tce?ssl=disable",
    ],
)
def test_the_live_database_url_is_recognised(url):
    assert conftest.is_live_database(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://nobody:nobody@127.0.0.1:1/tce_test_never",
        "sqlite+aiosqlite:///:memory:",
        "postgresql+asyncpg://tce:tce@localhost:5432/tce_test",
    ],
)
def test_test_databases_are_not_the_live_one(url):
    assert not conftest.is_live_database(url)