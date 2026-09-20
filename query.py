"""Query CoCo conversation history from Snowflake."""

import argparse
import json

from snowflake.core import Root

from core import get_snowflake_connection

SCHEMA = "DEMOS.AGENT_MEMORY"
DB = "DEMOS"
SCHEMA_NAME = "AGENT_MEMORY"


def get_search_service(conn, service_name):
    root = Root(conn)
    return root.databases[DB].schemas[SCHEMA_NAME].cortex_search_services[service_name]


def cmd_conversations(args):
    conn = get_snowflake_connection()
    cur = conn.cursor()

    if args.search:
        svc = get_search_service(conn, "CONVERSATIONS_SEARCH")
        resp = svc.search(
            query=args.search,
            columns=["SESSION_ID", "TITLE", "SUMMARY", "MESSAGE_COUNT", "STARTED_AT"],
            limit=args.limit,
        )
        results = json.loads(resp.to_json()).get("results", [])
        for r in results:
            r = {k: v for k, v in r.items() if not k.startswith("@")}
            print_row(r, args.format)
    elif args.id:
        cur.execute(f"""
            SELECT SESSION_ID, TITLE, SOURCE, STARTED_AT, LAST_MESSAGE_AT, MESSAGE_COUNT, SUMMARY
            FROM {SCHEMA}.CONVERSATIONS WHERE SESSION_ID = %s
        """, (args.id,))
        for row in cur.fetchall():
            print_row(dict(zip([d[0] for d in cur.description], row)), args.format)
    else:
        cur.execute(f"""
            SELECT SESSION_ID, TITLE, MESSAGE_COUNT, STARTED_AT, LEFT(SUMMARY, 80) AS SUMMARY
            FROM {SCHEMA}.CONVERSATIONS ORDER BY STARTED_AT DESC LIMIT %s
        """, (args.limit,))
        rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        print_rows(rows, args.format)

    cur.close()
    conn.close()


def cmd_messages(args):
    conn = get_snowflake_connection()
    cur = conn.cursor()

    if args.search:
        svc = get_search_service(conn, "MESSAGES_SEARCH")

        filters = []
        if args.id:
            filters.append({"@eq": {"SESSION_ID": args.id}})
        if args.role:
            filters.append({"@eq": {"ROLE": args.role}})

        search_kwargs = {
            "query": args.search,
            "columns": ["MESSAGE_ID", "SESSION_ID", "TURN_INDEX", "ROLE", "CONTENT"],
            "limit": args.limit,
        }
        if len(filters) == 1:
            search_kwargs["filter"] = filters[0]
        elif len(filters) > 1:
            search_kwargs["filter"] = {"@and": filters}

        resp = svc.search(**search_kwargs)
        results = json.loads(resp.to_json()).get("results", [])
        for r in results:
            r = {k: v for k, v in r.items() if not k.startswith("@")}
            print_row(r, args.format)
    else:
        conditions = []
        params = []
        if args.id:
            conditions.append("SESSION_ID = %s")
            params.append(args.id)
        if args.role:
            conditions.append("ROLE = %s")
            params.append(args.role)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(args.limit)

        cur.execute(f"""
            SELECT MESSAGE_ID, SESSION_ID, TURN_INDEX, ROLE, LEFT(CONTENT, 200) AS CONTENT
            FROM {SCHEMA}.MESSAGES {where}
            ORDER BY SESSION_ID, TURN_INDEX
            LIMIT %s
        """, params)
        rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
        print_rows(rows, args.format)

    cur.close()
    conn.close()


def cmd_transcript(args):
    if not args.id:
        print("Error: --id is required for transcript")
        return

    conn = get_snowflake_connection()
    cur = conn.cursor()
    cur.execute(f"""
        SELECT ROLE, CONTENT FROM {SCHEMA}.MESSAGES
        WHERE SESSION_ID = %s AND CONTENT IS NOT NULL
        ORDER BY TURN_INDEX
    """, (args.id,))

    for role, content in cur.fetchall():
        tag = role.upper() if role else "?"
        print(f"[{tag}]: {content}\n")

    cur.close()
    conn.close()


def cmd_stats(args):
    conn = get_snowflake_connection()
    cur = conn.cursor()

    cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.CONVERSATIONS")
    conv_count = cur.fetchone()[0]

    cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.MESSAGES")
    msg_count = cur.fetchone()[0]

    cur.execute(f"SELECT MIN(STARTED_AT), MAX(LAST_MESSAGE_AT) FROM {SCHEMA}.CONVERSATIONS")
    row = cur.fetchone()

    cur.execute(f"""
        SELECT SESSION_ID, TITLE, MESSAGE_COUNT
        FROM {SCHEMA}.CONVERSATIONS
        ORDER BY MESSAGE_COUNT DESC LIMIT 5
    """)
    top = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]

    print(f"Conversations: {conv_count}")
    print(f"Messages:      {msg_count}")
    print(f"Date range:    {row[0]} to {row[1]}")
    print(f"\nTop sessions by message count:")
    for t in top:
        print(f"  {t['SESSION_ID']}  {t['MESSAGE_COUNT']:>4}  {t.get('TITLE') or '(untitled)'}")

    cur.close()
    conn.close()


def print_row(row, fmt):
    if fmt == "json":
        print(json.dumps(row, default=str))
    else:
        for k, v in row.items():
            print(f"  {k}: {v}")
        print()


def print_rows(rows, fmt):
    if fmt == "json":
        print(json.dumps(rows, default=str, indent=2))
    elif not rows:
        print("No results.")
    else:
        keys = list(rows[0].keys())
        widths = {k: max(len(k), max(len(str(r.get(k, "") or "")) for r in rows)) for k in keys}
        for k in widths:
            widths[k] = min(widths[k], 80)
        header = "  ".join(k.ljust(widths[k]) for k in keys)
        print(header)
        print("  ".join("-" * widths[k] for k in keys))
        for r in rows:
            print("  ".join(str(r.get(k, "") or "").ljust(widths[k])[:widths[k]] for k in keys))


def main():
    parser = argparse.ArgumentParser(description="Query CoCo conversation history")
    sub = parser.add_subparsers(dest="command", required=True)

    p_conv = sub.add_parser("conversations", aliases=["c"], help="List or search conversations")
    p_conv.add_argument("--search", "-s", help="Semantic search over summaries")
    p_conv.add_argument("--id", help="Show a specific session")
    p_conv.add_argument("--limit", "-n", type=int, default=20)
    p_conv.add_argument("--format", "-f", choices=["table", "json"], default="table")

    p_msg = sub.add_parser("messages", aliases=["m"], help="List or search messages")
    p_msg.add_argument("--search", "-s", help="Semantic search over message content")
    p_msg.add_argument("--id", help="Filter to a session ID")
    p_msg.add_argument("--role", "-r", choices=["user", "assistant"])
    p_msg.add_argument("--limit", "-n", type=int, default=20)
    p_msg.add_argument("--format", "-f", choices=["table", "json"], default="table")

    p_trans = sub.add_parser("transcript", aliases=["t"], help="Print readable transcript")
    p_trans.add_argument("--id", required=True, help="Session ID")
    p_trans.add_argument("--format", "-f", choices=["table", "json"], default="table")

    sub.add_parser("stats", help="Show summary statistics")

    args = parser.parse_args()

    if args.command in ("conversations", "c"):
        cmd_conversations(args)
    elif args.command in ("messages", "m"):
        cmd_messages(args)
    elif args.command in ("transcript", "t"):
        cmd_transcript(args)
    elif args.command == "stats":
        cmd_stats(args)


if __name__ == "__main__":
    main()
