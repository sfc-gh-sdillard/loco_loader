"""Full load: extract all CoCo conversations and load from scratch."""

import argparse
import json
from datetime import datetime, timezone

import pandas as pd
from snowflake.snowpark import Session

from core import (
    add_common_args,
    ensure_search_services,
    ensure_tables,
    fetch_transcript,
    get_config,
    get_snowflake_connection,
    list_conversations,
    parse_messages,
)


def full_load(connection_name=None, database=None, schema=None):
    db, sc = get_config(database, schema)
    fqn = f"{db}.{sc}"

    print("Connecting to Snowflake...")
    conn = get_snowflake_connection(connection_name)
    ensure_tables(conn, fqn)
    cur = conn.cursor()

    print("Fetching conversation list...")
    conversations = list_conversations(connection_name=connection_name)
    print(f"Found {len(conversations)} conversations")

    # Truncate both tables for clean reload
    cur.execute(f"TRUNCATE TABLE IF EXISTS {fqn}.MESSAGES")
    cur.execute(f"TRUNCATE TABLE IF EXISTS {fqn}.CONVERSATIONS")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conv_rows = []
    msg_rows = []
    errors = 0

    # Phase 1: Extract all transcripts locally
    for i, conv in enumerate(conversations):
        sid = conv["id"]
        title = conv.get("title", "")
        source = conv.get("source", "")
        updated = conv.get("updated", "")

        print(f"  [{i+1}/{len(conversations)}] {sid}: {title[:60]}...", end=" ", flush=True)

        try:
            transcript = fetch_transcript(sid, connection_name=connection_name)
        except Exception as e:
            print(f"SKIP (fetch error: {e})")
            errors += 1
            continue

        if not transcript:
            print("SKIP (empty transcript)")
            errors += 1
            continue

        messages = parse_messages(sid, transcript)

        conv_rows.append((sid, title, source, updated, updated, now, len(messages),
                          json.dumps(transcript, default=str)))

        for m in messages:
            msg_rows.append((m["message_id"], m["session_id"], m["turn_index"],
                             m["role"], m["content"], m["raw_content"], updated))

        print(f"OK ({len(messages)} messages)")

    print(f"\nExtracted {len(conv_rows)} conversations, {len(msg_rows)} messages ({errors} skipped)")

    # Phase 2: Bulk insert conversations
    print("Loading conversations...", flush=True)
    cur.executemany(f"""
        INSERT INTO {fqn}.CONVERSATIONS
            (SESSION_ID, TITLE, SOURCE, STARTED_AT, LAST_MESSAGE_AT,
             LAST_LOADED_AT, MESSAGE_COUNT, TRANSCRIPT)
        SELECT %s, %s, %s, TRY_TO_TIMESTAMP_NTZ(%s), TRY_TO_TIMESTAMP_NTZ(%s),
               %s::TIMESTAMP_NTZ, %s, PARSE_JSON(%s)
    """, conv_rows)
    print(f"  Loaded {len(conv_rows)} conversation rows")

    # Phase 3: Bulk insert messages via Snowpark
    print("Loading messages...", flush=True)
    session = Session.builder.configs({"connection": conn}).create()
    df_msg = pd.DataFrame(msg_rows, columns=[
        "MESSAGE_ID", "SESSION_ID", "TURN_INDEX", "ROLE", "CONTENT", "RAW_CONTENT", "CREATED_AT"
    ])
    session.write_pandas(df_msg, "MESSAGES", database=db, schema=sc)
    print(f"  Loaded {len(msg_rows)} message rows")

    # Phase 4: Generate summaries
    print("Generating summaries via AI_COMPLETE...", flush=True)
    cur.execute(f"""
        UPDATE {fqn}.CONVERSATIONS
        SET SUMMARY = AI_COMPLETE(
                'llama3.1-8b',
                'summarize this cortex code conversation. Focus on what was discussed and accomplished. No preamble about the response. Only return the summary:\\n\\n' ||
                TRANSCRIPT::VARCHAR
            ),
            SUMMARY_UPDATED_AT = CURRENT_TIMESTAMP()
        WHERE SUMMARY IS NULL
    """)
    summary_count = cur.rowcount
    print(f"Generated {summary_count} summaries")

    # Phase 5: Refresh Cortex Search services
    print("Refreshing Cortex Search services...", flush=True)
    ensure_search_services(conn, fqn)
    print("  Search services created/refreshed")

    cur.close()
    conn.close()
    print("Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Full load of CoCo conversations")
    add_common_args(parser)
    args = parser.parse_args()
    full_load(args.snowflake_connection, args.database, args.schema)
