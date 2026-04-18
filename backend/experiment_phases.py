"""experiment_phases.py -- SHARD Experiment Engine phases (#35).

Three pipeline phases activated only in research_mode=True:

  ExperimentDesignPhase   -- LLM generates executable Python for hypothesis test
  ExperimentSandboxPhase  -- runs code in DockerSandboxRunner (zero modifications)
  ExperimentValidatePhase -- LLM decides CONFIRMED/REFUTED/INCONCLUSIVE + DB write

All three phases are non-fatal and self-gating:
  - If research_mode=False or hypothesis not suitable -> SKIPPED, pipeline continues
  - Errors are caught and logged, never propagate to CertifyRetryGroup
"""
import json
import logging
import os
import time
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from study_context import StudyContext

from study_phases import BasePhase

logger = logging.getLogger("shard.experiment_phases")

# ── Deterministic 4-section parser ──────────────────────────────────────────

import re as _re_module

# ── Regex-based multiline 4-section parser ────────────────────────────────────
# Handles: "MECHANISM:\n text", whitespace/indent variation, out-of-order sections.

_SECTION_PATTERNS = {
    "mechanism":        r"MECHANISM:\s*(.+?)(?=\n[A-Z ]+:|$)",
    "intervention":     r"INTERVENTION:\s*(.+?)(?=\n[A-Z ]+:|$)",
    "measurement":      r"MEASUREMENT:\s*(.+?)(?=\n[A-Z ]+:|$)",
    "success_criterion": r"SUCCESS CRITERION:\s*(.+?)(?=\n[A-Z ]+:|$)",
}

# Qualitative signals → measurement is NOT scalar
_MEASUREMENT_BLACKLIST = {"compare", "visual", "plot", "qualitative", "describe", "observe", "show"}

# Proxy metric patterns: vague improvement claims with no specific variable binding.
# These pass structural checks but are scientifically weak — mechanism is untestable.
_PROXY_METRIC_PATTERNS = [
    r'\baccuracy\s+improve[sd]?\b',
    r'\bperformance\s+increase[sd]?\b',
    r'\bperformance\s+improve[sd]?\b',
    r'\befficiency\s+improve[sd]?\b',
    r'\bquality\s+improve[sd]?\b',
    r'\bscore\s+increase[sd]?\b',
    r'\bbetter\s+(?:than|result|outcome|performance)\b',
    r'\bimprove[sd]?\s+(?:accuracy|performance|efficiency|quality)\b',
]


def parse_experiment_spec(text: str) -> dict | None:
    """Parse the 4-section structure from minimum_experiment text (regex, multiline).

    Handles newline after colon, indentation, out-of-order sections.
    Returns dict[mechanism/intervention/measurement/success_criterion] or None.
    """
    if not text:
        return None
    spec = {}
    for key, pattern in _SECTION_PATTERNS.items():
        m = _re_module.search(pattern, text, _re_module.DOTALL | _re_module.IGNORECASE)
        if not m:
            return None
        value = m.group(1).strip()
        if not value:
            return None
        spec[key] = value
    return spec


def _is_scalar_metric(text: str) -> bool:
    """True if measurement is likely scalar (not qualitative/visual)."""
    lower = text.lower()
    return not any(w in lower for w in _MEASUREMENT_BLACKLIST)


def _has_numeric_threshold(text: str) -> bool:
    """True if success criterion contains a numeric comparison threshold."""
    return bool(_re_module.search(r'\d+(\.\d+)?\s*(%|>|<|>=|<=)', text))


_STOPWORDS = {
    "the", "a", "an", "is", "are", "of", "in", "to", "by", "for",
    "with", "and", "or", "that", "this", "it", "be", "as", "at",
    "from", "on", "not", "can", "will", "which", "its", "has",
}

_SIMULATION_KEYWORDS = {
    "distribution", "generate", "sample", "random", "numpy",
    "scipy", "simulate", "synthetic", "np.", "randn", "randint",
}


def check_metric_linkage(spec: dict) -> bool:
    """Check that the metric named in MEASUREMENT is referenced in SUCCESS CRITERION.

    Captures the MECHANISM→MEASUREMENT→SUCCESS chain without full AST parsing.
    Extracts significant tokens (len≥4, not stopwords) from MEASUREMENT and checks
    that at least one appears in SUCCESS CRITERION.
    """
    measurement = spec.get("measurement", "").lower()
    success = spec.get("success_criterion", "").lower()
    tokens = {
        w for w in _re_module.findall(r'\b\w{4,}\b', measurement)
        if w not in _STOPWORDS
    }
    return bool(tokens) and any(tok in success for tok in tokens)


def check_simulation_grounding(spec: dict) -> bool:
    """Check that INTERVENTION or MECHANISM describes how data is generated synthetically."""
    text = (spec.get("intervention", "") + " " + spec.get("mechanism", "")).lower()
    return any(k in text for k in _SIMULATION_KEYWORDS)


def check_control_clause(raw_text: str) -> bool:
    """Check that a CONTROL section is present in the raw spec text."""
    return bool(_re_module.search(r'CONTROL\s*:', raw_text, _re_module.IGNORECASE))


