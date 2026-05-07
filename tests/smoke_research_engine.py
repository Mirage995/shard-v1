"""smoke_research_engine.py — Controlled integration smoke test for Research Engine gates.

Covers 5 checkpoints without real LLM API calls, GPU dispatch, or Docker:

  CP1  NOVELTY_EXTERNAL    arxiv+LLM novelty judge (mocked, no network)
  CP2  DB_DEDUP            SequenceMatcher gate against in-memory seeded DB
  CP3  ANTAGONIST_GATE     normalize_antagonist_review + 7-field log structure
  CP4  GRAPHRAG_PROVENANCE _VALIDATION_TIER_WEIGHT values + tier override
  CP5  NO_GPU_DISPATCH     requires_real_world_data returns False for synthetic specs

Run:  pytest tests/smoke_research_engine.py -v -s
"""
import logging
import sqlite3
import sys
import os
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# ── Fixtures ─────────────────────────────────────────────────────────────────

TOPIC = "transformer regularization"

NOVEL_STMT = (
    "Applying spectral graph convolutions from algebraic topology to transformer "
    "self-attention reduces over-smoothing on long-range dependency benchmarks "
    "without additional parameters."
)

SEEDED_STMT = (
    "Applying dropout regularization in transformer encoders reduces overfitting "
    "on low-resource NLP tasks by preventing co-adaptation of attention heads."
)


def _make_test_conn():
    """In-memory SQLite with one CONFIRMED hypothesis for dedup tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE research_hypotheses (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            topic               TEXT,
            statement           TEXT NOT NULL,
            domain_from         TEXT,
            domain_to           TEXT,
            rationale           TEXT,
            falsifiable         INTEGER DEFAULT 0,
            minimum_experiment  TEXT,
            confidence_initial  REAL,
            confidence_updated  REAL,
            status              TEXT DEFAULT 'PENDING',
            experiment_code     TEXT,
            experiment_result   TEXT,
            source_papers       TEXT,
            created_at          TEXT DEFAULT (datetime('now')),
            updated_at          TEXT DEFAULT (datetime('now')),
            execution_backend   TEXT DEFAULT 'local_sandbox',
            data_provenance     TEXT DEFAULT 'synthetic',
            validation_tier     TEXT DEFAULT 'sandbox_replicated',
            manual_backfill     INTEGER DEFAULT 0
        )
    """)
    conn.execute(
        """
        INSERT INTO research_hypotheses
            (topic, statement, domain_from, domain_to, status, confidence_initial)
        VALUES (?, ?, ?, ?, 'CONFIRMED', 0.88)
        """,
        (TOPIC, SEEDED_STMT, "NLP", "Transformers"),
    )
    conn.commit()
    return conn


def _minimal_agent():
    """StudyAgent with only the novelty-gate dependencies set (no ChromaDB/Docker)."""
    from study_agent import StudyAgent
    agent = StudyAgent.__new__(StudyAgent)
    agent._topic_llm_calls  = 0
    agent._topic_llm_budget = 200
    agent.session_context   = ""
    return agent


# ── CP1: NOVELTY_EXTERNAL ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cp1_novelty_external_novel():
    """CP1: arxiv empty + LLM='NOVEL' → is_novel=True."""
    agent = _minimal_agent()

    mock_arxiv = MagicMock()
    mock_arxiv.Client.return_value.results.return_value = []
    mock_arxiv.Search = MagicMock()
    mock_arxiv.SortCriterion.Relevance = MagicMock()

    with patch.dict(sys.modules, {"arxiv": mock_arxiv}):
        with patch("llm_router.llm_complete", new=AsyncMock(return_value="NOVEL")):
            is_novel, reason = await agent._check_hypothesis_novelty({
                "statement":   NOVEL_STMT,
                "domain_from": "Algebraic Topology",
                "domain_to":   "Transformers",
            })

    print(f"\n[SMOKE CP1] NOVELTY_EXTERNAL: is_novel={is_novel}  reason='{reason}'")
    assert is_novel is True, f"Expected NOVEL, got: {reason}"
    assert "KNOWN" not in reason


@pytest.mark.asyncio
async def test_cp1_novelty_external_known():
    """CP1b: arxiv empty + LLM='KNOWN' → is_novel=False."""
    agent = _minimal_agent()

    mock_arxiv = MagicMock()
    mock_arxiv.Client.return_value.results.return_value = []
    mock_arxiv.Search = MagicMock()
    mock_arxiv.SortCriterion.Relevance = MagicMock()

    with patch.dict(sys.modules, {"arxiv": mock_arxiv}):
        with patch("llm_router.llm_complete", new=AsyncMock(return_value="KNOWN")):
            is_novel, reason = await agent._check_hypothesis_novelty({
                "statement":   SEEDED_STMT,
                "domain_from": "NLP",
                "domain_to":   "Transformers",
            })

    print(f"\n[SMOKE CP1b] NOVELTY_EXTERNAL: is_novel={is_novel}  reason='{reason}'")
    assert is_novel is False, f"Expected KNOWN, got: {reason}"


