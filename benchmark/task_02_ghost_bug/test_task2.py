"""test_task2.py — The Ghost Bug Benchmark.

Tests that fixed_pipeline.py correctly fixes ALL runtime bugs
in buggy_pipeline.py without changing the pipeline's semantics.

Exit Code 0 = SHARD wins.
Exit Code 1 = keep trying.

Run:  pytest test_task2.py -v
"""
import copy
import sys
from pathlib import Path

import pytest

# Ensure the task directory is importable
TASK_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TASK_DIR))

from buggy_pipeline import SAMPLE_READINGS, SENSOR_CONFIG


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def fixed_module():
    """Import the fixed module — must exist at fixed_pipeline.py."""
    spec_path = TASK_DIR / "fixed_pipeline.py"
    if not spec_path.exists():
        pytest.fail(
            f"fixed_pipeline.py not found at {spec_path}\n"
            "Create this file by fixing all bugs in buggy_pipeline.py."
        )
    import importlib
    if "fixed_pipeline" in sys.modules:
        del sys.modules["fixed_pipeline"]
    return importlib.import_module("fixed_pipeline")


@pytest.fixture
def fresh_readings():
    """Deep copy of SAMPLE_READINGS to prevent cross-test mutation."""
    return copy.deepcopy(SAMPLE_READINGS)


@pytest.fixture
def fresh_config():
    """Deep copy of SENSOR_CONFIG."""
    return copy.deepcopy(SENSOR_CONFIG)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 1: THE PIPELINE MUST NOT CRASH
# ══════════════════════════════════════════════════════════════════════════════

class TestNoCrash:
    """The fixed pipeline must run without any exceptions."""

    def test_pipeline_runs(self, fixed_module, fresh_readings, fresh_config):
        """The full pipeline must complete without crashing."""
        try:
            report, anomalies, groups = fixed_module.run_pipeline(
                fresh_readings, fresh_config
            )
        except Exception as e:
            pytest.fail(f"Pipeline crashed: {type(e).__name__}: {e}")

    def test_pipeline_returns_correct_types(self, fixed_module, fresh_readings, fresh_config):
        """Pipeline must return (str, list, dict)."""
        report, anomalies, groups = fixed_module.run_pipeline(
            fresh_readings, fresh_config
        )
        assert isinstance(report, str), f"Report should be str, got {type(report)}"
        assert isinstance(anomalies, list), f"Anomalies should be list, got {type(anomalies)}"
        assert isinstance(groups, dict), f"Groups should be dict, got {type(groups)}"

    def test_buggy_pipeline_crashes(self):
        """Verify the original buggy_pipeline DOES crash (sanity check)."""
        from buggy_pipeline import run_pipeline
        readings = copy.deepcopy(SAMPLE_READINGS)
        config = copy.deepcopy(SENSOR_CONFIG)
        with pytest.raises(Exception):
            run_pipeline(readings, config)


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 2: BUG FIXES — each bug must be specifically fixed
# ══════════════════════════════════════════════════════════════════════════════

class TestBugFixes:
    """Each specific bug must be fixed."""

    def test_no_mutation_of_input(self, fixed_module, fresh_config):
        """Bug 1: validate_readings must NOT mutate the original readings."""
        readings = copy.deepcopy(SAMPLE_READINGS)
        original = copy.deepcopy(readings)
        fixed_module.validate_readings(readings, fresh_config)
        assert readings == original, (
            "validate_readings mutated the original readings list! "
            "Use deepcopy instead of shallow copy."
        )

    def test_calibration_idempotent(self, fixed_module, fresh_readings, fresh_config):
        """Bug 2: Calling calibrate twice must not apply offset twice."""
        validated = fixed_module.validate_readings(fresh_readings, fresh_config)
        calibrated_once = fixed_module.calibrate_values(
            copy.deepcopy(validated), fresh_config
        )
        calibrated_twice = fixed_module.calibrate_values(
            copy.deepcopy(calibrated_once), fresh_config
        )

        # Get values from valid readings
        for r1, r2 in zip(calibrated_once, calibrated_twice):
            if r1.get("valid"):
                assert r1["value"] == r2["value"], (
                    f"Calibration is not idempotent for {r1['sensor_id']}: "
                    f"first={r1['value']}, second={r2['value']}. "
                    f"The offset is being applied multiple times!"
                )

    def test_invalid_readings_excluded_from_averages(self, fixed_module, fresh_readings, fresh_config):
        """Bug 3: Invalid readings must NOT be included in group averages."""
        report, anomalies, groups = fixed_module.run_pipeline(
            fresh_readings, fresh_config
        )

        # temp_02 has one valid (23.1) and one invalid (150.0, out of range)
        # Only the valid one should be in the average
        temp_group = groups["temperature"]
        # Valid temp readings: temp_01 (22.5, 22.8, 22.6) and temp_02 (23.1 only)
        # After calibration with offsets: temp_01 offset=-0.3, temp_02 offset=0.1
        # temp_01: 22.2, 22.5, 22.3 | temp_02: 23.2
        # Average: (22.2 + 22.5 + 22.3 + 23.2) / 4 = 22.55
        valid_count = sum(
            1 for r in temp_group["readings"] if r.get("valid", False)
        )
        assert temp_group["count"] == valid_count, (
            f"Temperature group count includes invalid readings: "
            f"count={temp_group['count']}, valid={valid_count}"
        )

    def test_detect_anomalies_correct_key(self, fixed_module, fresh_readings, fresh_config):
        """Bug 4: detect_anomalies must use 'value' not 'calibrated_value'."""
        validated = fixed_module.validate_readings(fresh_readings, fresh_config)
        calibrated = fixed_module.calibrate_values(
            copy.deepcopy(validated), fresh_config
        )
        groups = fixed_module.aggregate_by_group(calibrated, fresh_config)
        # This must not crash with KeyError: 'calibrated_value'
        try:
            anomalies = fixed_module.detect_anomalies(groups)
        except KeyError as e:
            pytest.fail(
                f"detect_anomalies crashed with KeyError: {e}. "
                f"Check that you're using the correct dict key for values."
            )

    def test_report_correct_keys(self, fixed_module, fresh_readings, fresh_config):
        """Bug 5: generate_report must use correct dict keys."""
        report, anomalies, groups = fixed_module.run_pipeline(
            fresh_readings, fresh_config
        )
        # Report must contain group averages without KeyError
        assert "Group Averages" in report, "Report missing 'Group Averages' section"
        assert "temperature" in report, "Report missing temperature group"
        assert "humidity" in report, "Report missing humidity group"
        assert "pressure" in report, "Report missing pressure group"
        assert "Total groups: 3" in report, "Report should show 3 groups"


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 3: SEMANTIC CORRECTNESS — the pipeline must produce right values
# ══════════════════════════════════════════════════════════════════════════════

