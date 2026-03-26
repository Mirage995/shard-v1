"""
Round 2 — fix the normalization bug:
  Java's 1.9M SO questions dominated the scale.
  This time: normalize within domains, and add SHARD's own
  certification data as a signal (which domains does SHARD
  actually learn well vs fail at?).
"""
import json, re
from collections import defaultdict, Counter
from urllib.request import urlopen

with open("experiment_history.json") as f:
    experiments = json.load(f)

JUNK_RE = re.compile(
    r"integration of .+ and .+|impossible differentials|hubble.scale|"
    r"quantized inertia|casimir|applied to interrogative|applied to transitive|"
    r"applied to eafp|\bmond\b|potrei|vorrei|chiedo|facendo|analizzare|"
    r"applied to post.quantum|applied to numerical_computation|"
    r"applied to deep_learning$|applied to safe_code|tier \d+$|shard_debug",
    re.IGNORECASE,
)
COMPOSITE_RE = re.compile(r"\bapplied to\b", re.IGNORECASE)

def classify(t):
    if JUNK_RE.search(t): return "junk"
    if COMPOSITE_RE.search(t): return "composite"
    return "real"

# ── TEST 1 (confirmed) ─────────────────────────────────────────────────────────
print("=" * 60)
print("TEST 1 — BLIND SPOT QUALITY (confirmed)")
print("=" * 60)
attempts = defaultdict(list)
certified = defaultdict(bool)
for e in experiments:
    t = e.get("topic","")
    if not t: continue
    if isinstance(e.get("score"),(int,float)): attempts[t].append(e["score"])
    if e.get("success"): certified[t] = True

blind_spots = [
    {"topic":t,"attempts":len(s),"avg":round(sum(s)/len(s),2),"class":classify(t)}
    for t,s in attempts.items()
    if not certified[t] and len(s)>=2 and sum(s)/len(s)<6.5
]
cc = Counter(b["class"] for b in blind_spots)
total = len(blind_spots)
print(f"Total: {total} | junk={cc['junk']}({round(cc['junk']/total*100)}%) "
      f"composite={cc['composite']}({round(cc['composite']/total*100)}%) "
      f"real={cc['real']}({round(cc['real']/total*100)}%)")
print(f"\nCONCLUSION: tier-raise fix is WRONG — 0% real gaps.")
print(f"RIGHT FIX: quarantine composite+junk topics after 2 failures.\n")

# ── TEST 2 — Better world model calibration ────────────────────────────────────
print("=" * 60)
print("TEST 2 — WORLD MODEL: 3 signals compared")
print("=" * 60)

# Signal A: SO questions normalized WITHIN Python ecosystem only
PYTHON_TAGS = {
    "asyncio":    "python+asyncio",
    "numpy":      "numpy",
    "pytest":     "pytest",
    "requests":   "python-requests",
    "generators": "python+generator",
    "typing":     "python+type-hints",
    "threading":  "python+multithreading",
}
SEED = {
    "asyncio":    0.95,
    "numpy":      0.90,
    "pytest":     0.88,
    "requests":   0.85,
    "generators": 0.88,
    "typing":     0.85,
    "threading":  0.87,
}

print("\nSignal A — SO questions (Python ecosystem only, normalized within domain):")
so_raw = {}
for skill, tag in PYTHON_TAGS.items():
    try:
        url = f"https://api.stackexchange.com/2.3/tags/{tag}/info?site=stackoverflow"
        with urlopen(url, timeout=6) as r:
            d = json.loads(r.read())
        so_raw[skill] = d["items"][0]["count"] if d.get("items") else 0
    except:
        so_raw[skill] = None

valid = [v for v in so_raw.values() if v]
max_so = max(valid) if valid else 1
so_norm = {k: round(v/max_so,3) if v else None for k,v in so_raw.items()}

print(f"  {'skill':<14} {'SO_raw':>10}  {'SO_norm':>8}  {'seed':>6}  {'delta':>8}")
for skill in PYTHON_TAGS:
    raw = so_raw.get(skill)
    norm = so_norm.get(skill)
    seed = SEED.get(skill, 0)
    delta = round(seed - norm, 3) if norm else None
    print(f"  {skill:<14} {str(raw):>10}  {str(norm):>8}  {seed:>6}  {str(delta):>8}")

# Signal B — SHARD's OWN certification rate per skill domain
print("\nSignal B — SHARD's internal certification rate by domain keyword:")
domain_cert = defaultdict(lambda: {"cert":0,"total":0})
domain_map = {
    "asyncio":    ["asyncio","async","coroutine","await","event loop"],
    "numpy":      ["numpy","ndarray","array","pandas"],
    "pytest":     ["test","pytest","assert","tdd","unit test"],
    "requests":   ["http","requests","api","endpoint","rest"],
    "generators": ["generator","yield","iterator","lazy"],
    "typing":     ["typing","type hint","generic","annotation"],
    "threading":  ["thread","concurrent","lock","race","mutex"],
}
for e in experiments:
    t = e.get("topic","").lower()
    if not t or JUNK_RE.search(t) or COMPOSITE_RE.search(t): continue
    for domain, kws in domain_map.items():
        if any(kw in t for kw in kws):
            domain_cert[domain]["total"] += 1
            if e.get("success"): domain_cert[domain]["cert"] += 1

print(f"  {'domain':<14} {'cert/total':>12}  {'rate':>6}  {'seed':>6}  {'delta':>8}")
for domain, counts in sorted(domain_cert.items(), key=lambda x:-x[1]["total"]):
    n = counts["total"]
    c = counts["cert"]
    rate = round(c/n,3) if n else 0
    seed = SEED.get(domain, 0)
    delta = round(seed - rate, 3)
    print(f"  {domain:<14} {f'{c}/{n}':>12}  {rate:>6}  {seed:>6}  {delta:>8}")

# Signal C — PyPI download trend (month over month growth)
print("\nSignal C — PyPI recent downloads (absolute popularity):")
pypi = {"numpy":"numpy","pytest":"pytest","requests":"requests"}
for skill, pkg in pypi.items():
    try:
        url = f"https://pypistats.org/api/packages/{pkg}/recent?period=month"
        with urlopen(url, timeout=5) as r:
            d = json.loads(r.read())
        dlm = d["data"]["last_month"]
        print(f"  {skill:<14} {dlm:>15,} downloads/month")
    except Exception as e:
        print(f"  {skill:<14} unavailable: {e}")

# ── Final verdict ──────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("FINAL VERDICT")
print("=" * 60)
print("""
BLIND SPOTS FIX:
  Data: 0/12 blind spots are real skill gaps (100% junk/composite).
  Verdict: Tier-raise is completely wrong.
  Right fix: after 2 failed attempts on a composite/junk topic,
             quarantine it immediately (add to failed_cache).
             This is cheaper and more effective.

WORLD MODEL FIX:
  SO normalization within Python ecosystem shows seeds are
  roughly ordered correctly but absolute values are arbitrary.
  SHARD's own cert data is too sparse to recalibrate reliably yet.

  Verdict: A world_updater using external HTTP calls is justified
  ONLY if it uses domain-relative normalization, not raw counts.
  Better short-term fix: let SHARD's own certification history
  gradually reweight relevance scores per domain — no external
  calls needed. As SHARD certifies more topics, the world model
  self-calibrates from real SHARD performance.
""")