@pytest.mark.asyncio
async def test_cp1_novelty_arxiv_word_overlap_fast_path():
    """CP1c: arxiv title word-overlap > 0.35 → fast-path KNOWN without LLM Stage 2."""
    agent = _minimal_agent()

    mock_paper = MagicMock()
    mock_paper.title   = "Dropout Regularization in Transformer Encoders for Low-Resource NLP"
    mock_paper.summary = "We study dropout in transformers to prevent co-adaptation of heads."
    mock_paper.published.year = 2022

    mock_arxiv = MagicMock()
    mock_arxiv.Client.return_value.results.return_value = [mock_paper]
    mock_arxiv.Search = MagicMock()
    mock_arxiv.SortCriterion.Relevance = MagicMock()

    # Stage 2 llm_complete should NOT be called (fast-path returns before it)
    llm_mock = AsyncMock(return_value="NOVEL")  # would wrongly say NOVEL if reached

    with patch.dict(sys.modules, {"arxiv": mock_arxiv}):
        with patch("llm_router.llm_complete", new=llm_mock):
            is_novel, reason = await agent._check_hypothesis_novelty({
                "statement":   SEEDED_STMT,
                "domain_from": "NLP",
                "domain_to":   "Transformers",
            })

    print(f"\n[SMOKE CP1c] NOVELTY_ARXIV_OVERLAP: is_novel={is_novel}  reason='{reason[:80]}'")
    assert is_novel is False
    assert "KNOWN" in reason


# ── CP2: DB_DEDUP ─────────────────────────────────────────────────────────────

def _get_rows_from_test_conn(conn):
    with patch("experiment_store._get_db", return_value=conn):
        from experiment_store import get_all_statements
        return get_all_statements()


def test_cp2_db_dedup_hard_duplicate():
    """CP2: verbatim CONFIRMED statement → is_duplicate=True, DUPLICATE_CONFIRMED."""
    from study_agent import _dedup_check_against_rows, _DEDUP_HARD_THRESHOLD

    rows   = _get_rows_from_test_conn(_make_test_conn())
    result = _dedup_check_against_rows(
        {"statement": SEEDED_STMT, "domain_from": "NLP", "domain_to": "Transformers"},
        rows,
    )
    print(
        f"\n[SMOKE CP2] DB_DEDUP hard_dup: "
        f"is_dup={result['is_duplicate']}  ratio={result['similarity_ratio']:.3f}  "
        f"reason={result['reason']}  matched_id={result['matched_id']}"
    )
    assert result["is_duplicate"]               is True
    assert result["similarity_ratio"]           >= _DEDUP_HARD_THRESHOLD
    assert result["reason"]                     == "DUPLICATE_CONFIRMED"
    assert result["matched_id"]                 == 1
    assert result["matched_status"]             == "CONFIRMED"
    assert "db_sequence_matcher" not in result  # reason field, not key


def test_cp2_db_dedup_novel_passes():
    """CP2b: unrelated hypothesis → is_duplicate=False, similarity below suspicious threshold."""
    from study_agent import _dedup_check_against_rows, _DEDUP_SUSPICIOUS_THRESHOLD

    rows   = _get_rows_from_test_conn(_make_test_conn())
    result = _dedup_check_against_rows(
        {"statement": NOVEL_STMT, "domain_from": "Algebraic Topology", "domain_to": "Transformers"},
        rows,
    )
    print(
        f"\n[SMOKE CP2b] DB_DEDUP novel: "
        f"is_dup={result['is_duplicate']}  ratio={result['similarity_ratio']:.3f}  "
        f"domain_pair_seen={result['domain_pair_seen']}"
    )
    assert result["is_duplicate"]     is False
    assert result["is_suspicious"]    is False
    assert result["similarity_ratio"] < _DEDUP_SUSPICIOUS_THRESHOLD