def check_proxy_metric(spec: dict) -> bool:
    """Return True if measurement/success_criterion are free of proxy metric patterns.

    Proxy metrics ("accuracy improves", "performance increases") are scientifically weak:
    the measurement does not isolate the mechanism effect — it could change for reasons
    unrelated to the stated MECHANISM. Returns False (issue) when a proxy pattern is found
    AND there is no explicit VARIABLE binding (V = formula) in the spec.
    """
    measurement = spec.get("measurement", "").lower()
    success = spec.get("success_criterion", "").lower()
    combined = measurement + " " + success
    mechanism = spec.get("mechanism", "").lower() + spec.get("intervention", "").lower()

    # Only flag if there's no explicit variable binding (the binding already provides specificity)
    has_variable_binding = bool(_re_module.search(
        r'\bvariable\s*:\s*\w|[a-z_]\w*\s*=\s*\w', mechanism, _re_module.IGNORECASE
    ))
    if has_variable_binding:
        return True  # binding present — proxy concern overridden

    return not any(
        _re_module.search(p, combined, _re_module.IGNORECASE)
        for p in _PROXY_METRIC_PATTERNS
    )


def validate_structure(spec: dict, raw_text: str = "") -> tuple[bool, list[str]]:
    """Zero-LLM micro-validation of a parsed 4-section spec.

    Returns (ok, list_of_issues).
    """
    issues = []
    if not _is_scalar_metric(spec.get("measurement", "")):
        issues.append("MEASUREMENT appears qualitative (not scalar)")
    if not _has_numeric_threshold(spec.get("success_criterion", "")):
        issues.append("SUCCESS CRITERION has no numeric threshold")
    if not check_metric_linkage(spec):
        issues.append("METRIC not linked: MEASUREMENT token absent from SUCCESS CRITERION")
    if not check_simulation_grounding(spec):
        issues.append("SIMULATION not grounded: no data-generation keywords in INTERVENTION/MECHANISM")
    if raw_text and not check_control_clause(raw_text):
        issues.append("CONTROL clause missing: no confounder isolation declared")
    if not check_proxy_metric(spec):
        issues.append("PROXY METRIC: vague improvement claim without direct variable mapping — "
                      "measurement does not isolate mechanism")
    return (len(issues) == 0, issues)


_REAL_WORLD_FLAGS = {
    "fmri", "eeg", "clinical", "patient", "wildfire", "satellite",
    "real-world", "biological variability", "in vivo", "in situ",
    "ecg", "mri", "ct scan", "hospital", "genomic", "transcriptomic",
    "sensor data", "lidar", "remote sensing",
    # biological sequence domains — require real molecular data
    "dna", "rna", "dna sequence", "rna sequence", "bioinformatics",
    "nucleotide", "genome", "proteomics", "sequencing",
}

_SYNTHETIC_SIGNALS = {
    "synthetic", "simulated", "simulate", "random", "toy", "benchmark",
    "generate", "numpy", "scipy", "artificial",
}


def requires_real_world_data(spec: dict) -> bool:
    """True if the spec references domain-specific real-world data the sandbox can't provide."""
    text = " ".join(spec.values()).lower()
    return any(k in text for k in _REAL_WORLD_FLAGS)


def synthetic_declared(spec: dict) -> bool:
    """True if the spec explicitly states the phenomenon is simulated synthetically."""
    text = (spec.get("intervention", "") + " " + spec.get("mechanism", "")).lower()
    return any(k in text for k in _SYNTHETIC_SIGNALS)


async def _force_rewrite_experiment(original: str, ctx) -> str | None:
    """Atomic LLM call to reformat a free-form experiment into the 4-section spec.

    Uses a sterile minimal prompt — no system context contamination.
    json_mode=False: we want rigid plain text, not JSON.
    Returns reformatted string if parse succeeds, else None (hard fail).
    """
    prompt = (
        "Convert this experiment into the required structured format.\n\n"
        "FORMAT (each section on its own line):\n"
        "MECHANISM: [property P of X reduces/increases process Q in Y. VARIABLE: V = <formula>]\n"
        "INTERVENTION: [technique vs baseline. Simulated as: generate data using numpy/scipy with <distribution/process>]\n"
        "MEASUREMENT: [Metric: <name_of_V>, computed as <formula>]\n"
        "SUCCESS CRITERION: [<name_of_V> exceeds baseline by ><threshold>]\n"
        "CONTROL: [1-2 confounders held constant: <what and how>]\n\n"
        "STRICT RULES:\n"
        "- All 5 sections MUST be present (MECHANISM, INTERVENTION, MEASUREMENT, SUCCESS CRITERION, CONTROL)\n"
        "- MECHANISM must define a named VARIABLE (e.g. 'VARIABLE: V = metric()')\n"
        "- MEASUREMENT must reference that same variable name\n"
        "- SUCCESS CRITERION must threshold that same variable name with a number\n"
        "- INTERVENTION must describe synthetic data generation (distribution, numpy, scipy)\n"
        "- CONTROL must name 1-2 confounders and how they are held constant\n"
        "- MEASUREMENT must be a single scalar (no qualitative descriptions)\n"
        "- No explanations, no extra text outside the 5 sections\n\n"
        f"INPUT:\n{original}"
    )
    try:
        raw = await ctx.agent._think(
            prompt,
            system="You strictly format experimental specifications.",
            json_mode=False,
            temperature=0.1,
        )
        if raw:
            reformatted = raw.strip()
            if parse_experiment_spec(reformatted) is not None:
                return reformatted
            print(f"[EXPERIMENT_DESIGN] FORCE_REWRITE: model output failed parse — hard fail")
    except Exception as _e:
        print(f"[EXPERIMENT_DESIGN] FORCE_REWRITE_EXCEPTION: {_e}")
    return None


def _to_str(exp) -> str:
    """Convert any experiment spec to a stable, loggable string.

    Handles str, dict, None, and arbitrary objects safely.
    Uses json.dumps (sorted keys) for dicts to preserve structure readably.
    Never crashes.
    """
    if isinstance(exp, str):
        return exp
    if exp is None:
        return ""
    try:
        return json.dumps(exp, ensure_ascii=False, sort_keys=True)
    except Exception:
        try:
            return str(exp)
        except Exception:
            return "<unserializable_experiment>"


