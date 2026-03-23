"""buggy_pipeline.py — The Ghost Bug.

A data processing pipeline that looks correct on static analysis
but crashes at runtime due to subtle state mutation and ordering bugs.

The pipeline processes sensor readings from an IoT system:
  1. Validates raw readings
  2. Calibrates values using sensor-specific offsets
  3. Aggregates by sensor group
  4. Detects anomalies via z-score
  5. Generates a summary report

EVERY function looks correct. The bugs are in the INTERACTIONS between them.
The agent must run the code, read the tracebacks, and fix the root causes.
"""
from copy import copy

# ── Sensor configuration ──────────────────────────────────────────────────────

SENSOR_CONFIG = {
    "temp_01": {"group": "temperature", "unit": "°C", "offset": -0.3, "min": -40, "max": 120},
    "temp_02": {"group": "temperature", "unit": "°C", "offset": 0.1, "min": -40, "max": 120},
    "hum_01":  {"group": "humidity",    "unit": "%",  "offset": -1.2, "min": 0,   "max": 100},
    "hum_02":  {"group": "humidity",    "unit": "%",  "offset": 0.5,  "min": 0,   "max": 100},
    "pres_01": {"group": "pressure",    "unit": "hPa","offset": 2.0,  "min": 800, "max": 1200},
}

# ── Sample data ───────────────────────────────────────────────────────────────

SAMPLE_READINGS = [
    {"sensor_id": "temp_01", "value": 22.5, "timestamp": 1000},
    {"sensor_id": "temp_02", "value": 23.1, "timestamp": 1001},
    {"sensor_id": "hum_01",  "value": 65.0, "timestamp": 1002},
    {"sensor_id": "hum_02",  "value": 63.5, "timestamp": 1003},
    {"sensor_id": "pres_01", "value": 1013.25, "timestamp": 1004},
    {"sensor_id": "temp_01", "value": 22.8, "timestamp": 1005},
    {"sensor_id": "temp_02", "value": 150.0, "timestamp": 1006},  # out of range!
    {"sensor_id": "hum_01",  "value": 64.2, "timestamp": 1007},
    {"sensor_id": "unknown_sensor", "value": 42.0, "timestamp": 1008},  # unknown!
    {"sensor_id": "pres_01", "value": 1013.50, "timestamp": 1009},
    {"sensor_id": "temp_01", "value": 22.6, "timestamp": 1010},
    {"sensor_id": "hum_02",  "value": 64.0, "timestamp": 1011},
]


# ── Bug 1: Shallow copy mutates the original ─────────────────────────────────
# validate_readings uses copy() on each dict, but the caller reuses SAMPLE_READINGS.
# After validate_readings runs, the original dicts have an extra "valid" key.
# The second call behaves differently because the data is already mutated.

def validate_readings(readings, config):
    """Validate readings against sensor config. Returns list of validated readings."""
    results = []
    for reading in readings:
        r = copy(reading)  # BUG: shallow copy is fine for flat dicts... right?
        sid = r["sensor_id"]

        if sid not in config:
            r["valid"] = False
            r["error"] = "unknown_sensor"
            results.append(r)
            continue

        sensor = config[sid]
        if sensor["min"] <= r["value"] <= sensor["max"]:
            r["valid"] = True
        else:
            r["valid"] = False
            r["error"] = "out_of_range"
        results.append(r)

    return results


# ── Bug 2: calibrate_values modifies dicts in-place ──────────────────────────
# It receives the validated list and mutates each dict's "value" field.
# But the test calls calibrate twice (calibrate then check idempotency).
# Second calibration applies the offset AGAIN → values drift.

def calibrate_values(validated_readings, config):
    """Apply sensor-specific calibration offsets to validated readings."""
    for reading in validated_readings:
        if not reading.get("valid", False):
            continue
        sid = reading["sensor_id"]
        if sid in config:
            reading["value"] = round(reading["value"] + config[sid]["offset"], 2)
    return validated_readings


