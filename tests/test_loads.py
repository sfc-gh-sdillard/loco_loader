"""Integration tests for full_load.py and incremental_load.py — mocked Snowflake."""

import json
from unittest.mock import patch, MagicMock, call

import pytest

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))


class TestFullLoad:
    @patch("full_load.Session")
    @patch("full_load.get_snowflake_connection")
    @patch("full_load.fetch_transcript")
    @patch("full_load.list_conversations")
    @patch("full_load.ensure_tables")
    @patch("full_load.ensure_search_services")
    def test_full_load_writes_conversations_and_messages(
        self, mock_search, mock_tables, mock_list, mock_fetch, mock_conn_fn, MockSession,
        parsed_transcript, conversations_csv
    ):
        import csv, io
        convos = list(csv.DictReader(io.StringIO(conversations_csv)))
        mock_list.return_value = convos
        mock_fetch.return_value = parsed_transcript

        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 3
        conn.cursor.return_value = cur
        mock_conn_fn.return_value = conn

        session = MagicMock()
        MockSession.builder.configs.return_value.create.return_value = session

        from full_load import full_load
        full_load(connection_name="test-conn")

        # Conversations inserted via executemany
        cur.executemany.assert_called_once()
        sql = cur.executemany.call_args[0][0]
        assert "INSERT INTO" in sql
        assert "CONVERSATIONS" in sql
        rows = cur.executemany.call_args[0][1]
        assert len(rows) == 3

        # Messages inserted via Snowpark write_pandas
        session.write_pandas.assert_called_once()
        df = session.write_pandas.call_args[0][0]
        assert "MESSAGE_ID" in df.columns
        assert "SESSION_ID" in df.columns
        # 3 conversations * 4 messages each = 12
        assert len(df) == 12

    @patch("full_load.Session")
    @patch("full_load.get_snowflake_connection")
    @patch("full_load.fetch_transcript")
    @patch("full_load.list_conversations")
    @patch("full_load.ensure_tables")
    @patch("full_load.ensure_search_services")
    def test_skipped_transcripts_dont_break(
        self, mock_search, mock_tables, mock_list, mock_fetch, mock_conn_fn, MockSession,
        conversations_csv
    ):
        import csv, io
        convos = list(csv.DictReader(io.StringIO(conversations_csv)))
        mock_list.return_value = convos
        mock_fetch.side_effect = Exception("fetch error")

        conn = MagicMock()
        cur = MagicMock()
        cur.rowcount = 0
        conn.cursor.return_value = cur
        mock_conn_fn.return_value = conn

        session = MagicMock()
        MockSession.builder.configs.return_value.create.return_value = session

        from full_load import full_load
        full_load(connection_name="test-conn")

        # executemany called with empty list (no data to insert)
        if cur.executemany.called:
            rows = cur.executemany.call_args[0][1]
            assert len(rows) == 0
        # write_pandas called with empty DataFrame
        if session.write_pandas.called:
            df = session.write_pandas.call_args[0][0]
            assert len(df) == 0


class TestIncrementalLoad:
    @patch("incremental_load.Session")
    @patch("incremental_load.get_snowflake_connection")
    @patch("incremental_load.fetch_transcript")
    @patch("incremental_load.list_conversations")
    @patch("incremental_load.ensure_tables")
    @patch("incremental_load.ensure_search_services")
    def test_incremental_merges_conversations(
        self, mock_search, mock_tables, mock_list, mock_fetch, mock_conn_fn, MockSession,
        parsed_transcript, conversations_csv
    ):
        import csv, io
        convos = list(csv.DictReader(io.StringIO(conversations_csv)))
        mock_list.return_value = convos
        mock_fetch.return_value = parsed_transcript

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = ("2026-09-19 18:21:57.000",)
        cur.fetchall.return_value = []  # no existing messages
        cur.rowcount = 3
        conn.cursor.return_value = cur
        mock_conn_fn.return_value = conn

        session = MagicMock()
        MockSession.builder.configs.return_value.create.return_value = session

        from incremental_load import incremental_load
        incremental_load(connection_name="test-conn")

        # Should have MERGE calls for each conversation
        execute_calls = [c.args[0] for c in cur.execute.call_args_list if c.args]
        merge_calls = [sql for sql in execute_calls if "MERGE INTO" in sql]
        assert len(merge_calls) == 3

        # Messages written via Snowpark
        session.write_pandas.assert_called_once()
        df = session.write_pandas.call_args[0][0]
        assert len(df) == 12

    @patch("incremental_load.Session")
    @patch("incremental_load.get_snowflake_connection")
    @patch("incremental_load.list_conversations")
    @patch("incremental_load.ensure_tables")
    def test_no_new_conversations_exits_clean(
        self, mock_tables, mock_list, mock_conn_fn, MockSession,
    ):
        mock_list.return_value = []

        conn = MagicMock()
        cur = MagicMock()
        cur.fetchone.return_value = ("2026-09-19 18:21:57.000",)
        conn.cursor.return_value = cur
        mock_conn_fn.return_value = conn

        from incremental_load import incremental_load
        incremental_load(connection_name="test-conn")

        # No MERGE, no write_pandas
        execute_calls = [c.args[0] for c in cur.execute.call_args_list if c.args]
        merge_calls = [sql for sql in execute_calls if "MERGE" in sql]
        assert len(merge_calls) == 0