def _normalize_rewritten(exp) -> str:
    """Normalize the `rewritten` field from the alignment validator.

    The model sometimes returns a structured dict instead of a plain string.
    Preserve semantic content via field-by-field decomposition; fall back to
    _to_str() for unknown structures.
    """
    if isinstance(exp, str):
        return exp.strip()
    if isinstance(exp, dict):
        parts = []
        for key in ("description", "procedure", "method", "dataset", "metric",
                    "comparison", "expected_result"):
            if key in exp:
                label = "" if key == "description" else f"{key}: "
                parts.append(f"{label}{exp[key]}")
        return " | ".join(parts) if parts else _to_str(exp)
    return _to_str(exp)


def _rewrite_delta(a: str, b: str) -> float:
    """Semantic distance between two experiment specs (0.0=identical, 1.0=completely different).

    Uses SequenceMatcher ratio so it's sensitive to character-level changes
    while being robust to whitespace and minor reformulations.
    """
    if not a or not b:
        return 0.0
    return round(1.0 - SequenceMatcher(None, a, b).ratio(), 4)

# ── Calibration log (jsonl, one record per hypothesis alignment decision) ─────
_CALIB_LOG_PATH: str | None = None   # set once per process on first use

def _calib_log_path() -> str:
    global _CALIB_LOG_PATH
    if _CALIB_LOG_PATH is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        experiments_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "shard_workspace", "experiments"
        )
        os.makedirs(experiments_dir, exist_ok=True)
        _CALIB_LOG_PATH = os.path.join(experiments_dir, f"alignment_log_{ts}.jsonl")
    return _CALIB_LOG_PATH