# ── Bug 3: aggregate_by_group assumes "value" exists on all readings ─────────
# Invalid readings don't have a calibrated value but still get included
# in the group aggregation, causing a division that includes None-like semantics.
# Actually the bug is subtler: invalid readings DO have "value" (the original),
# so they silently corrupt the averages.

def aggregate_by_group(calibrated_readings, config):
    """Group readings by sensor group and compute averages."""
    groups = {}
    for reading in calibrated_readings:
        sid = reading["sensor_id"]
        if sid not in config:
            continue
        group = config[sid]["group"]
        if group not in groups:
            groups[group] = {"readings": [], "sum": 0.0, "count": 0}
        groups[group]["readings"].append(reading)
        groups[group]["sum"] += reading["value"]
        groups[group]["count"] += 1

    # Compute averages
    for group_name, data in groups.items():
        data["average"] = round(data["sum"] / data["count"], 2)

    return groups


# ── Bug 4: detect_anomalies crashes on single-reading groups ──────────────────
# Z-score needs stddev, which needs at least 2 data points.
# pressure group has only 2 readings, but if one is invalid, it has 1 → crash.
# Actually with our data it has 2 valid readings, but the math module's stdev
# requires at least 2 data points. The real crash: we import statistics
# inside the function but "statistics" isn't imported at module level.
# Also: we access reading["calibrated_value"] but the key is just "value".

def detect_anomalies(groups, threshold=2.0):
    """Flag readings with z-score above threshold as anomalies."""
    import statistics

    anomalies = []
    for group_name, data in groups.items():
        values = [r["calibrated_value"] for r in data["readings"] if r.get("valid")]
        if len(values) < 2:
            continue  # can't compute stddev with < 2 points

        mean = statistics.mean(values)
        stdev = statistics.stdev(values)
        if stdev == 0:
            continue

        for reading in data["readings"]:
            if not reading.get("valid"):
                continue
            z = abs(reading["calibrated_value"] - mean) / stdev
            if z > threshold:
                anomalies.append({
                    "sensor_id": reading["sensor_id"],
                    "value": reading["calibrated_value"],
                    "z_score": round(z, 2),
                    "group": group_name,
                })

    return anomalies


# ── Bug 5: generate_report uses f-string with wrong key ──────────────────────
# The report references group["avg"] but the key is "average".
# Also, it tries to sort anomalies by "z" but the key is "z_score".

def generate_report(groups, anomalies):
    """Generate a plain-text summary report."""
    lines = ["=== Sensor Pipeline Report ===", ""]

    lines.append("--- Group Averages ---")
    for name, data in sorted(groups.items()):
        lines.append(f"  {name}: {data['avg']:.2f} ({data['count']} readings)")

    lines.append("")
    lines.append("--- Anomalies Detected ---")
    if anomalies:
        for a in sorted(anomalies, key=lambda x: x["z"]):
            lines.append(f"  [{a['sensor_id']}] value={a['value']:.2f}, z-score={a['z']:.2f}")
    else:
        lines.append("  None")

    lines.append("")
    lines.append(f"Total groups: {len(groups)}")
    lines.append(f"Total anomalies: {len(anomalies)}")

    return "\n".join(lines)


# ── Pipeline orchestrator ─────────────────────────────────────────────────────

def run_pipeline(readings, config):
    """Execute the full sensor processing pipeline. Returns (report, anomalies, groups)."""
    validated = validate_readings(readings, config)
    calibrated = calibrate_values(validated, config)
    groups = aggregate_by_group(calibrated, config)
    anomalies = detect_anomalies(groups)
    report = generate_report(groups, anomalies)
    return report, anomalies, groups


# ── Direct execution ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    report, anomalies, groups = run_pipeline(SAMPLE_READINGS, SENSOR_CONFIG)
    print(report)
