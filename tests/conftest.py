import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conversations_csv():
    return (FIXTURES / "conversations.csv").read_text()


@pytest.fixture
def transcript_short():
    return (FIXTURES / "transcript_short.ndjson").read_text()


@pytest.fixture
def transcript_malformed():
    return (FIXTURES / "transcript_malformed.ndjson").read_text()


@pytest.fixture
def parsed_transcript():
    """The transcript_short fixture parsed into a list of dicts (as fetch_transcript returns)."""
    lines = (FIXTURES / "transcript_short.ndjson").read_text().strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = ("2026-09-19 18:21:57.000",)
    cur.fetchall.return_value = []
    cur.rowcount = 0
    conn.cursor.return_value = cur
    return conn, cur
