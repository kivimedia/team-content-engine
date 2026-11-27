"""A UUID that reads as a number comes back as a UUID on the suite's SQLite (T-25692).

The models use Postgres UUID columns. On SQLite the declared type "UUID" has
NUMERIC affinity, so an id whose 32 hex characters are all digits and one "e"
was stored as a REAL and read back as a float. That broke a random test in
about one full run in a few. tests/conftest.py compiles the type as CHAR(32)
on SQLite; these checks hold it there.
"""

import uuid

from sqlalchemy import Column, MetaData, Table, create_engine, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.schema import CreateTable

NUMBER_LIKE = [
    uuid.UUID("12345678123441238123123456789e12"),  # digits and one "e": a REAL
    uuid.UUID("12345678123441238123123456789012"),  # all digits: an INTEGER
]


def _table():
    md = MetaData()
    return md, Table("t", md, Column("id", PG_UUID(as_uuid=True), primary_key=True))


def test_the_uuid_column_is_text_on_sqlite():
    md, t = _table()
    ddl = str(CreateTable(t).compile(create_engine("sqlite://")))
    assert "CHAR(32)" in ddl and " UUID " not in ddl


def test_a_number_like_uuid_round_trips_on_sqlite():
    md, t = _table()
    engine = create_engine("sqlite://")
    md.create_all(engine)
    with engine.begin() as conn:
        for u in NUMBER_LIKE:
            conn.execute(t.insert().values(id=u))
        back = sorted(conn.execute(select(t.c.id)).scalars().all())
    assert back == sorted(NUMBER_LIKE)
