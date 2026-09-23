"""Tests for core.py: parsing, config resolution, and CLI command building."""

import os
import subprocess
from unittest.mock import patch, MagicMock

import pytest

import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from core import parse_messages, get_config, list_conversations, fetch_transcript


class TestParseMessages:
    def test_extracts_text_content(self, parsed_transcript):
        rows = parse_messages("sess-1", parsed_transcript)
        assert len(rows) == 4
        assert rows[0]["role"] == "user"
        assert rows[1]["role"] == "assistant"

    def test_message_ids_include_session_and_index(self, parsed_transcript):
        rows = parse_messages("sess-1", parsed_transcript)
        assert rows[0]["message_id"] == "sess-1:0"
        assert rows[3]["message_id"] == "sess-1:3"

    def test_strips_system_reminders_not_in_content(self, parsed_transcript):
        # parse_messages does NOT strip system reminders — it preserves raw text
        rows = parse_messages("sess-1", parsed_transcript)
        assert "system-reminder" in rows[0]["content"]

    def test_extracts_tool_result_text(self, parsed_transcript):
        # Message 3 (assistant) has a tool_result with text "Query returned 1500"
        rows = parse_messages("sess-1", parsed_transcript)
        assert "Query returned 1500" in rows[3]["content"]

    def test_empty_transcript_returns_empty(self):
        assert parse_messages("sess-1", []) == []

    def test_raw_content_is_json(self, parsed_transcript):
        rows = parse_messages("sess-1", parsed_transcript)
        import json
        for row in rows:
            json.loads(row["raw_content"])  # should not raise


class TestGetConfig:
    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            db, sc = get_config()
            assert db == "DEMOS"
            assert sc == "AGENT_MEMORY"

    def test_env_vars_override_defaults(self):
        with patch.dict(os.environ, {"SNOWFLAKE_DATABASE": "MY_DB", "SNOWFLAKE_SCHEMA": "MY_SCHEMA"}):
            db, sc = get_config()
            assert db == "MY_DB"
            assert sc == "MY_SCHEMA"

    def test_args_override_env_vars(self):
        with patch.dict(os.environ, {"SNOWFLAKE_DATABASE": "ENV_DB", "SNOWFLAKE_SCHEMA": "ENV_SCHEMA"}):
            db, sc = get_config(database="ARG_DB", schema="ARG_SCHEMA")
            assert db == "ARG_DB"
            assert sc == "ARG_SCHEMA"


class TestListConversations:
    @patch("core.subprocess.run")
    def test_parses_csv_output(self, mock_run, conversations_csv):
        mock_run.return_value = MagicMock(stdout=conversations_csv, returncode=0)
        result = list_conversations()
        assert len(result) == 3
        assert result[0]["id"] == "2048721639110"
        assert result[0]["title"] == "Finance Streamlit App Ideas"

    @patch("core.subprocess.run")
    def test_after_flag_in_command(self, mock_run, conversations_csv):
        mock_run.return_value = MagicMock(stdout=conversations_csv, returncode=0)
        list_conversations(after="2026-09-19 18:21:57.000")
        cmd = mock_run.call_args[0][0]
        assert "--after" in cmd
        assert "2026-09-19 18:21:57.000" in cmd
        # positional query "" must come after --after
        assert cmd.index("--after") < cmd.index("")

    @patch("core.subprocess.run")
    def test_connection_flag_in_command(self, mock_run, conversations_csv):
        mock_run.return_value = MagicMock(stdout=conversations_csv, returncode=0)
        list_conversations(connection_name="my-conn")
        cmd = mock_run.call_args[0][0]
        assert "--connection" in cmd
        assert "my-conn" in cmd

    @patch("core.subprocess.run")
    def test_no_after_when_none(self, mock_run, conversations_csv):
        mock_run.return_value = MagicMock(stdout=conversations_csv, returncode=0)
        list_conversations()
        cmd = mock_run.call_args[0][0]
        assert "--after" not in cmd


class TestFetchTranscript:
    @patch("core.subprocess.run")
    def test_parses_ndjson(self, mock_run, transcript_short):
        mock_run.return_value = MagicMock(stdout=transcript_short, returncode=0)
        result = fetch_transcript("sess-1")
        assert len(result) == 4
        assert result[0]["role"] == "user"

    @patch("core.subprocess.run")
    def test_connection_flag_passed(self, mock_run, transcript_short):
        mock_run.return_value = MagicMock(stdout=transcript_short, returncode=0)
        fetch_transcript("sess-1", connection_name="my-conn")
        cmd = mock_run.call_args[0][0]
        assert "--connection" in cmd
        assert "my-conn" in cmd
