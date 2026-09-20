-- CoCo Conversation History Schema
-- Target: DEMOS.AGENT_MEMORY

CREATE SCHEMA IF NOT EXISTS DEMOS.AGENT_MEMORY;

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
COMMENT = 'Quick recall of CoCo conversations: lookup summaries, pull whole transcripts, or browse session metadata.';

CREATE TABLE IF NOT EXISTS DEMOS.AGENT_MEMORY.MESSAGES (
  MESSAGE_ID   VARCHAR PRIMARY KEY,
  SESSION_ID   VARCHAR,
  TURN_INDEX   INT,
  ROLE         VARCHAR,
  CONTENT      VARCHAR,
  RAW_CONTENT  VARIANT,
  CREATED_AT   TIMESTAMP_NTZ
)
COMMENT = 'Normalized CoCo conversation turns for searching specific messages, filtering by role, or finding conversations by keyword against RAW_CONTENT.';

-- Optional: Task to refresh summaries for already-loaded data
-- The full extraction requires the local `cortex` CLI, so this Task
-- only handles re-summarizing sessions whose summary is stale.
/*
CREATE OR REPLACE TASK DEMOS.AGENT_MEMORY.REFRESH_COCO_SUMMARIES
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = 'USING CRON 0 8 * * * America/Los_Angeles'
AS
  UPDATE DEMOS.AGENT_MEMORY.CONVERSATIONS
  SET SUMMARY = AI_COMPLETE(
        'claude-3-5-sonnet',
        'Summarize this CoCo (Cortex Code) conversation in 2-3 sentences. Focus on what was accomplished:\n\n' ||
        TRANSCRIPT::VARCHAR
      ),
      SUMMARY_UPDATED_AT = CURRENT_TIMESTAMP()
  WHERE SUMMARY IS NULL
     OR LAST_MESSAGE_AT > SUMMARY_UPDATED_AT;
*/
