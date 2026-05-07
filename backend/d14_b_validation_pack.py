"""d14_b_validation_pack.py -- D14-B: 5-task Split-MNIST validation pack for Hypothesis #14.

Extends the original 2-task Kaggle run to the standard 5-task continual learning
protocol. Tests four conditions (Baseline SGD, ANV only, OGD only, ANV+OGD)
across 5 seeds to assess stability of the ANV+OGD advantage over OGD-only.

Usage:
  # Dry-run (CPU, synthetic data, 2 seeds, 1 epoch/task -- fast local smoke):
  python backend/d14_b_validation_pack.py --dry-run

  # Full run (requires torchvision + GPU recommended):
  python backend/d14_b_validation_pack.py --output-dir shard_workspace/d14_b_runs

  # Custom:
  python backend/d14_b_validation_pack.py --seeds 0 1 2 --epochs 3 --output-dir /tmp/d14

Outputs to output_dir/<timestamp>/:
  raw_results.json   -- per-seed, per-condition, per-task accuracy matrix
  summary.json       -- mean ± std across seeds for each condition
  summary.md         -- human-readable report

DO NOT update Hypothesis #14 provenance automatically.
Promotion to benchmark_validated is a manual step after human review.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset, Subset

_ROOT = Path(__file__).resolve().parent.parent
RUNS_ROOT = _ROOT / "shard_workspace" / "d14_b_runs"

# ── Task definition ───────────────────────────────────────────────────────────

TASKS: List[Tuple[int, int]] = [
    (0, 1),   # Task 1: digits 0-1
    (2, 3),   # Task 2: digits 2-3
    (4, 5),   # Task 3: digits 4-5
    (6, 7),   # Task 4: digits 6-7
    (8, 9),   # Task 5: digits 8-9
]
N_TASKS   = len(TASKS)
N_CLASSES = 2   # binary within-task classification


# ── Experiment config ─────────────────────────────────────────────────────────

@dataclass
class D14BConfig:
    seeds:         List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    epochs_per_task: int     = 5
    lr:            float     = 1e-3
    momentum:      float     = 0.9
    batch_size:    int       = 256
    hidden:        int       = 256
    anv_sigma:     float     = 0.15
    ogd_batches:   int       = 30
    dry_run:       bool      = False
    output_dir:    Path      = RUNS_ROOT
    data_root:     str       = "."       # MNIST download dir

    def __post_init__(self):
        if self.dry_run:
            self.seeds          = [0, 1]
            self.epochs_per_task = 1
            self.ogd_batches    = 5
            self.batch_size     = 512


CONDITIONS = [
    {"name": "Baseline SGD", "use_anv": False, "use_ogd": False},
    {"name": "ANV only",     "use_anv": True,  "use_ogd": False},
    {"name": "OGD only",     "use_anv": False, "use_ogd": True},
    {"name": "ANV + OGD",    "use_anv": True,  "use_ogd": True},
]


# ── Data loading ──────────────────────────────────────────────────────────────

class _SyntheticMNIST(Dataset):
    """Synthetic 28×28 grayscale data for dry-run (no torchvision needed)."""
    def __init__(self, n_samples: int = 1000, seed: int = 0):
        rng = torch.Generator().manual_seed(seed)
        self.X = torch.randn(n_samples, 1, 28, 28, generator=rng)
        self.y = torch.randint(0, 10, (n_samples,), generator=rng)

    def __len__(self) -> int: return len(self.X)
    def __getitem__(self, i): return self.X[i], int(self.y[i])


def _load_datasets(cfg: D14BConfig) -> Tuple[Dataset, Dataset]:
    """Return (train_dataset, test_dataset). Falls back to synthetic on ImportError."""
    try:
        from torchvision import datasets, transforms  # type: ignore[import]
        transform = transforms.Compose([
            transforms.ToTensor(),
            transforms.Normalize((0.1307,), (0.3081,)),
        ])
        train = datasets.MNIST(cfg.data_root, train=True,  download=True, transform=transform)
        test  = datasets.MNIST(cfg.data_root, train=False, download=True, transform=transform)
        return train, test
    except ImportError:
        print("[D14-B] torchvision not available — using synthetic data (dry-run only)")
        return _SyntheticMNIST(6000), _SyntheticMNIST(1000, seed=99)


def _task_loader(dataset: Dataset, digits: Tuple[int, int],
                 batch_size: int, shuffle: bool = True) -> DataLoader:
    d0, d1 = digits
    idx = [i for i, (_, y) in enumerate(dataset) if int(y) in (d0, d1)]
    return DataLoader(Subset(dataset, idx), batch_size=batch_size, shuffle=shuffle)


# ── Model ─────────────────────────────────────────────────────────────────────

class MLP(nn.Module):
    """2-layer MLP with 2-class head (task-incremental, same architecture as D14-A)."""
    def __init__(self, hidden: int = 256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(784, hidden), nn.ReLU(),
            nn.Linear(hidden, hidden), nn.ReLU(),
            nn.Linear(hidden, N_CLASSES),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ── Training primitives ───────────────────────────────────────────────────────

def _anv_hook(sigma: float):
    def h(module, inp, out):
        return out * (1.0 + sigma * torch.randn_like(out))
    return h


def _collect_grad_basis(model: MLP, loader: DataLoader,
                        digits: Tuple[int, int], n_batches: int,
                        device: torch.device) -> List[torch.Tensor]:
    d0 = digits[0]
    criterion = nn.CrossEntropyLoss()
    basis: List[torch.Tensor] = []
    for i, (x, y) in enumerate(loader):
        if i >= n_batches:
            break
        x = x.to(device)
        y = (y.to(device) - d0).long()   # 0 or 1
        model.zero_grad()
        criterion(model(x), y).backward()
        g = torch.cat([p.grad.data.clone().flatten()
                       for p in model.parameters() if p.grad is not None])
        basis.append(g)
        model.zero_grad()
    return basis


def _make_ogd_projector(all_basis: List[torch.Tensor], eps: float = 1e-8):
    normed = [v / v.norm() for v in all_basis if v.norm() > eps]

    def project(model: MLP) -> None:
        grads = [p.grad.data.flatten() for p in model.parameters() if p.grad is not None]
        g_flat = torch.cat(grads)
        for v in normed:
            g_flat = g_flat - (g_flat @ v) * v
        offset = 0
        for p in model.parameters():
            if p.grad is None:
                continue
            size = p.grad.data.numel()
            p.grad.data.copy_(g_flat[offset:offset + size].view_as(p.grad.data))
            offset += size
    return project


def _accuracy(model: MLP, loader: DataLoader,
              digits: Tuple[int, int], device: torch.device) -> float:
    model.eval()
    d0 = digits[0]
    correct = total = 0
    with torch.no_grad():
        for x, y in loader:
            x = x.to(device)
            y = (y.to(device) - d0).long()
            correct += (model(x).argmax(1) == y).sum().item()
            total   += len(y)
    return correct / total if total > 0 else 0.0


def _train_epoch(model: MLP, loader: DataLoader, optimizer: optim.Optimizer,
                 digits: Tuple[int, int], device: torch.device,
                 anv_sigma: float = 0.0, proj_fn=None) -> float:
    model.train()
    d0 = digits[0]
    criterion = nn.CrossEntropyLoss()
    hooks, total_loss = [], 0.0
    for x, y in loader:
        x = x.to(device)
        y = (y.to(device) - d0).long()
        if anv_sigma > 0:
            for layer in model.net:
                if isinstance(layer, nn.ReLU):
                    hooks.append(layer.register_forward_hook(_anv_hook(anv_sigma)))
        optimizer.zero_grad()
        loss = criterion(model(x), y)
        loss.backward()
        if proj_fn is not None:
            proj_fn(model)
        optimizer.step()
        for h in hooks:
            h.remove()
        hooks.clear()
        total_loss += loss.item()
    return total_loss / max(len(loader), 1)


# ── Single-seed experiment run ────────────────────────────────────────────────

def run_one_seed(seed: int, cfg: D14BConfig,
                 train_ds: Dataset, test_ds: Dataset,
                 device: torch.device) -> Dict[str, Any]:
    """Run all 4 conditions for one seed. Returns condition → metrics dict."""
    torch.manual_seed(seed)

    # Pre-build per-task loaders once (shared across conditions)
    train_loaders = [_task_loader(train_ds, t, cfg.batch_size, shuffle=True)  for t in TASKS]
    test_loaders  = [_task_loader(test_ds,  t, cfg.batch_size, shuffle=False) for t in TASKS]

    results: Dict[str, Any] = {}
    for cond in CONDITIONS:
        name    = cond["name"]
        use_anv = cond["use_anv"]
        use_ogd = cond["use_ogd"]
        print(f"  [seed={seed}] condition='{name}'")

        torch.manual_seed(seed)
        model  = MLP(hidden=cfg.hidden).to(device)
        optim_ = optim.SGD(model.parameters(), lr=cfg.lr, momentum=cfg.momentum)

        # A[t][k] = accuracy on task t measured right after training task k (k >= t)
        # acc_matrix[t][k] where t is task index, k is after which task was evaluated
        # We store as list of lists: acc_matrix[t] = list of accuracies measured at
        # eval points after tasks t, t+1, ..., N_TASKS-1
        # For simplicity: record accuracy on all previous tasks after each new task
        acc_after: List[List[float]] = [[] for _ in range(N_TASKS)]
        # acc_after[t][k] = accuracy on task t measured after training tasks 0..k
        # We fill it only for k >= t

        all_basis: List[torch.Tensor] = []   # OGD: accumulated across tasks

        for task_idx, task_digits in enumerate(TASKS):
            proj_fn = _make_ogd_projector(all_basis) if use_ogd and all_basis else None

            for _ in range(cfg.epochs_per_task):
                _train_epoch(model, train_loaders[task_idx], optim_,
                             task_digits, device,
                             anv_sigma=cfg.anv_sigma if use_anv else 0.0,
                             proj_fn=proj_fn)

            # Record gradient basis for OGD after this task
            if use_ogd:
                basis = _collect_grad_basis(model, train_loaders[task_idx],
                                            task_digits, cfg.ogd_batches, device)
                all_basis.extend(basis)

            # Evaluate all tasks seen so far
            for prev_t in range(task_idx + 1):
                acc = _accuracy(model, test_loaders[prev_t], TASKS[prev_t], device)
                acc_after[prev_t].append(acc)

        # Compute metrics from acc_after
        # acc_after[t] has (N_TASKS - t) entries: accuracy on task t measured after
        # tasks t, t+1, ..., N_TASKS-1. Entry [0] = right after learning task t.
        task_acc_right_after = [acc_after[t][0]  for t in range(N_TASKS)]
        task_acc_final       = [acc_after[t][-1] for t in range(N_TASKS)]

        final_avg_acc = sum(task_acc_final) / N_TASKS

        # BWT = mean(A[t][final] - A[t][right_after_t]) for t < last task
        bwt_vals = [task_acc_final[t] - task_acc_right_after[t]
                    for t in range(N_TASKS - 1)]
        signed_bwt = sum(bwt_vals) / len(bwt_vals) if bwt_vals else 0.0

        # Forgetting magnitude = mean(peak - final) for t < last task; >= 0
        forget_vals = []
        for t in range(N_TASKS - 1):
            peak  = max(acc_after[t])
            final = task_acc_final[t]
            forget_vals.append(max(0.0, peak - final))
        forgetting_magnitude = sum(forget_vals) / len(forget_vals) if forget_vals else 0.0

        results[name] = {
            "task_acc_right_after": task_acc_right_after,
            "task_acc_final":       task_acc_final,
            "per_task_acc_matrix":  [list(row) for row in acc_after],
            "final_average_accuracy": round(final_avg_acc, 6),
            "forgetting_magnitude":   round(forgetting_magnitude, 6),
            "signed_bwt":             round(signed_bwt, 6),
        }
        print(f"    final_avg_acc={final_avg_acc:.4f}  forgetting={forgetting_magnitude:.4f}  bwt={signed_bwt:.4f}")

    return results


# ── Metrics helpers (importable for tests) ────────────────────────────────────

def compute_forgetting_magnitude(acc_after: List[List[float]]) -> float:
    """Mean max-to-final forgetting for tasks 0..N-2 (excludes last task)."""
    vals = []
    for t in range(len(acc_after) - 1):
        row = acc_after[t]
        if row:
            vals.append(max(0.0, max(row) - row[-1]))
    return sum(vals) / len(vals) if vals else 0.0


def compute_signed_bwt(acc_after: List[List[float]]) -> float:
    """Mean (final_acc - right_after_acc) for tasks 0..N-2."""
    vals = []
    for t in range(len(acc_after) - 1):
        row = acc_after[t]
        if row:
            vals.append(row[-1] - row[0])
    return sum(vals) / len(vals) if vals else 0.0


def compute_final_average_accuracy(acc_after: List[List[float]]) -> float:
    """Mean of final accuracy across all tasks."""
    finals = [row[-1] for row in acc_after if row]
    return sum(finals) / len(finals) if finals else 0.0


def get_task_splits() -> List[Tuple[int, int]]:
    """Return the 5-task digit pair list (importable for tests)."""
    return list(TASKS)


# ── Summary computation ───────────────────────────────────────────────────────

def _mean_std(values: List[float]) -> Tuple[float, float]:
    import statistics
    if len(values) == 0:
        return 0.0, 0.0
    if len(values) == 1:
        return values[0], 0.0
    return statistics.mean(values), statistics.stdev(values)


def compute_summary(raw_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-seed results into mean ± std for each condition and metric."""
    summary: Dict[str, Any] = {}
    metrics = ["final_average_accuracy", "forgetting_magnitude", "signed_bwt"]
    for cond in CONDITIONS:
        name = cond["name"]
        cond_summary: Dict[str, Any] = {}
        for m in metrics:
            vals = [seed_res[name][m] for seed_res in raw_results
                    if name in seed_res]
            mean, std = _mean_std(vals)
            cond_summary[f"{m}_mean"] = round(mean, 6)
            cond_summary[f"{m}_std"]  = round(std,  6)
        summary[name] = cond_summary
    return summary