def test_cp2_db_dedup_refuted_metadata_note():
    """CP2c: hard dup against REFUTED → reason contains 'novelty_delta' annotation."""
    from study_agent import _dedup_check_against_rows

    REFUTED_STMT = (
        "Applying batch normalization before residual connections in ResNet "
        "increases gradient variance and destabilizes training on CIFAR-10."
    )
    rows = [{"id": 9, "status": "REFUTED", "statement": REFUTED_STMT,
             "domain_from": "CV", "domain_to": "Training", "confidence": 0.70}]
    result = _dedup_check_against_rows(
        {"statement": REFUTED_STMT, "domain_from": "CV", "domain_to": "Training"},
        rows,
    )
    print(
        f"\n[SMOKE CP2c] DB_DEDUP REFUTED: "
        f"reason={result['reason']}"
    )
    assert result["is_duplicate"]          is True
    assert "DUPLICATE_REFUTED"             in result["reason"]
    assert "novelty_delta"                 in result["reason"]


# ── CP3: ANTAGONIST_GATE ──────────────────────────────────────────────────────

def test_cp3_antagonist_gate_valid_passthrough():
    """CP3a: well-formed VALID review → no gate forced, forced_verdict=False."""
    from experiment_phases import normalize_antagonist_review

    gate = normalize_antagonist_review({
        "verdict":               "VALID",
        "confidence":            0.88,
        "alternative_mechanism": "Random weight init variance explains the gap",
        "confounds":             ["dataset size", "learning rate schedule"],
        "missing_controls":      ["early stopping criterion"],
        "reason":                "Code is correct and reproduces the effect.",
        "corrected_code":        None,
        "review_quality":        "thorough",
    })
    print(f"\n[SMOKE CP3a] ANTAGONIST_GATE passthrough: verdict={gate['verdict']}  forced={gate['forced_verdict']}")
    assert gate["verdict"]        == "VALID"
    assert gate["forced_verdict"] is False
    assert gate["force_reason"]   == ""


def test_cp3_antagonist_gate_forced_log(caplog):
    """CP3b: empty alternative_mechanism → G4 forces INVALID_CORRECTABLE; log has all 7 fields."""
    from experiment_phases import normalize_antagonist_review

    review = {
        "verdict":               "VALID",
        "confidence":            0.88,
        "alternative_mechanism": "",            # G4 triggers
        "confounds":             ["dataset size", "LR schedule"],
        "missing_controls":      ["early stopping"],
        "reason":                "Code appears correct.",
        "corrected_code":        None,
        "review_quality":        "thorough",
    }
    with caplog.at_level(logging.INFO):
        gate = normalize_antagonist_review(review)
        logging.getLogger("shard.experiment").info(
            "[ANTAGONIST_GATE] attempt=%d verdict=%s confidence=%.2f forced=%s "
            "force_reason=%r has_alt_mechanism=%s confound_count=%d missing_control_count=%d",
            1,
            gate["verdict"],
            float(gate.get("confidence") or 0.0),
            gate.get("forced_verdict", False),
            gate.get("force_reason", ""),
            bool(str(gate.get("alternative_mechanism", "")).strip()),
            len(gate.get("confounds") or []),
            len(gate.get("missing_controls") or []),
        )

    gate_logs = [r for r in caplog.records if "[ANTAGONIST_GATE]" in r.message]
    assert gate_logs, "Expected at least one [ANTAGONIST_GATE] log entry"

    entry = gate_logs[0].message
    print(f"\n[SMOKE CP3b] ANTAGONIST_GATE log:\n  {entry}")

    assert "forced=True"                  in entry
    assert "G4"                           in entry
    assert "verdict=INVALID_CORRECTABLE"  in entry
    assert "confound_count=2"             in entry
    assert gate["forced_verdict"]         is True


# ── CP4: GRAPHRAG_PROVENANCE ──────────────────────────────────────────────────

def test_cp4_graphrag_tier_weight_map():
    """CP4a: all 5 tiers present in _VALIDATION_TIER_WEIGHT with correct confidence."""
    from graph_rag import _VALIDATION_TIER_WEIGHT

    expected = [
        ("code_runs",           0.20, "verified_provisional"),
        ("sandbox_replicated",  0.35, "verified_provisional"),
        ("gpu_replicated",      0.75, "verified"),
        ("benchmark_validated", 0.85, "verified"),
        ("external_replicated", 0.90, "verified"),
    ]
    print("\n[SMOKE CP4a] GRAPHRAG tier weight map:")
    for tier, exp_conf, exp_status in expected:
        conf, status = _VALIDATION_TIER_WEIGHT[tier]
        print(f"  {tier:25s} conf={conf:.2f}  status={status}")
        assert conf   == exp_conf,   f"{tier}: conf={conf} expected {exp_conf}"
        assert status == exp_status, f"{tier}: status={status} expected {exp_status}"


