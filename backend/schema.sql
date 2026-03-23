-- ============================================================================
-- SHARD SQLite Schema v1.0
-- Replaces: experiment_history.json, experiment_replay.json, failed_cache.json,
--           meta_learning.json (sessions), capability_graph.json,
--           improvement_queue.json, refactor_state.json
-- ============================================================================

PRAGMA journal_mode = WAL;          -- Write-Ahead Logging: concurrent reads + one writer
PRAGMA busy_timeout = 5000;         -- Wait 5s on lock instead of failing immediately
PRAGMA foreign_keys = ON;

-- ─── EXPERIMENTS ─────────────────────────────────────────────────────────────
-- Single source of truth for ALL study cycle results.
-- Replaces: experiment_history.json, experiment_replay.json,
--           meta_learning.json (sessions array), and partially failed_cache.json

CREATE TABLE IF NOT EXISTS experiments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    topic           TEXT    NOT NULL,
    score           REAL,                           -- 0.0–10.0, NULL if crashed before eval
    certified       INTEGER DEFAULT 0,              -- 0/1 boolean
    sandbox_success INTEGER,                        -- 0/1 boolean, NULL if no sandbox phase
    timestamp       TEXT    NOT NULL,               -- ISO 8601
    category        TEXT,                           -- algorithms, ml, web, systems, etc.
    source          TEXT,                           -- curated, research_agenda, phoenix, improvement_engine
    failure_reason  TEXT,                           -- low_score, phase_error, network_violation, etc.
    strategy_used   TEXT,                           -- free text from meta_learning hint
    previous_score  REAL,                           -- Phoenix retry: score from previous attempt
    duration_min    REAL,                           -- minutes
    error_type      TEXT,
    error_signature TEXT,
    attempts        INTEGER DEFAULT 1,              -- repair loop count
    verdict         TEXT,                           -- PASS / FAIL
    -- JSON arrays stored as TEXT (queried rarely, iterated in Python)
    strategies_reused TEXT DEFAULT '[]',            -- JSON array of strings
    skills_unlocked   TEXT DEFAULT '[]',            -- JSON array of strings
    files_modified    TEXT DEFAULT '[]'             -- JSON array of strings
);

CREATE INDEX IF NOT EXISTS idx_exp_topic      ON experiments(topic);
CREATE INDEX IF NOT EXISTS idx_exp_certified  ON experiments(certified);
CREATE INDEX IF NOT EXISTS idx_exp_timestamp  ON experiments(timestamp);
CREATE INDEX IF NOT EXISTS idx_exp_category   ON experiments(category);
CREATE INDEX IF NOT EXISTS idx_exp_score      ON experiments(score);

-- Phoenix Protocol candidates: near-miss experiments eligible for retry
CREATE VIEW IF NOT EXISTS phoenix_candidates AS
SELECT
    topic,
    MAX(score)  AS best_score,
    COUNT(*)    AS attempt_count,
    MAX(timestamp) AS last_attempt
FROM experiments
WHERE score BETWEEN 6.0 AND 7.4
  AND certified = 0
GROUP BY topic
ORDER BY best_score DESC;

-- Quarantine: topics with 3+ attempts and max score < 6.0 (hard fails)
CREATE VIEW IF NOT EXISTS quarantined_topics AS
SELECT
    topic,
    COUNT(*)    AS attempt_count,
    MAX(score)  AS best_score,
    MAX(timestamp) AS last_attempt
FROM experiments
WHERE certified = 0
GROUP BY topic
HAVING COUNT(*) >= 3 AND MAX(score) < 6.0;

-- Per-category stats (replaces meta_learning.json topic_categories)
CREATE VIEW IF NOT EXISTS category_stats AS
SELECT
    category,
    COUNT(*)                          AS total,
    SUM(certified)                    AS certified_count,
    ROUND(AVG(score), 2)             AS avg_score,
    ROUND(CAST(SUM(certified) AS REAL) / COUNT(*), 3) AS cert_rate
FROM experiments
WHERE category IS NOT NULL
GROUP BY category;

-- Global stats (replaces meta_learning.json global_stats)
CREATE VIEW IF NOT EXISTS global_stats AS
SELECT
    COUNT(*)                          AS total_sessions,
    SUM(certified)                    AS certified_count,
    ROUND(AVG(score), 2)             AS avg_score,
    ROUND(CAST(SUM(certified) AS REAL) / COUNT(*), 3) AS cert_rate
FROM experiments;


