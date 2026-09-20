# loco_loader

Loads local CoCo conversations into Snowflake for recall and analysis.

## Setup

**Requirements:** Python 3.11+, [Cortex Code Desktop](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code) (`cortex` CLI), key pair auth in `~/.snowflake/connections.toml`

```
pip install snowflake-connector-python snowflake cryptography
```

Create the target schema (or change via config below):

```sql
CREATE SCHEMA IF NOT EXISTS DEMOS.AGENT_MEMORY;
```

## Configuration

Via env vars:

```
export SNOWFLAKE_CONNECTION=my-connection-name
export SNOWFLAKE_DATABASE=DEMOS          # optional, default: DEMOS
export SNOWFLAKE_SCHEMA=AGENT_MEMORY     # optional, default: AGENT_MEMORY
```

Or flags (take precedence over env vars):

```
python3 full_load.py --snowflake-connection my-conn --database MY_DB --schema MY_SCHEMA
```

## Usage

```
python3 full_load.py          # first run or rebuild — truncates and reloads everything
python3 incremental_load.py   # ongoing sync — merges new/updated conversations
```

```
python3 query.py stats                              # row counts, date range, top sessions
python3 query.py conversations                       # list recent conversations
python3 query.py conversations --search "docusign"   # semantic search over summaries
python3 query.py conversations --id <session_id>     # one session's metadata + summary
python3 query.py messages --search "iceberg"         # semantic search over message content
python3 query.py messages --id <session_id>          # all messages in a session
python3 query.py messages --role user                # filter by speaker
python3 query.py transcript --id <session_id>        # readable [USER]/[ASSISTANT] format
```

`--format json` for JSON output. `-n <limit>` to control result count (default 20).

## Schema

| Table | Purpose |
|---|---|
| `CONVERSATIONS` | Session metadata, transcript (VARIANT), AI summary |
| `MESSAGES` | One row per turn — searchable by content, filterable by role |

| Search Service | Indexed | Filters |
|---|---|---|
| `MESSAGES_SEARCH` | CONTENT | SESSION_ID, ROLE |
| `CONVERSATIONS_SEARCH` | SUMMARY | TITLE, SOURCE |

## Limitations

- Active sessions won't appear until closed server-side (CLI indexing lag)
- ~5% of sessions fail to fetch (local-only or malformed) — skipped
- Summaries via `llama3.1-70b` can be verbose