# ── Report generation ─────────────────────────────────────────────────────────

def build_markdown_report(summary: Dict[str, Any], cfg: D14BConfig,
                          meta: Dict[str, Any]) -> str:
    lines = [
        "# D14-B Validation Pack — Report",
        "",
        f"**Date:** {meta.get('date', '?')}",
        f"**Mode:** {'DRY-RUN (synthetic data)' if cfg.dry_run else 'FULL RUN (real MNIST)'}",
        f"**Seeds:** {cfg.seeds}",
        f"**Epochs/task:** {cfg.epochs_per_task}",
        f"**Hypothesis #14:** ANV+OGD reduces catastrophic forgetting vs OGD-only (Split-MNIST 5-task)",
        "",
        "## Results — Mean ± Std Across Seeds",
        "",
        "| Condition | final_avg_acc | forgetting_mag | signed_bwt |",
        "|---|---|---|---|",
    ]
    for cond in CONDITIONS:
        n = cond["name"]
        s = summary.get(n, {})
        fa  = f"{s.get('final_average_accuracy_mean', 0):.4f} ± {s.get('final_average_accuracy_std', 0):.4f}"
        fm  = f"{s.get('forgetting_magnitude_mean',   0):.4f} ± {s.get('forgetting_magnitude_std',   0):.4f}"
        bwt = f"{s.get('signed_bwt_mean',             0):.4f} ± {s.get('signed_bwt_std',             0):.4f}"
        lines.append(f"| {n} | {fa} | {fm} | {bwt} |")

    lines += [
        "",
        "## Kaggle Quota Estimate",
        "",
        f"- **estimated_gpu_hours:** {meta.get('estimated_gpu_hours', 1.0):.1f}h",
        f"- **expected_kaggle_queue_entry:** pending (manual dispatch required)",
        f"- KAGGLE_DISPATCH_ENABLED=false by default — no auto-dispatch performed",
        "",
        "## Promotion Gate (manual review required)",
        "",
        "ANV+OGD may be promoted to `benchmark_validated` only if:",
        "1. Mean forgetting_magnitude (ANV+OGD) < mean forgetting_magnitude (OGD-only)",
        "2. Mean final_average_accuracy (ANV+OGD) >= mean final_average_accuracy (OGD-only) − 0.01",
        "3. Result is stable across seeds (std is not dominated by one outlier seed)",
        "",
        "> **This script does NOT update Hypothesis #14 provenance.**",
        "> Promotion to `benchmark_validated` is a manual step after human review.",
        "> Run `backend/d14_b_analyze.py` for the automated verdict.",
    ]
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="D14-B 5-task Split-MNIST validation pack")
    parser.add_argument("--dry-run",    action="store_true",  help="Fast CPU smoke (synthetic data)")
    parser.add_argument("--output-dir", default=str(RUNS_ROOT), help="Where to save results")
    parser.add_argument("--seeds",      nargs="+", type=int,  help="Override seed list")
    parser.add_argument("--epochs",     type=int,              help="Override epochs_per_task")
    parser.add_argument("--no-cuda",    action="store_true",  help="Force CPU even if GPU present")
    args = parser.parse_args(argv)

    cfg = D14BConfig(dry_run=args.dry_run)
    if args.seeds:
        cfg.seeds = args.seeds
    if args.epochs:
        cfg.epochs_per_task = args.epochs
    cfg.output_dir = Path(args.output_dir)

    device = torch.device("cpu" if args.no_cuda or not torch.cuda.is_available() else "cuda")
    print(f"[D14-B] device={device}  dry_run={cfg.dry_run}  seeds={cfg.seeds}  "
          f"epochs_per_task={cfg.epochs_per_task}")

    # Estimate GPU hours (for report)
    # Full run (5 seeds × 5 tasks × 5 epochs): ~1.0h on T4
    estimated_gpu_hours = 0.1 if cfg.dry_run else 1.0

    # Load data once
    train_ds, test_ds = _load_datasets(cfg)

    run_root = cfg.output_dir / datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=True)
    print(f"[D14-B] Output dir: {run_root}")

    t_start = time.time()
    all_seed_results: List[Dict] = []

    for seed in cfg.seeds:
        print(f"\n[D14-B] -- Seed {seed} ------------------------------------------")
        seed_res = run_one_seed(seed, cfg, train_ds, test_ds, device)
        all_seed_results.append(seed_res)

    elapsed = time.time() - t_start
    print(f"\n[D14-B] Completed in {elapsed:.1f}s")

    # Save raw results
    raw_path = run_root / "raw_results.json"
    raw_path.write_text(json.dumps({
        "seeds":       cfg.seeds,
        "dry_run":     cfg.dry_run,
        "elapsed_s":   round(elapsed, 1),
        "results":     all_seed_results,
    }, indent=2), encoding="utf-8")
    print(f"[D14-B] Saved raw results -> {raw_path}")

    # Compute summary
    summary = compute_summary(all_seed_results)
    meta = {
        "date":                 datetime.now(tz=timezone.utc).isoformat(),
        "estimated_gpu_hours":  estimated_gpu_hours,
        "dry_run":              cfg.dry_run,
        "seeds":                cfg.seeds,
        "epochs_per_task":      cfg.epochs_per_task,
    }
    summary_path = run_root / "summary.json"
    summary_path.write_text(json.dumps({"meta": meta, "summary": summary}, indent=2),
                            encoding="utf-8")
    print(f"[D14-B] Saved summary -> {summary_path}")

    # Markdown report
    report_path = run_root / "summary.md"
    report_path.write_text(build_markdown_report(summary, cfg, meta), encoding="utf-8")
    print(f"[D14-B] Saved report -> {report_path}")

    # Print quick comparison
    ogd  = summary.get("OGD only",   {})
    anv_ogd = summary.get("ANV + OGD", {})
    print("\n[D14-B] Quick comparison (OGD-only vs ANV+OGD):")
    print(f"  forgetting_magnitude:   OGD={ogd.get('forgetting_magnitude_mean', '?'):.4f}  "
          f"ANV+OGD={anv_ogd.get('forgetting_magnitude_mean', '?'):.4f}")
    print(f"  final_average_accuracy: OGD={ogd.get('final_average_accuracy_mean', '?'):.4f}  "
          f"ANV+OGD={anv_ogd.get('final_average_accuracy_mean', '?'):.4f}")


if __name__ == "__main__":
    main()
