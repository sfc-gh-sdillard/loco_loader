"""Shared extraction, parsing, and connection logic for CoCo history loading."""

import csv
import io
import json
import subprocess
from pathlib import Path
from cryptography.hazmat.primitives import serialization

import snowflake.connector

SCHEMA = "DEMOS.AGENT_MEMORY"
CONNECTION_NAME = "demo-account-admin-sdillard"
CONNECTIONS_TOML = Path.home() / ".snowflake" / "connections.toml"


def get_snowflake_connection():
    """Connect to Snowflake using the connections.toml config."""
    import tomllib
    with open(CONNECTIONS_TOML, "rb") as f:
        config = tomllib.load(f)

    conn_cfg = config[CONNECTION_NAME]
    key_path = Path(conn_cfg["private_key_path"]).expanduser()
    with open(key_path, "rb") as kf:
        private_key = serialization.load_pem_private_key(kf.read(), password=None)

    private_key_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    return snowflake.connector.connect(
        account=conn_cfg["account"],
        user=conn_cfg["user"],
        private_key=private_key_bytes,
        role=conn_cfg.get("role", "FREEPLAY"),
        warehouse=conn_cfg.get("warehouse", "COMPUTE_WH"),
        database="DEMOS",
        schema="AGENT_MEMORY",
    )


def list_conversations(after=None):
    """Call `cortex conversations search` and return list of dicts with id, updated, title, source."""
    cmd = ["cortex", "conversations", "search", "--limit", "1000", "--output", "csv", ""]
    if after:
        cmd.extend(["--after", after])

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    reader = csv.DictReader(io.StringIO(result.stdout))
    return list(reader)


def fetch_transcript(session_id):
    """Call `cortex conversations transcript` and return list of message dicts (NDJSON lines)."""
    cmd = ["cortex", "conversations", "transcript", "--output", "json", str(session_id)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)

    messages = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line:
            messages.append(json.loads(line))
    return messages


def parse_messages(session_id, transcript):
    """Parse a transcript (list of message dicts) into structured message rows.

    Returns list of dicts with keys: message_id, session_id, turn_index, role, content, raw_content.
    """
    rows = []
    for i, msg in enumerate(transcript):
        role = msg.get("role", "unknown")
        content_arr = msg.get("content", [])

        # Extract text content; for non-text items, store JSON representation
        text_parts = []
        for item in (content_arr if isinstance(content_arr, list) else []):
            if isinstance(item, dict):
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif item.get("type") == "tool_result":
                    tr = item.get("tool_result", {})
                    for sub in tr.get("content", []):
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            text_parts.append(sub.get("text", ""))
                else:
                    text_parts.append(json.dumps(item, default=str)[:500])
            elif isinstance(item, str):
                text_parts.append(item)

        content_text = "\n".join(text_parts) if text_parts else None

        rows.append({
            "message_id": f"{session_id}:{i}",
            "session_id": str(session_id),
            "turn_index": i,
            "role": role,
            "content": content_text,
            "raw_content": json.dumps(content_arr, default=str),
        })
    return rows


def ensure_tables(conn):
    """Create tables if they don't exist. Schema DEMOS.AGENT_MEMORY must already exist."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS DEMOS.AGENT_MEMORY.CONVERSATIONS (
            SESSION_ID         VARCHAR PRIMARY KEY,
            TITLE              VARCHAR,
            SOURCE             VARCHAR,
            STARTED_AT         TIMESTAMP_NTZ,
            LAST_MESSAGE_AT    TIMESTAMP_NTZ,
            LAST_LOADED_AT     TIMESTAMP_NTZ,
            MESSAGE_COUNT      INT,
            TRANSCRIPT         VARIANT,
            SUMMARY            VARCHAR,
            SUMMARY_UPDATED_AT TIMESTAMP_NTZ
        )
        COMMENT = 'Quick recall of CoCo conversations: lookup summaries, pull whole transcripts, or browse session metadata.'
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS DEMOS.AGENT_MEMORY.MESSAGES (
            MESSAGE_ID   VARCHAR PRIMARY KEY,
            SESSION_ID   VARCHAR,
            TURN_INDEX   INT,
            ROLE         VARCHAR,
            CONTENT      VARCHAR,
            RAW_CONTENT  VARIANT,
            CREATED_AT   TIMESTAMP_NTZ
        )
        COMMENT = 'Normalized CoCo conversation turns for searching specific messages, filtering by role, or finding conversations by keyword against RAW_CONTENT.'
    """)
    cur.close()


def ensure_search_services(conn):
    """Create or replace Cortex Search services. Call after data + summaries are loaded."""
    cur = conn.cursor()
    cur.execute("""
        CREATE OR REPLACE CORTEX SEARCH SERVICE DEMOS.AGENT_MEMORY.MESSAGES_SEARCH
          ON CONTENT
          ATTRIBUTES SESSION_ID, ROLE
          WAREHOUSE = COMPUTE_WH
          TARGET_LAG = '1 hour'
          COMMENT = 'Search CoCo conversation turns by content. Filter by SESSION_ID or ROLE.'
        AS (
          SELECT MESSAGE_ID, SESSION_ID, TURN_INDEX, ROLE, CONTENT, CREATED_AT
          FROM DEMOS.AGENT_MEMORY.MESSAGES
          WHERE CONTENT IS NOT NULL
        )
    """)
    cur.execute("""
        CREATE OR REPLACE CORTEX SEARCH SERVICE DEMOS.AGENT_MEMORY.CONVERSATIONS_SEARCH
          ON SUMMARY
          ATTRIBUTES TITLE, SOURCE
          WAREHOUSE = COMPUTE_WH
          TARGET_LAG = '1 hour'
          COMMENT = 'Search CoCo conversations by summary. Filter by TITLE or SOURCE.'
        AS (
          SELECT SESSION_ID, TITLE, SOURCE, SUMMARY, STARTED_AT, LAST_MESSAGE_AT, MESSAGE_COUNT
          FROM DEMOS.AGENT_MEMORY.CONVERSATIONS
          WHERE SUMMARY IS NOT NULL
        )
    """)
    cur.close()