-- ─── FAILED CACHE ────────────────────────────────────────────────────────────
-- Topics that failed, with the skill count SHARD had at time of failure.
-- A topic is retryable when current_skill_count > skill_count_at_failure.
-- Replaces: failed_cache.json

CREATE TABLE IF NOT EXISTS failed_cache (
    topic               TEXT PRIMARY KEY,
    skill_count_at_fail INTEGER NOT NULL,
    last_failed_at      TEXT                        -- ISO 8601
);


-- ─── CAPABILITIES ────────────────────────────────────────────────────────────
-- Persistent registry of SHARD's certified skills.
-- Replaces: capability_graph.json

CREATE TABLE IF NOT EXISTS capabilities (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    UNIQUE NOT NULL,            -- lowercase, atomic (no "Integration of...")
    source_topic TEXT,                               -- the study topic that unlocked this
    acquired_at  TEXT    NOT NULL                     -- ISO 8601
);

CREATE INDEX IF NOT EXISTS idx_cap_name   ON capabilities(name);
CREATE INDEX IF NOT EXISTS idx_cap_source ON capabilities(source_topic);

-- Dependency edges: capability X requires capability Y
CREATE TABLE IF NOT EXISTS capability_deps (
    capability_id  INTEGER NOT NULL,
    requires_name  TEXT    NOT NULL,
    PRIMARY KEY (capability_id, requires_name),
    FOREIGN KEY (capability_id) REFERENCES capabilities(id) ON DELETE CASCADE
);


-- ─── IMPROVEMENT QUEUE ───────────────────────────────────────────────────────
-- SSJ3 self-improvement tickets from SelfAnalyzer → ImprovementEngine.
-- Replaces: improvement_queue.json

CREATE TABLE IF NOT EXISTS improvement_tickets (
    id           TEXT    PRIMARY KEY,                -- e.g. "cf_topic_name_truncated"
    ticket_type  TEXT    NOT NULL,                   -- retry_chronic_failure, certify_near_miss, fill_gap, retry_grown
    action       TEXT,                               -- decompose, inject, skip_garbage
    topic        TEXT,
    reason       TEXT,
    priority     INTEGER DEFAULT 0,                  -- lower = higher priority (-1 = drain first)
    status       TEXT    DEFAULT 'pending',           -- pending, processed, skipped
    created_at   TEXT    NOT NULL,
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tickets_status ON improvement_tickets(status);


-- ─── REFACTOR HISTORY ────────────────────────────────────────────────────────
-- SSJ4 proactive refactor proposals and their outcomes.
-- Replaces: refactor_state.json

CREATE TABLE IF NOT EXISTS refactor_history (
    id          TEXT PRIMARY KEY,                    -- UUID
    file_path   TEXT NOT NULL,
    description TEXT,
    category    TEXT,                                -- performance, clean_code, token_savings
    rationale   TEXT,
    changes     TEXT NOT NULL,                       -- JSON array of {old, new}
    status      TEXT DEFAULT 'pending',              -- pending, applied, rejected
    created_at  TEXT NOT NULL,
    applied_at  TEXT,
    backup_path TEXT
);

-- Key-value store for small config (e.g. refactor round-robin index)
CREATE TABLE IF NOT EXISTS kv_store (
    key   TEXT PRIMARY KEY,
    value TEXT
);


-- ─── KNOWLEDGE GRAPH (GraphRAG) ──────────────────────────────────────────────
-- Causal relations between concepts extracted during SYNTHESIZE phase.
-- Transforms SHARD from "student who studied" to "senior who has experience".
-- e.g. asyncio → threading: relation_type=causes_conflict

CREATE TABLE IF NOT EXISTS knowledge_graph (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_concept  TEXT    NOT NULL,
    target_concept  TEXT    NOT NULL,
    relation_type   TEXT    NOT NULL,   -- causes_conflict | depends_on | replaces | improves | breaks
    confidence      REAL    DEFAULT 0.7,
    context         TEXT,               -- natural language explanation
    topic_origin    TEXT,               -- study topic that discovered this relation
    created_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kg_source ON knowledge_graph(source_concept);
CREATE INDEX IF NOT EXISTS idx_kg_target ON knowledge_graph(target_concept);
CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_pair
    ON knowledge_graph(source_concept, target_concept, relation_type);


-- ─── SCHEMA VERSION ──────────────────────────────────────────────────────────
-- For future migrations

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

INSERT OR IGNORE INTO schema_version (version, applied_at)
VALUES (1, datetime('now'));
