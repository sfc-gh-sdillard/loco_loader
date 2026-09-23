---
name: "add-local-tests"
created: "2026-09-23T06:29:15.055Z"
status: pending
---

# Plan: Add Local Tests

## Approach

Unit tests using `pytest` + `unittest.mock` that run entirely locally — no Snowflake connection, no `cortex` CLI, no credits. Mock the two boundaries:

1. **`subprocess.run`** (cortex CLI calls) — return canned CSV/NDJSON responses
2. **`snowflake.connector.connect`** / **`Session`** — mock cursor and session objects

## What gets tested

### `core.py` (pure logic — highest value)

- `parse_messages()` — given a transcript, produces correct message rows (role extraction, text parsing, tool\_result handling)
- `get_config()` — flag > env var > default precedence
- `list_conversations()` — builds correct CLI command with/without `--after` and `--connection`, parses CSV output
- `fetch_transcript()` — parses NDJSON, handles malformed lines
- `add_common_args()` — parser gets all three flags

### `full_load.py` / `incremental_load.py` (integration-level)

- Mock the connection and verify:

  - Correct SQL statements are executed (TRUNCATE, INSERT, MERGE, UPDATE)
  - `session.write_pandas` is called with correctly shaped DataFrame
  - Watermark query returns expected value and filters conversations
  - Skipped/errored transcripts don't break the run

## Test fixtures (`tests/fixtures/`)

| File                          | Content                                                 |
| ----------------------------- | ------------------------------------------------------- |
| `conversations.csv`           | 3 rows of `cortex conversations search` CSV output      |
| `transcript_short.ndjson`     | 4-message transcript (user, assistant, user, assistant) |
| `transcript_malformed.ndjson` | Valid line + broken JSON line (tests error handling)    |

## File structure

```
tests/
├── conftest.py              # Fixtures: mock data, patched subprocess/connector
├── fixtures/
│   ├── conversations.csv
│   ├── transcript_short.ndjson
│   └── transcript_malformed.ndjson
├── test_core.py             # Unit tests for core.py
└── test_loads.py            # Integration tests for full_load + incremental_load
```

## What this does NOT test

- Actual Snowflake SQL correctness (that's an integration test requiring a live connection)
- AI\_COMPLETE summary quality
- Cortex Search service creation

Those would be a separate integration test suite if needed later.
