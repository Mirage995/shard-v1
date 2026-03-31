"""analyze_snapshots.py -- Longitudinal analysis of session_snapshots.jsonl

Usage:
  cd backend && python analyze_snapshots.py
  cd backend && python analyze_snapshots.py --last 20
  cd backend && python analyze_snapshots.py --watch   (refresh every 60s)
"""
import json
import sys
import time
from pathlib import Path
from statistics import mean, stdev

SNAP_FILE = Path(__file__).parent.parent / "shard_memory" / "session_snapshots.jsonl"


def load_snapshots(last_n: int | None = None) -> list[dict]:
    if not SNAP_FILE.exists():
        return []
    lines = SNAP_FILE.read_text(encoding="utf-8").strip().splitlines()
    snaps = []
    for line in lines:
        try:
            snaps.append(json.loads(line))
        except Exception:
            continue
    snaps.sort(key=lambda x: x.get("timestamp", ""))
    if last_n:
        snaps = snaps[-last_n:]
    return snaps


def _trend(values: list[float], window: int = 5) -> str:
    if len(values) < window * 2:
        return "~"
    first = mean(values[:window])
    last  = mean(values[-window:])
    delta = last - first
    if delta > 0.05:
        return f"↑ +{delta:.3f}"
    if delta < -0.05:
        return f"↓ {delta:.3f}"
    return f"~ {delta:+.3f}"


def analyze(snaps: list[dict]):
    if not snaps:
        print("No snapshots found. Run NightRunner first.")
        return

    n = len(snaps)

    risk    = [s["risk_score"]    for s in snaps if s.get("risk_score")    is not None]
    esteem  = [s["self_esteem"]   for s in snaps if s.get("self_esteem")   is not None]
    cert    = [s["cert_rate"]     for s in snaps if s.get("cert_rate")     is not None]
    score   = [s["avg_score"]     for s in snaps if s.get("avg_score")     is not None]
    strat   = [s["strategy_reuse_rate"] for s in snaps if s.get("strategy_reuse_rate") is not None]
    perv    = sum(1 for s in snaps if s.get("perverse_emerged"))

    print("\n" + "=" * 55)
    print(f"  SHARD LONGITUDINAL ANALYSIS  |  {n} sessions")
    print("=" * 55)

    # Core metrics
    print(f"\n{'Metric':<22} {'Avg':>8} {'Std':>8} {'Trend':>12}")
    print("-" * 55)
    for label, values in [
        ("risk_score",       risk),
        ("self_esteem",      esteem),
        ("cert_rate",        cert),
        ("avg_score",        score),
        ("strategy_reuse",   strat),
    ]:
        if values:
            avg = mean(values)
            sd  = stdev(values) if len(values) > 1 else 0.0
            tr  = _trend(values)
            print(f"  {label:<20} {avg:>8.3f} {sd:>8.3f} {tr:>12}")

    # Perverse emergence
    print(f"\n  perverse_emerged:  {perv}/{n} sessions ({perv/n*100:.0f}%)")

    # Flags distribution
    flags: dict[str, int] = {}
    for s in snaps:
        for f in s.get("flags") or []:
            flags[f] = flags.get(f, 0) + 1
    if flags:
        print(f"\n  FLAGS DISTRIBUTION:")
        for k, v in sorted(flags.items(), key=lambda x: -x[1]):
            bar = "#" * v
            print(f"    {k:<22} {v:>3}x  {bar}")
    else:
        print(f"\n  FLAGS: none triggered")

    # Trend alert
    print(f"\n  HEALTH CHECK:")
    alerts = []
    if esteem and _trend(esteem).startswith("↓") and len(esteem) >= 10:
        alerts.append("self_esteem declining -- check over-correction loop")
    if risk and mean(risk) > 0.5:
        alerts.append(f"risk_score avg {mean(risk):.2f} > 0.5 -- persistent exploit pattern")
    if cert and _trend(cert) == "~" and len(cert) >= 20:
        alerts.append("cert_rate stagnant -- learning loop may be blocked")
    if flags and max(flags.values()) == n:
        alerts.append(f"flag '{max(flags, key=flags.get)}' fires every session -- overfitting")
    if alerts:
        for a in alerts:
            print(f"    ⚠  {a}")
    else:
        print(f"    OK  no anomalies detected")

    # Last 5 sessions
    print(f"\n  LAST 5 SESSIONS:")
    print(f"  {'#':<4} {'timestamp':<22} {'risk':>6} {'esteem':>7} {'cert':>6} {'perv':>5}")
    print("  " + "-" * 52)
    for i, s in enumerate(snaps[-5:]):
        ts   = s.get("timestamp", "")[:19]
        r    = s.get("risk_score")
        e    = s.get("self_esteem")
        c    = s.get("cert_rate")
        p    = "YES" if s.get("perverse_emerged") else "-"
        r_s  = f"{r:.2f}" if r is not None else "  -"
        e_s  = f"{e:.2f}" if e is not None else "  -"
        c_s  = f"{c:.2f}" if c is not None else "  -"
        print(f"  {n - 4 + i:<4} {ts:<22} {r_s:>6} {e_s:>7} {c_s:>6} {p:>5}")

    print()


if __name__ == "__main__":
    watch_mode = "--watch" in sys.argv
    last_n = None
    for i, arg in enumerate(sys.argv):
        if arg == "--last" and i + 1 < len(sys.argv):
            last_n = int(sys.argv[i + 1])

    if watch_mode:
        print("Watch mode -- refreshing every 60s. Ctrl+C to stop.")
        while True:
            snaps = load_snapshots(last_n)
            analyze(snaps)
            try:
                time.sleep(60)
            except KeyboardInterrupt:
                break
    else:
        snaps = load_snapshots(last_n)
        analyze(snaps)