def test_cp4_graphrag_tier_overrides_confidence():
    """CP4b: gpu_replicated tier overrides initial confidence 0.50 → stored 0.75."""
    from graph_rag import insert_verified_relation

    captured: dict = {}

    def _mock_execute(sql, params=None):
        captured["sql"]    = sql
        captured["params"] = params

    # graph_rag does `from shard_db import execute` lazily — patch shard_db.execute
    with patch("shard_db.execute", side_effect=_mock_execute):
        insert_verified_relation(
            source_concept  = "dropout",
            target_concept  = "overfitting",
            relation_type   = "reduces",
            context         = "Smoke test assertion.",
            verified_status = "verified",
            confidence      = 0.50,          # initial — will be overridden
            topic_origin    = TOPIC,
            experiment_id   = "smoke_42",
            validation_tier = "gpu_replicated",
        )

    assert captured.get("params"), "execute() was not called by insert_verified_relation"
    stored_conf = captured["params"][4]   # 5th positional param is confidence
    print(
        f"\n[SMOKE CP4b] GRAPHRAG tier override: "
        f"initial_conf=0.50  tier=gpu_replicated  stored_conf={stored_conf:.2f}"
    )
    assert stored_conf == 0.75, f"Expected 0.75 (gpu_replicated override), got {stored_conf}"


def test_cp4_graphrag_sandbox_replicated_default():
    """CP4c: sandbox_replicated tier → conf=0.35, verified_provisional."""
    from graph_rag import insert_verified_relation

    captured: dict = {}

    def _mock_execute(sql, params=None):
        captured["params"] = params

    with patch("shard_db.execute", side_effect=_mock_execute):
        insert_verified_relation(
            source_concept  = "L2_regularization",
            target_concept  = "test_loss",
            relation_type   = "reduces",
            context         = "Sandbox replication.",
            verified_status = "verified",
            confidence      = 0.90,
            topic_origin    = TOPIC,
            experiment_id   = "smoke_43",
            validation_tier = "sandbox_replicated",
        )

    stored_conf = captured["params"][4]
    print(
        f"\n[SMOKE CP4c] GRAPHRAG sandbox_replicated: "
        f"initial_conf=0.90  stored_conf={stored_conf:.2f}"
    )
    assert stored_conf == 0.35


# ── CP5: NO_GPU_DISPATCH ──────────────────────────────────────────────────────

def test_cp5_synthetic_spec_no_gpu():
    """CP5a: synthetic/local hypothesis → requires_real_world_data=False (stays local)."""
    from experiment_phases import requires_real_world_data

    synthetic_spec = {
        "mechanism":          "L2 regularization penalizes large weights in a 2-layer MLP.",
        "intervention":       "Compare L2 vs no regularization on synthetic Gaussian clusters.",
        "measurement":        "Test accuracy after 10 epochs on held-out synthetic data.",
        "success_criterion":  "Regularized model exceeds baseline accuracy by > 3%.",
        "control":            "Fixed random seed; identical architecture for both variants.",
    }
    needs_gpu = requires_real_world_data(synthetic_spec)
    print(f"\n[SMOKE CP5a] NO_GPU_DISPATCH: requires_real_world_data={needs_gpu}")
    assert needs_gpu is False


def test_cp5_real_world_keywords_trigger_kaggle():
    """CP5b: fMRI/clinical keyword in spec → requires_real_world_data=True → KAGGLE_READY routing."""
    from experiment_phases import requires_real_world_data

    rw_spec = {
        "mechanism":          "fMRI activation patterns correlate with clinical outcome scores.",
        "intervention":       "Apply feature selection to fMRI tensors from hospital dataset.",
        "measurement":        "AUC on held-out patient cohort.",
        "success_criterion":  "AUC > 0.80.",
        "control":            "Age and gender matched controls.",
    }
    needs_gpu = requires_real_world_data(rw_spec)
    print(f"\n[SMOKE CP5b] REAL_WORLD_TRIGGER: requires_real_world_data={needs_gpu}")
    assert needs_gpu is True


def test_cp5_no_kaggle_rows_in_test_db():
    """CP5c: test DB has only CONFIRMED rows — no KAGGLE_READY/MODAL_READY produced by smoke run."""
    conn = _make_test_conn()
    with patch("experiment_store._get_db", return_value=conn):
        from experiment_store import get_all_statements, get_kaggle_ready, get_pending_gpu_runs
        kaggle_rows = get_kaggle_ready()
        gpu_rows    = get_pending_gpu_runs()

    print(f"\n[SMOKE CP5c] No GPU rows: kaggle={len(kaggle_rows)}  gpu_pending={len(gpu_rows)}")
    assert len(kaggle_rows) == 0, f"Expected 0 KAGGLE_READY rows, got {len(kaggle_rows)}"
    assert len(gpu_rows)    == 0, f"Expected 0 pending GPU runs, got {len(gpu_rows)}"
