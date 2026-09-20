"""Incremental load: fetch only new/updated conversations since last load."""

import json
from datetime import datetime, timezone

import pandas as pd

from core import (
    ensure_search_services,
    ensure_tables,
    fetch_transcript,
    get_snowflake_connection,
    list_conversations,
    parse_messages,
)

from snowflake.connector.pandas_tools import write_pandas


def incremental_load():
    print("Connecting to Snowflake...")
    conn = get_snowflake_connection()
    ensure_tables(conn)
    cur = conn.cursor()

    # Read watermark: latest LAST_LOADED_AT across all conversations
    cur.execute("SELECT MAX(LAST_LOADED_AT)::VARCHAR FROM DEMOS.AGENT_MEMORY.CONVERSATIONS")
    row = cur.fetchone()
    watermark = row[0] if row and row[0] else None

    if watermark:
        print(f"Watermark: {watermark}")
    else:
        print("No watermark found — table is empty. Run full_load.py first, or this will load everything.")

    # Fetch conversations updated after watermark
    conversations = list_conversations(after=watermark)
    if not conversations:
        print("No new or updated conversations. Nothing to do.")
        cur.close()
        conn.close()
        return

    print(f"Found {len(conversations)} new/updated conversations")

    # Get existing max turn_index only for sessions in the delta
    delta_sids = [c["id"] for c in conversations]
    placeholders = ",".join(["%s"] * len(delta_sids))
    cur.execute(f"""
        SELECT SESSION_ID, MAX(TURN_INDEX) 
        FROM DEMOS.AGENT_MEMORY.MESSAGES 
        WHERE SESSION_ID IN ({placeholders})
        GROUP BY SESSION_ID
    """, delta_sids)
    existing_max_turn = {r[0]: r[1] for r in cur.fetchall()}

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    errors = 0
    new_msg_rows = []

    for i, conv in enumerate(conversations):
        sid = conv["id"]
        title = conv.get("title", "")
        source = conv.get("source", "")
        updated = conv.get("updated", "")

        print(f"  [{i+1}/{len(conversations)}] {sid}: {title[:60]}...", end=" ", flush=True)

        try:
            transcript = fetch_transcript(sid)
        except Exception as e:
            print(f"SKIP (fetch error: {e})")
            errors += 1
            continue

        if not transcript:
            print("SKIP (empty transcript)")
            errors += 1
            continue

        messages = parse_messages(sid, transcript)
        message_count = len(messages)

        # MERGE conversation (upsert metadata + transcript)
        cur.execute(
            """
            MERGE INTO DEMOS.AGENT_MEMORY.CONVERSATIONS tgt
            USING (
                SELECT %s AS SESSION_ID, %s AS TITLE, %s AS SOURCE,
                       TRY_TO_TIMESTAMP_NTZ(%s) AS UPDATED,
                       %s::TIMESTAMP_NTZ AS NOW,
                       %s AS MSG_COUNT,
                       PARSE_JSON(%s) AS TRANSCRIPT
            ) src
            ON tgt.SESSION_ID = src.SESSION_ID
            WHEN MATCHED THEN UPDATE SET
                tgt.TITLE = src.TITLE,
                tgt.LAST_MESSAGE_AT = src.UPDATED,
                tgt.LAST_LOADED_AT = src.NOW,
                tgt.MESSAGE_COUNT = src.MSG_COUNT,
                tgt.TRANSCRIPT = src.TRANSCRIPT
            WHEN NOT MATCHED THEN INSERT
                (SESSION_ID, TITLE, SOURCE, STARTED_AT, LAST_MESSAGE_AT,
                 LAST_LOADED_AT, MESSAGE_COUNT, TRANSCRIPT)
            VALUES
                (src.SESSION_ID, src.TITLE, src.SOURCE, src.UPDATED, src.UPDATED,
                 src.NOW, src.MSG_COUNT, src.TRANSCRIPT)
            """,
            (sid, title, source, updated, now, message_count,
             json.dumps(transcript, default=str)),
        )

        # Collect only new messages (turn_index beyond what's already loaded)
        max_existing = existing_max_turn.get(sid, -1)
        new_messages = [m for m in messages if m["turn_index"] > max_existing]

        for m in new_messages:
            new_msg_rows.append({
                "MESSAGE_ID": m["message_id"],
                "SESSION_ID": m["session_id"],
                "TURN_INDEX": m["turn_index"],
                "ROLE": m["role"],
                "CONTENT": m["content"],
                "RAW_CONTENT": m["raw_content"],
                "CREATED_AT": updated or None,
            })

        appended = len(new_messages)
        status = "NEW" if max_existing == -1 else f"+{appended} messages"
        print(f"OK ({status})")

    # Bulk insert new messages
    if new_msg_rows:
        print(f"Inserting {len(new_msg_rows)} new message rows...", flush=True)
        df_msg = pd.DataFrame(new_msg_rows)
        write_pandas(conn, df_msg, "MESSAGES", database="DEMOS", schema="AGENT_MEMORY")

    loaded = len(conversations) - errors
    print(f"\nProcessed {loaded} conversations ({errors} skipped)")

    # Re-summarize stale summaries
    print("Updating stale summaries via AI_COMPLETE...")
    cur.execute("""
        UPDATE DEMOS.AGENT_MEMORY.CONVERSATIONS
        SET SUMMARY = AI_COMPLETE(
                'llama3.1-70b',
                'Summarize this Cortex Code conversation in 2-3 sentences. Focus on what was discussed and accomplished:\\n\\n' ||
                TRANSCRIPT::VARCHAR
            ),
            SUMMARY_UPDATED_AT = CURRENT_TIMESTAMP()
        WHERE SUMMARY IS NULL
           OR LAST_MESSAGE_AT > SUMMARY_UPDATED_AT
    """)
    summary_count = cur.rowcount
    print(f"Updated {summary_count} summaries")

    # Refresh Cortex Search services (picks up new/updated data)
    print("Refreshing Cortex Search services...", flush=True)
    ensure_search_services(conn)
    print("  Search services refreshed")

    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    incremental_load()
