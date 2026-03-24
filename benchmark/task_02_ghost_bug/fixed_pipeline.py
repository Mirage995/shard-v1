"""fixed_pipeline.py — Fixed version of the Ghost Bug pipeline."""
from copy import deepcopy
import statistics

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


def validate_readings(readings, config):
    """Validate readings against sensor config. Returns list of validated readings."""
    if readings is None or not readings:
        return []
    results = []
    for reading in readings:
        r = deepcopy(reading)
        sid = r["sensor_id"]

        if sid not in config:
            r["valid"] = False
            r["error"] = "unknown_sensor"
            results.append(r)
            continue

        sensor = config[sid]
        value = r["value"]
        if not isinstance(value, (int, float)):
            r["valid"] = False
            r["error"] = "invalid_value_type"
            results.append(r)
            continue

        if sensor["min"] <= value <= sensor["max"]:
            r["valid"] = True
        else:
            r["valid"] = False
            r["error"] = "out_of_range"
        results.append(r)

    return results


def calibrate_values(validated_readings, config):
    """Apply sensor-specific calibration offsets to validated readings."""
    if validated_readings is None or not validated_readings:
        return []
    calibrated_readings = []
    for reading in validated_readings:
        r = deepcopy(reading)
        if not r.get("valid", False):
            calibrated_readings.append(r)
            continue
        sid = r["sensor_id"]
        if sid in config:
            value = r["value"]
            if not isinstance(value, (int, float)):
                calibrated_readings.append(r)
                continue
            if not r.get("_calibrated", False):
                r["value"] = round(value + config[sid]["offset"], 2)
                r["_calibrated"] = True
        calibrated_readings.append(r)
    return calibrated_readings


def aggregate_by_group(calibrated_readings, config):
    """Group readings by sensor group and compute averages."""
    if calibrated_readings is None or not calibrated_readings:
        return {}

    groups = {}
    for reading in calibrated_readings:
        if not reading.get("valid"):
            continue
        sid = reading["sensor_id"]
        if sid not in config:
            continue
        group = config[sid]["group"]
        if group not in groups:
            groups[group] = {"readings": [], "sum": 0.0, "count": 0}
        groups[group]["readings"].append(reading)
        value = reading["value"]
        if isinstance(value, (int, float)):
            groups[group]["sum"] += value
            groups[group]["count"] += 1

    # Compute averages
    for group_name, data in groups.items():
        if data["count"] > 0:
            data["average"] = round(data["sum"] / data["count"], 2)
        else:
            data["average"] = 0.0

    return groups


def detect_anomalies(groups, threshold=2.0):
    """Flag readings with z-score above threshold as anomalies."""
    if groups is None or not groups:
        return []

    if not isinstance(threshold, (int, float)):
        return []

    anomalies = []
    for group_name, data in groups.items():
        values = [r["value"] for r in data["readings"] if r.get("valid")]
        if not values:
            continue
        if len(values) < 2:
            continue  # can't compute stddev with < 2 points

        try:
            mean = statistics.mean(values)
            stdev = statistics.stdev(values)
        except statistics.StatisticsError:
            continue

        if stdev == 0.0:
            continue

        for reading in data["readings"]:
            if not reading.get("valid"):
                continue
            z = abs(reading["value"] - mean) / stdev
            if z > threshold:
                anomalies.append({
                    "sensor_id": reading["sensor_id"],
                    "value": reading["value"],
                    "z_score": round(z, 2),
                    "group": group_name,
                })

    return anomalies


def generate_report(groups, anomalies):
    """Generate a plain-text summary report."""
    if groups is None:
        return "Error: Groups data is missing."
    if anomalies is None:
        return "Error: Anomalies data is missing."

    lines = ["=== Sensor Pipeline Report ===", ""]

    lines.append("--- Group Averages ---")
    for name, data in sorted(groups.items()):
        if data['count'] > 0:
            lines.append(f"  {name}: {data['average']:.2f} ({data['count']} readings)")
        else:
            lines.append(f"  {name}: No valid readings")

    lines.append("")
    lines.append("--- Anomalies Detected ---")
    if anomalies:
        for a in sorted(anomalies, key=lambda x: x["z_score"]):
            lines.append(f"  [{a['sensor_id']}] value={a['value']:.2f}, z-score={a['z_score']:.2f}")
    else:
        lines.append("  None")

    lines.append("")
    lines.append(f"Total groups: {len(groups)}")
    lines.append(f"Total anomalies: {len(anomalies)}")

    return "\n".join(lines)


def run_pipeline(readings, config):
    """Execute the full sensor processing pipeline. Returns (report, anomalies, groups)."""
    if readings is None:
        return "Error: Readings data is missing.", [], {}
    if config is None:
        return "Error: Config data is missing.", [], {}
    validated = validate_readings(readings, config)
    calibrated = calibrate_values(validated, config)
    groups = aggregate_by_group(calibrated, config)
    anomalies = detect_anomalies(groups)
    report = generate_report(groups, anomalies)
    return report, anomalies, groups


if __name__ == "__main__":
    report, anomalies, groups = run_pipeline(SAMPLE_READINGS, SENSOR_CONFIG)
    print(report)