class TestSemanticCorrectness:
    """The fixed pipeline must produce mathematically correct results."""

    def test_validation_counts(self, fixed_module, fresh_readings, fresh_config):
        """Correct number of valid and invalid readings."""
        validated = fixed_module.validate_readings(fresh_readings, fresh_config)
        valid = [r for r in validated if r.get("valid")]
        invalid = [r for r in validated if not r.get("valid")]
        # 12 total readings, 1 unknown sensor, 1 out of range = 10 valid
        assert len(valid) == 10, f"Expected 10 valid readings, got {len(valid)}"
        assert len(invalid) == 2, f"Expected 2 invalid readings, got {len(invalid)}"

    def test_calibration_values(self, fixed_module, fresh_readings, fresh_config):
        """Calibrated values must have correct offsets applied exactly once."""
        validated = fixed_module.validate_readings(fresh_readings, fresh_config)
        calibrated = fixed_module.calibrate_values(copy.deepcopy(validated), fresh_config)

        # Find temp_01's first reading: 22.5 + offset(-0.3) = 22.2
        temp01_first = next(
            r for r in calibrated
            if r["sensor_id"] == "temp_01" and r.get("valid")
        )
        assert temp01_first["value"] == 22.2, (
            f"temp_01 calibration wrong: expected 22.2 (22.5 + -0.3), got {temp01_first['value']}"
        )

    def test_group_averages(self, fixed_module, fresh_readings, fresh_config):
        """Group averages must be mathematically correct."""
        report, anomalies, groups = fixed_module.run_pipeline(
            fresh_readings, fresh_config
        )

        # Pressure: pres_01 readings 1013.25 and 1013.50, offset +2.0
        # Calibrated: 1015.25, 1015.50 → average 1015.375 → round to 1015.38
        pres_avg = groups["pressure"]["average"]
        assert pres_avg == 1015.38, (
            f"Pressure average wrong: expected 1015.38, got {pres_avg}"
        )

    def test_three_groups_present(self, fixed_module, fresh_readings, fresh_config):
        """Pipeline must produce exactly 3 groups."""
        report, anomalies, groups = fixed_module.run_pipeline(
            fresh_readings, fresh_config
        )
        assert set(groups.keys()) == {"temperature", "humidity", "pressure"}, (
            f"Expected groups {{temperature, humidity, pressure}}, got {set(groups.keys())}"
        )

    def test_report_not_empty(self, fixed_module, fresh_readings, fresh_config):
        """Report must have actual content."""
        report, anomalies, groups = fixed_module.run_pipeline(
            fresh_readings, fresh_config
        )
        assert len(report) > 100, f"Report too short ({len(report)} chars)"
        assert "Sensor Pipeline Report" in report

    def test_idempotent_pipeline_runs(self, fixed_module, fresh_config):
        """Running pipeline twice with same input must produce same output."""
        r1 = copy.deepcopy(SAMPLE_READINGS)
        r2 = copy.deepcopy(SAMPLE_READINGS)

        report1, anom1, groups1 = fixed_module.run_pipeline(r1, fresh_config)
        report2, anom2, groups2 = fixed_module.run_pipeline(r2, copy.deepcopy(SENSOR_CONFIG))

        assert report1 == report2, "Pipeline is not idempotent — produces different reports on same input"


# ══════════════════════════════════════════════════════════════════════════════
# GROUP 4: STRUCTURAL QUALITY
# ══════════════════════════════════════════════════════════════════════════════

class TestStructure:
    """The fix must maintain the pipeline's modular structure."""

    def test_has_all_functions(self, fixed_module):
        """All 6 pipeline functions must exist."""
        required = [
            "validate_readings", "calibrate_values", "aggregate_by_group",
            "detect_anomalies", "generate_report", "run_pipeline",
        ]
        for name in required:
            assert hasattr(fixed_module, name), (
                f"Missing function: {name}. Fix the bugs, don't rewrite the architecture."
            )

    def test_no_try_except_suppression(self):
        """The fix must not just wrap everything in try/except and ignore errors."""
        source = (TASK_DIR / "fixed_pipeline.py").read_text(encoding="utf-8")
        # Count bare except or except Exception with pass
        import re
        suppressed = re.findall(r"except.*:\s*\n\s*(pass|continue)\s*\n", source)
        assert len(suppressed) <= 1, (
            f"Found {len(suppressed)} suppressed exceptions. "
            f"Fix the bugs properly, don't just catch and ignore them."
        )


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short"]))