def _calib_append(record: dict) -> None:
    """Append one JSON line to the calibration log. Non-fatal."""
    try:
        with open(_calib_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("[CALIB_LOG] write failed (non-fatal): %s", exc)

_MIN_CONFIDENCE = 0.6   # gate threshold -- hypotheses below this are SKIPPED


class ExperimentDesignPhase(BasePhase):
    """Translate hypothesis.minimum_experiment into executable sandbox Python.

    Gate conditions (all must be true):
      - ctx.research_mode is True
      - ctx.structured['hypothesis'] is present and not None
      - hypothesis['falsifiable'] is True
      - hypothesis['confidence'] >= _MIN_CONFIDENCE

    On success: writes ctx.experiment_code (str).
    On gate failure or error: writes ctx.experiment_status = 'SKIPPED'.
    """
    name  = "EXPERIMENT_DESIGN"
    fatal = False

    async def run(self, ctx: "StudyContext") -> None:
        # ── Gate ─────────────────────────────────────────────────────────────
        hypothesis = (ctx.structured or {}).get("hypothesis") if ctx.structured else None

        if not ctx.research_mode:
            print("[EXPERIMENT_DESIGN] SKIPPED (research_mode=False)")
            return

        if not hypothesis:
            ctx.experiment_status = "SKIPPED"
            logger.debug("[EXPERIMENT_DESIGN] No hypothesis in ctx.structured -- skipped")
            return

        if not hypothesis.get("falsifiable"):
            ctx.experiment_status = "SKIPPED"
            await ctx.emit("EXPERIMENT_DESIGN", 0, "Hypothesis not falsifiable -- skipped")
            _persist_skipped(ctx, hypothesis, "SKIPPED")
            return

        confidence = float(hypothesis.get("confidence", 0.0))
        if confidence < _MIN_CONFIDENCE:
            ctx.experiment_status = "SKIPPED"
            await ctx.emit(
                "EXPERIMENT_DESIGN", 0,
                f"Hypothesis confidence {confidence:.2f} < {_MIN_CONFIDENCE} -- skipped"
            )
            _persist_skipped(ctx, hypothesis, "SKIPPED")
            return

        # ── Feasibility gate ──────────────────────────────────────────────────
        # Returns: "local" | "kaggle" | "invalid"
        #   "local"   → run in sandbox as-is
        #   "kaggle"  → valid science, needs GPU/downloads; generate code anyway
        #   "invalid" → domain mismatch or nonsensical proxy; skip with no code
        try:
            feasibility = await ctx.agent._is_experiment_feasible(hypothesis)
        except Exception:
            feasibility = "local"  # non-fatal -- assume feasible on error

        if feasibility == "invalid":
            ctx.experiment_status = "SKIPPED_TOO_COMPLEX"
            await ctx.emit(
                "EXPERIMENT_DESIGN", 0,
                "Domain mismatch or unfalsifiable experiment -- SKIPPED_TOO_COMPLEX"
            )
            print(f"[EXPERIMENT_DESIGN] SKIPPED_TOO_COMPLEX (invalid) -- '{hypothesis.get('statement','')[:80]}'")
            _persist_skipped(ctx, hypothesis, "SKIPPED_TOO_COMPLEX")
            return

        # kaggle or local → always generate code
        # For "kaggle", code is written for external compute and stored in DB
        is_kaggle = (feasibility == "kaggle")
        if is_kaggle:
            await ctx.emit(
                "EXPERIMENT_DESIGN", 0,
                "Experiment needs external compute (GPU/data) -- generating Kaggle-ready code"
            )
            print(f"[EXPERIMENT_DESIGN] KAGGLE_READY -- generating code for: '{hypothesis.get('statement','')[:80]}'")

        # ── 4-section enforcement gate (deterministic, pre-validator) ──────────
        # If minimum_experiment is free-form, attempt one targeted LLM reformat.
        # If still missing sections after reformat → skip as INVALID (no validator call).
        _min_exp_raw = hypothesis.get("minimum_experiment", "") or ""
        _parsed_spec = parse_experiment_spec(_to_str(_min_exp_raw))
        _gate_had_rewrite   = False
        _gate_rewrite_ok    = False

        if _parsed_spec is None:
            _gate_had_rewrite = True
            print(f"[EXPERIMENT_DESIGN] SPEC_GATE: free-form — forcing 4-section rewrite")
            _reformatted = await _force_rewrite_experiment(_to_str(_min_exp_raw), ctx)
            if _reformatted is not None:
                _gate_rewrite_ok = True
                print(f"[EXPERIMENT_DESIGN] SPEC_GATE: reformat OK — proceeding to validator")
                hypothesis = dict(hypothesis)
                hypothesis["minimum_experiment"] = _reformatted
                _parsed_spec = parse_experiment_spec(_reformatted)
            else:
                # Hard fail — no fallback to free-form text
                print(f"[EXPERIMENT_DESIGN] SPEC_GATE: reformat FAILED — hard stop INVALID")
                print(f"[EXPERIMENT_DESIGN] SPEC_GATE_KPI parsed=False had_rewrite=True rewrite_ok=False")
                _persist_skipped(ctx, hypothesis, "INVALID_SPEC_STRUCTURE")
                return

        # Zero-LLM micro-validations on the parsed spec (binding + simulation + control)
        _min_exp_str_for_gate = _to_str(hypothesis.get("minimum_experiment", ""))
        _struct_ok, _struct_issues = validate_structure(_parsed_spec, raw_text=_min_exp_str_for_gate)
        print(f"[EXPERIMENT_DESIGN] SPEC_GATE_KPI parsed=True "
              f"had_rewrite={_gate_had_rewrite} rewrite_ok={_gate_rewrite_ok} "
              f"struct_ok={_struct_ok} issues={_struct_issues}")

        # ── Binding gate (deterministic, pre-validator) ───────────────────────
        # If metric linkage or simulation grounding is missing, force a binding-aware
        # rewrite before entering the validator — one attempt, hard fail if it doesn't
        # improve the chain. CONTROL absence is soft (logged, not blocking alone).
        _binding_issues = [i for i in _struct_issues if any(
            kw in i for kw in ("METRIC not linked", "SIMULATION not grounded", "PROXY METRIC")
        )]
        if _binding_issues:
            print(f"[EXPERIMENT_DESIGN] BINDING_GATE: {_binding_issues} — forcing binding rewrite")
            _binding_rewritten = await _force_rewrite_experiment(_min_exp_str_for_gate, ctx)
            if _binding_rewritten is not None:
                _binding_spec = parse_experiment_spec(_binding_rewritten)
                if _binding_spec is not None:
                    _binding_issues_after = [
                        i for i in validate_structure(_binding_spec, raw_text=_binding_rewritten)[1]
                        if any(kw in i for kw in ("METRIC not linked", "SIMULATION not grounded"))
                    ]
                    if not _binding_issues_after:
                        hypothesis = dict(hypothesis)
                        hypothesis["minimum_experiment"] = _binding_rewritten
                        _parsed_spec = _binding_spec
                        print(f"[EXPERIMENT_DESIGN] BINDING_GATE: rewrite resolved binding issues")
                    else:
                        print(f"[EXPERIMENT_DESIGN] BINDING_GATE: rewrite did not resolve "
                              f"— proceeding anyway (validator will score)")
                else:
                    print(f"[EXPERIMENT_DESIGN] BINDING_GATE: rewrite failed parse — proceeding with original")
            else:
                print(f"[EXPERIMENT_DESIGN] BINDING_GATE: force_rewrite returned None — proceeding with original")

        if _struct_issues:
            print(f"[EXPERIMENT_DESIGN] SPEC_GATE: micro-validation issues: {_struct_issues}")
            # Remaining issues logged; validator will penalize FA/IM accordingly

        # ── Feasibility gate (deterministic, pre-validator) ───────────────────
        # If the spec requires real-world data the sandbox cannot provide, route
        # to KAGGLE_READY instead of burning validator budget on a guaranteed fail.
        if requires_real_world_data(_parsed_spec):
            _rwd_reason = next(
                (k for k in _REAL_WORLD_FLAGS
                 if k in " ".join(_parsed_spec.values()).lower()), "real_world_data"
            )
            print(f"[EXPERIMENT_DESIGN] FEASIBILITY_GATE: REQUIRES_REAL_WORLD_DATA "
                  f"flag='{_rwd_reason}' — routing to KAGGLE_READY")
            # Treat as kaggle-ready: generate a notebook-style experiment
            is_kaggle = True
            await ctx.emit(
                "EXPERIMENT_DESIGN", 0,
                f"Feasibility gate: real-world data required ({_rwd_reason}) — KAGGLE_READY"
            )

        # ── Experiment alignment validator (LLM-based, semantic check) ────────
        # Checks that minimum_experiment actually tests the hypothesis.
        # REWRITE: replaces minimum_experiment and retries (up to MAX_REWRITES).
        # INVALID: skips entirely (proxy unrelated to hypothesis domain).
        _MAX_REWRITES = 2
        _MAX_EMPTY_RETRIES = 1   # max times we retry a REWRITE with missing payload
        _empty_retries = 0
        _alignment_ok = False
        _calib_attempts: list[dict] = []   # one entry per loop iteration
        _attempt = 0
        _coercions_count   = 0   # forced rewrites applied inside the loop
        _regressions_count = 0   # times validator broke a valid spec
        # Track last known canonical text for regression guard
        _previous_canonical_text: str | None = _to_str(hypothesis.get("minimum_experiment", ""))
        while _attempt <= _MAX_REWRITES:
            try:
                alignment = await ctx.agent._validate_experiment_alignment(hypothesis, attempt=_attempt)
            except Exception as _outer_exc:
                print(f"[EXPERIMENT_DESIGN] ALIGNMENT_OUTER_EXCEPTION attempt={_attempt}: {_outer_exc}")
                alignment = {
                    "verdict":           "VALID",       # fail open: don't block pipeline
                    "alignment_score":   None,
                    "evaluation_status": "MODEL_FAILURE",
                    "criteria":          None,
                    "issues":            [f"Outer exception: {_outer_exc}"],
                    "rewritten":         None,
                }

            _verdict    = alignment.get("verdict", "VALID")
            _score      = alignment.get("alignment_score")   # may be None (protocol failure)
            _eval_status = alignment.get("evaluation_status", "VALID")
            _issues     = alignment.get("issues", [])

            # Invariant: VALID ⇒ score must exist. Violation means the caller
            # returned a semantically incoherent dict — treat it as MODEL_FAILURE.
            if _eval_status == "VALID" and _score is None:
                print(f"[EXPERIMENT_DESIGN] INVARIANT VIOLATION attempt={_attempt}: "
                      f"eval_status=VALID but score=None — reclassifying as MODEL_FAILURE")
                _eval_status = "MODEL_FAILURE"
                _issues = list(_issues) + ["Invariant violation: VALID without score"]

            _score_safe = round(_score, 4) if _score is not None else None

            # ── Conditional IM adjustment ─────────────────────────────────────
            # If the spec explicitly declares synthetic simulation, reduce the
            # "real-world gap" penalty on implementability by a small fixed amount.
            # This does NOT raise the VALID threshold — it only corrects over-penalization
            # of genuinely sandbox-runnable experiments.
            _im_adjusted = False
            if _score is not None and alignment.get("criteria"):
                _cur_exp_for_im = _to_str(hypothesis.get("minimum_experiment", ""))
                _spec_for_im    = parse_experiment_spec(_cur_exp_for_im)
                if _spec_for_im and synthetic_declared(_spec_for_im):
                    _criteria_adj = dict(alignment["criteria"])
                    _im_raw = float(_criteria_adj.get("implementability", 0.0))
                    _im_new = min(1.0, _im_raw + 0.05)
                    if _im_new != _im_raw:
                        _criteria_adj["implementability"] = round(_im_new, 4)
                        alignment = dict(alignment)
                        alignment["criteria"] = _criteria_adj
                        # Recompute alignment_score as average of adjusted criteria
                        _crit_vals = [float(v) for v in _criteria_adj.values()]
                        _new_score = sum(_crit_vals) / len(_crit_vals)
                        alignment["alignment_score"] = round(_new_score, 4)
                        _score      = alignment["alignment_score"]
                        _score_safe = round(_score, 4)
                        _im_adjusted = True
                        print(f"[EXPERIMENT_DESIGN] IM_ADJUSTMENT attempt={_attempt} "
                              f"im {_im_raw:.3f}→{_im_new:.3f} "
                              f"score→{_score_safe:.3f} (synthetic declared)")

            # ── Structural audit of the 4-section template ────────────────────
            _cur_exp_str  = _to_str(hypothesis.get("minimum_experiment", ""))
            _cur_spec     = parse_experiment_spec(_cur_exp_str)
            _sections_ok  = _cur_spec is not None
            _has_mechanism  = _sections_ok and bool(_cur_spec.get("mechanism"))
            _has_interv     = _sections_ok and bool(_cur_spec.get("intervention"))
            _has_measure    = _sections_ok and bool(_cur_spec.get("measurement"))
            _has_criterion  = _sections_ok and bool(_cur_spec.get("success_criterion"))
            _meas_len     = len(_cur_exp_str)
            _has_threshold = _sections_ok and _has_numeric_threshold(_cur_spec.get("success_criterion", ""))

            _calib_attempts.append({
                "attempt":          _attempt,
                "score":            _score_safe,
                "verdict":          _verdict,
                "evaluation_status": _eval_status,
                "issues":           _issues,
                "criteria":         alignment.get("criteria") or {},
                "sections_ok":      _sections_ok,
                "has_mechanism":    _has_mechanism,
                "has_intervention": _has_interv,
                "has_measurement":  _has_measure,
                "has_criterion":    _has_criterion,
                "exp_len":          _meas_len,
                "has_threshold":    _has_threshold,
                "im_adjusted":      _im_adjusted,
            })

            # Protocol failure (INVALID_FORMAT / MODEL_FAILURE): fail open, log and continue
            if _eval_status in ("INVALID_FORMAT", "MODEL_FAILURE"):
                print(f"[EXPERIMENT_DESIGN] ALIGNMENT_{_eval_status} attempt={_attempt} "
                      f"— failing open, proceeding to code generation")
                _alignment_ok = True
                break

            if _verdict == "VALID":
                _alignment_ok = True
                if _attempt > 0:
                    print(f"[EXPERIMENT_DESIGN] ALIGNMENT_VALID after {_attempt} rewrite(s) "
                          f"(score={_score:.2f})")
                break

            if _verdict == "REWRITE":
                _rewritten_raw = alignment.get("rewritten")
                _rewrite_len = len(str(_rewritten_raw)) if _rewritten_raw else 0
                print(f"[EXPERIMENT_DESIGN] ALIGNMENT_REWRITE_LEN attempt={_attempt} rewrite_len={_rewrite_len}")

                if not _rewritten_raw and _empty_retries < _MAX_EMPTY_RETRIES:
                    # Invariant: REWRITE ⇒ rewritten MUST exist.
                    # Retry the same attempt without incrementing _attempt.
                    _empty_retries += 1
                    print(f"[EXPERIMENT_DESIGN] REWRITE_EMPTY attempt={_attempt} "
                          f"(empty_retry {_empty_retries}/{_MAX_EMPTY_RETRIES}) — retrying same attempt")
                    continue  # do NOT increment _attempt

                if _rewritten_raw and _attempt < _MAX_REWRITES:
                    old_exp_str  = _to_str(hypothesis.get("minimum_experiment", ""))
                    _rewritten   = _normalize_rewritten(_rewritten_raw)

                    # ── SEMANTIC DRIFT CHECK (log only, don't block) ──────────
                    _old_spec = parse_experiment_spec(old_exp_str)
                    _new_spec = parse_experiment_spec(_rewritten)
                    if _old_spec and _new_spec:
                        _old_mech = _old_spec.get("mechanism", "")
                        _new_mech = _new_spec.get("mechanism", "")
                        _drift_ratio = SequenceMatcher(None, _old_mech, _new_mech).ratio()
                        if _drift_ratio < 0.6:
                            print(f"[EXPERIMENT_DESIGN] SEMANTIC_DRIFT attempt={_attempt} "
                                  f"mech_similarity={_drift_ratio:.2f} — mechanism may have shifted")
                            # Log into the current calib attempt if it exists
                            if _calib_attempts:
                                _calib_attempts[-1]["semantic_drift"] = round(_drift_ratio, 3)

                    # ── GATE RE-APPLICATION (invariant: every min_exp entering
                    # the validator must be canonical 4-section) ────────────────
                    _rw_spec = parse_experiment_spec(_rewritten)
                    if _rw_spec is None:
                        # Regression guard: if previous was canonical, log it
                        if _previous_canonical_text and parse_experiment_spec(_previous_canonical_text) is not None:
                            _regressions_count += 1
                            print(f"[EXPERIMENT_DESIGN] SPEC_REGRESSION attempt={_attempt} "
                                  f"(validator broke canonical spec) regressions={_regressions_count}")
                        # One coercion attempt — sterile prompt
                        _coerced = await _force_rewrite_experiment(_rewritten, ctx)
                        _coerced_spec = parse_experiment_spec(_coerced) if _coerced else None
                        if _coerced_spec is not None:
                            _coercions_count += 1
                            _rewritten = _coerced
                            print(f"[EXPERIMENT_DESIGN] SPEC_GATE_KPI "
                                  f"stage=validator_rewrite parsed=False rewrite_ok=True "
                                  f"coercions={_coercions_count}")
                        else:
                            # Hard fail — propagating free-form would recreate the leak
                            print(f"[EXPERIMENT_DESIGN] SPEC_GATE_KPI "
                                  f"stage=validator_rewrite parsed=False rewrite_ok=False — hard stop")
                            _alignment_ok = False
                            break
                    else:
                        print(f"[EXPERIMENT_DESIGN] SPEC_GATE_KPI "
                              f"stage=validator_rewrite parsed=True rewrite_ok=True")
                    _previous_canonical_text = _rewritten
                    # ── /GATE ─────────────────────────────────────────────────

                    _delta       = _rewrite_delta(old_exp_str, _rewritten)
                    _prev_score  = _calib_attempts[-2]["score"] if len(_calib_attempts) >= 2 else None
                    _score_delta = round(_score - _prev_score, 4) if (
                        _score is not None and _prev_score is not None
                    ) else None
                    hypothesis = dict(hypothesis)  # don't mutate original
                    hypothesis["minimum_experiment"] = _rewritten
                    score_str = f"{_score:.2f}" if _score is not None else "?"
                    print(f"[EXPERIMENT_DESIGN] ALIGNMENT_REWRITE attempt={_attempt+1}/{_MAX_REWRITES} "
                          f"score={score_str} delta={_delta:.3f} score_delta={_score_delta} "
                          f"-- '{old_exp_str[:50]}' -> '{_rewritten[:50]}'")
                    await ctx.emit("EXPERIMENT_DESIGN", 0,
                                   f"minimum_experiment rewritten (attempt {_attempt+1}) "
                                   f"score={score_str} delta={_delta:.3f}")
                    # patch last calib entry with rewrite diagnostics
                    if _calib_attempts:
                        _calib_attempts[-1]["rewrite_len"]   = len(_rewritten)
                        _calib_attempts[-1]["rewrite_delta"] = _delta
                        _calib_attempts[-1]["score_delta"]   = _score_delta
                    _empty_retries = 0   # reset for next attempt
                    _attempt += 1
                    continue

            # INVALID verdict, or REWRITE with no rewritten text, or rewrites exhausted
            ctx.experiment_status = "SKIPPED_TOO_COMPLEX"
            issues_str = "; ".join(_issues) if isinstance(_issues, list) else str(_issues)
            score_str  = f"{_score:.2f}" if _score is not None else "?"
            reason = (
                f"INVALID (score={score_str}): {issues_str}" if _verdict == "INVALID"
                else f"REWRITE loop exhausted after {_attempt} attempt(s): {issues_str}"
            )
            # ── Calibration record (failed path) ─────────────────────────────
            _calib_append({
                "ts":               time.strftime("%Y-%m-%dT%H:%M:%S"),
                "hypothesis":       (hypothesis.get("statement", "") or "")[:100],
                "domain_from":      hypothesis.get("domain_from", ""),
                "domain_to":        hypothesis.get("domain_to", ""),
                "kaggle_feasible":  is_kaggle,
                "attempts":         _calib_attempts,
                "num_rewrites":     _attempt,
                "final_verdict":    "INVALID" if _verdict == "INVALID" else "REWRITE_EXHAUSTED",
                "domain_blocked":   getattr(ctx, "domain_pairs_blocked", None) or [],
                "coercions_count":  _coercions_count,
                "regressions_count": _regressions_count,
            })
            await ctx.emit("EXPERIMENT_DESIGN", 0,
                           f"Alignment check failed -- SKIPPED ({reason[:100]})")
            print(f"[EXPERIMENT_DESIGN] ALIGNMENT_FAILED -- {reason[:140]}")
            _persist_skipped(ctx, hypothesis, "SKIPPED_TOO_COMPLEX")
            return

        if not _alignment_ok:
            # Shouldn't reach here, but guard anyway
            ctx.experiment_status = "SKIPPED_TOO_COMPLEX"
            _persist_skipped(ctx, hypothesis, "SKIPPED_TOO_COMPLEX")
            return

        # ── Calibration record (success path) ────────────────────────────────
        _calib_append({
            "ts":               time.strftime("%Y-%m-%dT%H:%M:%S"),
            "hypothesis":       (hypothesis.get("statement", "") or "")[:100],
            "domain_from":      hypothesis.get("domain_from", ""),
            "domain_to":        hypothesis.get("domain_to", ""),
            "kaggle_feasible":  is_kaggle,
            "attempts":         _calib_attempts,
            "num_rewrites":     len(_calib_attempts) - 1,
            "final_verdict":    "VALID",
            "domain_blocked":   getattr(ctx, "domain_pairs_blocked", None) or [],
            "coercions_count":  _coercions_count,
            "regressions_count": _regressions_count,
        })

        # ── Generate code ─────────────────────────────────────────────────────
        await ctx.emit("EXPERIMENT_DESIGN", 0, f"Designing experiment for: '{hypothesis.get('statement','')[:60]}...'")
        try:
            code = await ctx.agent._generate_experiment_code(hypothesis, kaggle_mode=is_kaggle)
            if not code or not code.strip():
                ctx.experiment_status = "SKIPPED"
                logger.warning("[EXPERIMENT_DESIGN] LLM returned empty code -- skipped")
                return
            ctx.experiment_code = code
            if is_kaggle:
                ctx.experiment_status = "KAGGLE_READY"
                # Persist immediately — no sandbox execution follows
                _persist_kaggle_ready(ctx, hypothesis, code)
                await ctx.emit("EXPERIMENT_DESIGN", 0,
                               f"Kaggle-ready code generated ({len(code)} chars) -- persisted to DB")
                print(f"[EXPERIMENT_DESIGN] KAGGLE_READY code saved for: '{hypothesis.get('statement','')[:80]}'")
                return
            await ctx.emit("EXPERIMENT_DESIGN", 0, f"Experiment code generated ({len(code)} chars)")
            print(f"[EXPERIMENT_DESIGN] Code preview:\n{code[:300]}...")
        except Exception as exc:
            ctx.experiment_status = "SKIPPED"
            logger.error("[EXPERIMENT_DESIGN] Code generation failed: %s", exc)
            await ctx.emit("EXPERIMENT_DESIGN", 0, f"Code generation failed: {exc} -- skipped")


def _persist_kaggle_ready(ctx, hypothesis: dict, code: str) -> None:
    """Persist a hypothesis whose experiment code targets Kaggle/GPU (KAGGLE_READY).

    Saves the generated code so it can be retrieved via get_kaggle_ready().
    Non-fatal -- errors are logged and swallowed.
    """
    try:
        from experiment_store import store_hypothesis, update_result
        source_papers = [
            {"title": s.get("title", ""), "year": s.get("year", ""), "url": s.get("url", "")}
            for s in (ctx.sources or [])
            if s.get("title")
        ] if ctx.research_mode else None
        hyp_id = store_hypothesis(ctx.topic, hypothesis, source_papers=source_papers)
        if hyp_id:
            update_result(
                hypothesis_id=hyp_id,
                status="KAGGLE_READY",
                experiment_code=code,
                experiment_result=None,
                confidence_updated=hypothesis.get("confidence", 0.0),
            )
            ctx._experiment_hypothesis_id = hyp_id
            print(f"[EXPERIMENT_DESIGN] Persisted KAGGLE_READY id={hyp_id}")
    except Exception as db_exc:
        logger.error("[EXPERIMENT_DESIGN] DB persist (kaggle) failed (non-fatal): %s", db_exc)


def _persist_skipped(ctx, hypothesis: dict, status: str) -> None:
    """Persist a hypothesis that was skipped before sandbox execution.

    Called for SKIPPED (not falsifiable / low confidence) and
    SKIPPED_TOO_COMPLEX (needs external resources).
    Non-fatal -- errors are logged and swallowed.
    """
    try:
        from experiment_store import store_hypothesis, update_result
        source_papers = [
            {"title": s.get("title", ""), "year": s.get("year", ""), "url": s.get("url", "")}
            for s in (ctx.sources or [])
            if s.get("title")
        ] if ctx.research_mode else None
        hyp_id = store_hypothesis(ctx.topic, hypothesis, source_papers=source_papers)
        if hyp_id:
            update_result(
                hypothesis_id=hyp_id,
                status=status,
                experiment_code=None,
                experiment_result=None,
                confidence_updated=hypothesis.get("confidence", 0.0),
            )
            ctx._experiment_hypothesis_id = hyp_id
            print(f"[EXPERIMENT_DESIGN] Persisted id={hyp_id} status={status}")
    except Exception as db_exc:
        logger.error("[EXPERIMENT_DESIGN] DB persist failed (non-fatal): %s", db_exc)


class ExperimentSandboxPhase(BasePhase):
    """Execute experiment_code in Docker sandbox (DockerSandboxRunner, zero modifications).

    Gate conditions:
      - ctx.experiment_status != 'SKIPPED'
      - ctx.experiment_code is not None

    On success: writes ctx.experiment_result {success, stdout, stderr, exit_code}.
    On gate failure or error: logs and returns (experiment_status unchanged).
    """
    name  = "EXPERIMENT_SANDBOX"
    fatal = False

    async def run(self, ctx: "StudyContext") -> None:
        # ── Gate ─────────────────────────────────────────────────────────────
        if not ctx.research_mode:
            print("[EXPERIMENT_SANDBOX] SKIPPED (research_mode=False)")
            return

        if ctx.experiment_status in ("SKIPPED", "KAGGLE_READY") or not ctx.experiment_code:
            return

        # ── Execute ───────────────────────────────────────────────────────────
        await ctx.emit("EXPERIMENT_SANDBOX", 0, "Running experiment in Docker sandbox...")
        try:
            import os as _os
            from sandbox_runner import DockerSandboxRunner
            _sandbox_dir = getattr(ctx.agent, "sandbox_dir", None) or _os.path.join(_os.getcwd(), "sandbox")
            runner = DockerSandboxRunner(
                sandbox_dir=_sandbox_dir,
                analysis_fn=None,   # no LLM analysis -- ExperimentValidatePhase handles it
            )
            result = await runner.run(
                topic=f"[EXPERIMENT] {ctx.topic}",
                code=ctx.experiment_code,
                progress=ctx.progress,
            )
            ctx.experiment_result = {
                "success":   result.get("success", False),
                "stdout":    result.get("stdout", ""),
                "stderr":    result.get("stderr", ""),
                "exit_code": 0 if result.get("success") else 1,
            }
            status_icon = "OK" if result.get("success") else "FAIL"
            await ctx.emit(
                "EXPERIMENT_SANDBOX", 0,
                f"Sandbox [{status_icon}] -- stdout: {result.get('stdout','')[:80]}"
            )
        except Exception as exc:
            logger.error("[EXPERIMENT_SANDBOX] Sandbox execution failed: %s", exc)
            ctx.experiment_result = {
                "success": False, "stdout": "", "stderr": str(exc), "exit_code": -1
            }
            await ctx.emit("EXPERIMENT_SANDBOX", 0, f"Sandbox error: {exc}")


class ExperimentValidatePhase(BasePhase):
    """LLM interprets sandbox output and decides CONFIRMED/REFUTED/INCONCLUSIVE.

    Gate conditions:
      - ctx.experiment_result is not None

    On success:
      - writes ctx.experiment_status (CONFIRMED/REFUTED/INCONCLUSIVE)
      - writes ctx.hypothesis_confidence_updated
      - persists to DB via ExperimentStore
    """
    name  = "EXPERIMENT_VALIDATE"
    fatal = False

    async def run(self, ctx: "StudyContext") -> None:
        # ── Gate ─────────────────────────────────────────────────────────────
        if not ctx.research_mode:
            print("[EXPERIMENT_VALIDATE] SKIPPED (research_mode=False)")
            return

        if ctx.experiment_result is None:
            return

        hypothesis = (ctx.structured or {}).get("hypothesis")
        if not hypothesis:
            return

        # ── Validate ──────────────────────────────────────────────────────────
        await ctx.emit("EXPERIMENT_VALIDATE", 0, "Interpreting experiment result...")
        try:
            stdout = ctx.experiment_result.get("stdout", "")
            stderr = ctx.experiment_result.get("stderr", "")

            verdict = await ctx.agent._validate_experiment_result(hypothesis, stdout, stderr)

            ctx.experiment_status           = verdict.get("status", "INCONCLUSIVE")
            ctx.hypothesis_confidence_updated = float(verdict.get("confidence_updated", hypothesis.get("confidence", 0.0)))

            await ctx.emit(
                "EXPERIMENT_VALIDATE", 0,
                f"Verdict: {ctx.experiment_status} | "
                f"confidence {hypothesis.get('confidence', 0.0):.2f} -> {ctx.hypothesis_confidence_updated:.2f} | "
                f"{verdict.get('reasoning','')[:80]}"
            )
            print(f"[EXPERIMENT_VALIDATE] {ctx.experiment_status} | reasoning: {verdict.get('reasoning','')}")

        except Exception as exc:
            ctx.experiment_status = "INCONCLUSIVE"
            ctx.hypothesis_confidence_updated = hypothesis.get("confidence", 0.0)
            logger.error("[EXPERIMENT_VALIDATE] Validation failed: %s", exc)
            await ctx.emit("EXPERIMENT_VALIDATE", 0, f"Validation error: {exc} -- set INCONCLUSIVE")

        # ── Persist to DB ─────────────────────────────────────────────────────
        try:
            from experiment_store import store_hypothesis, update_result

            # Store if not already persisted (first run for this topic/hypothesis)
            existing_id = getattr(ctx, "_experiment_hypothesis_id", None)
            if existing_id is None:
                source_papers = [
                    {"title": s.get("title", ""), "year": s.get("year", ""), "url": s.get("url", "")}
                    for s in (ctx.sources or [])
                    if s.get("title")
                ] if ctx.research_mode else None

                existing_id = store_hypothesis(ctx.topic, hypothesis, source_papers=source_papers)
                ctx._experiment_hypothesis_id = existing_id

            if existing_id:
                update_result(
                    hypothesis_id     = existing_id,
                    status            = ctx.experiment_status,
                    experiment_code   = ctx.experiment_code,
                    experiment_result = ctx.experiment_result,
                    confidence_updated= ctx.hypothesis_confidence_updated,
                )
                print(f"[EXPERIMENT_VALIDATE] Persisted id={existing_id} status={ctx.experiment_status}")
        except Exception as db_exc:
            logger.error("[EXPERIMENT_VALIDATE] DB persist failed (non-fatal): %s", db_exc)
