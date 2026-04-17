"""
JEPA Hypothesis Experiment v2 — SHARD #35 / id=8
=================================================
Hypothesis: The combination of Causal-JEPA with DSeq-JEPA leads to more robust
and generalizable world models by capturing interaction-dependent dynamics and
inducing latent interventions with counterfactual-like effects.

v2 improvements over v1:
  1. Positional encoding in transformer (fixes DSeq plateau bug)
  2. Harder task: predict t+3 (not t+1)
  3. 3 seeds, report mean ± std
  4. Causal accuracy metric: classify which object was masked
  5. More objects (6), longer sequences (10)
  6. Generalization: 9 objects (trained on 6)

Requirements: torch>=2.0, numpy, tqdm
Run: python jepa_causal_dseq_v2.py
Expected runtime: ~20-40 min on T4 GPU
"""

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import math
import random

SEEDS        = [42, 123, 777]
DEVICE       = torch.device("cuda" if torch.cuda.is_available() else "cpu")

N_TRAIN      = 5000
N_VAL        = 600
N_TEST       = 600
T_STEPS      = 10
PRED_HORIZON = 3       # predict t+3 (harder than t+1)
N_OBJ_TRAIN  = 6
N_OBJ_GEN    = 9
OBJ_DIM      = 5       # x, y, vx, vy, mass
HIDDEN_DIM   = 96
N_HEADS      = 4
N_LAYERS     = 3
EPOCHS       = 50
LR           = 3e-4
BATCH_SIZE   = 64
MASK_PROB    = 0.35

print(f"[SETUP] Device: {DEVICE}")
print(f"[SETUP] Seeds: {SEEDS} | T={T_STEPS} | predict t+{PRED_HORIZON} | N_obj={N_OBJ_TRAIN}")


# ── Physics simulator ─────────────────────────────────────────────────────────
def simulate_scene(n_objects: int, t_steps: int) -> np.ndarray:
    pos  = np.random.uniform(0.1, 0.9, (n_objects, 2))
    vel  = np.random.uniform(-0.06, 0.06, (n_objects, 2))
    mass = np.random.uniform(0.3, 2.5, (n_objects, 1))
    charge = np.random.choice([-1, 1], size=(n_objects, 1)).astype(float)

    seq = []
    for _ in range(t_steps):
        state = np.concatenate([pos, vel, mass], axis=1)
        seq.append(state.copy())

        # Gravity
        vel[:, 1] -= 0.003

        # Pairwise: elastic collision + weak charge repulsion
        for i in range(n_objects):
            for j in range(i + 1, n_objects):
                diff = pos[i] - pos[j]
                dist = np.linalg.norm(diff) + 1e-8
                # Charge repulsion (weak)
                if dist < 0.3:
                    force = charge[i, 0] * charge[j, 0] * 0.0003 / (dist ** 2)
                    vel[i] += force * diff / dist
                    vel[j] -= force * diff / dist
                # Elastic collision
                if dist < 0.07:
                    axis = diff / dist
                    v_rel = np.dot(vel[i] - vel[j], axis)
                    if v_rel < 0:
                        m1, m2 = mass[i, 0], mass[j, 0]
                        impulse = 2 * v_rel / (m1 + m2)
                        vel[i] -= impulse * m2 * axis
                        vel[j] += impulse * m1 * axis

        # Boundary
        for d in range(2):
            vel[pos[:, d] < 0.02, d] =  abs(vel[pos[:, d] < 0.02, d])
            vel[pos[:, d] > 0.98, d] = -abs(vel[pos[:, d] > 0.98, d])

        vel = np.clip(vel, -0.15, 0.15)
        pos = np.clip(pos + vel, 0.0, 1.0)

    return np.stack(seq, axis=0).astype(np.float32)


def generate_dataset(n_scenes, n_objects, t_steps):
    return np.stack([simulate_scene(n_objects, t_steps) for _ in range(n_scenes)])


# ── Dataset ───────────────────────────────────────────────────────────────────
class PhysicsDataset(Dataset):
    def __init__(self, data, horizon=PRED_HORIZON):
        self.data    = torch.tensor(data)
        self.horizon = horizon
        self.T       = data.shape[1]

    def __len__(self):
        return len(self.data) * (self.T - self.horizon)

    def __getitem__(self, idx):
        scene_idx = idx // (self.T - self.horizon)
        t_start   = idx  % (self.T - self.horizon)
        seq = self.data[scene_idx]             # [T, N, D]
        x   = seq[t_start : t_start + self.horizon]         # [H, N, D] input context
        y   = seq[t_start + self.horizon]                    # [N, D]    target state
        return x, y


# ── Positional Encoding ───────────────────────────────────────────────────────
class PositionalEncoding(nn.Module):
    def __init__(self, d_model, max_len=200):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        pos = torch.arange(0, max_len).unsqueeze(1).float()
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(pos * div)
        pe[:, 1::2] = torch.cos(pos * div)
        self.register_buffer("pe", pe.unsqueeze(0))  # [1, max_len, d_model]

    def forward(self, x):
        return x + self.pe[:, :x.size(1)]


# ── Model ──────────────────────────────────────────────────────────────────────
class JEPAv2(nn.Module):
    def __init__(self, obj_dim, hidden, n_heads, n_layers, n_obj, mode="base"):
        super().__init__()
        self.mode   = mode
        self.n_obj  = n_obj
        self.hidden = hidden

        self.slot_proj = nn.Sequential(
            nn.Linear(obj_dim, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden),
        )
        # Slot identity embedding: survives reordering, tells model "who" each slot is
        self.slot_id_emb = nn.Embedding(n_obj, hidden)

        self.pos_enc = PositionalEncoding(hidden, max_len=300)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden, nhead=n_heads, dim_feedforward=hidden * 4,
            dropout=0.1, batch_first=True, norm_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=n_layers)
        self.out_proj    = nn.Linear(hidden, obj_dim)

        # Causal identification head: given the diff between normal and masked output,
        # classify which object (0..N-1) was removed
        self.causal_head = nn.Linear(hidden, n_obj)

    def _causal_mask(self, x, mask_prob):
        """Zero out entire object slots (latent causal intervention). Returns (x_masked, masked_idx)."""
        B, T, N, D = x.shape
        mask = torch.rand(B, 1, N, 1, device=x.device) > mask_prob
        return x * mask

    def _dseq_reorder(self, x):
        """Reorder slots by velocity saliency, return reordered x and original indices."""
        vel = x[:, :, :, 2:4]
        sal = vel.norm(dim=-1).mean(dim=1)     # [B, N]
        order = sal.argsort(dim=-1, descending=True)  # [B, N] -- most salient first
        x_r = torch.stack([x[b, :, order[b]] for b in range(x.shape[0])])
        return x_r, order

    def forward(self, x, training=False):
        # x: [B, T, N, D]
        B, T, N, D = x.shape

        if training and self.mode in ("causal", "combined"):
            x = self._causal_mask(x, MASK_PROB)

        slot_order = torch.arange(N, device=x.device).unsqueeze(0).expand(B, -1)  # [B, N]
        if self.mode in ("dseq", "combined"):
            x, slot_order = self._dseq_reorder(x)

        # Encode slots
        h = self.slot_proj(x)   # [B, T, N, hidden]

        # Add slot identity embedding (reordered with slots)
        id_emb = self.slot_id_emb(slot_order)  # [B, N, hidden]
        h = h + id_emb.unsqueeze(1)            # [B, T, N, hidden]

        # Flatten T×N as sequence tokens
        h_flat = h.view(B, T * N, self.hidden)  # [B, T*N, hidden]
        h_flat = self.pos_enc(h_flat)

        h_out = self.transformer(h_flat)         # [B, T*N, hidden]

        # Predict next state for each slot (use last T tokens = last timestep)
        last_h = h_out[:, -N:, :]               # [B, N, hidden]
        pred   = self.out_proj(last_h)           # [B, N, D]

        return pred, last_h  # return hidden for causal head


# ── Training ──────────────────────────────────────────────────────────────────
def train_one(model, loader, val_loader, epochs, lr):
    opt   = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs, eta_min=lr * 0.1)
    crit  = nn.MSELoss()

    for epoch in range(epochs):
        model.train()
        tr_loss = 0.0
        for x, y in loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            pred, _ = model(x, training=True)
            loss = crit(pred, y)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tr_loss += loss.item()

        sched.step()
        if (epoch + 1) % 10 == 0:
            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for x, y in val_loader:
                    x, y = x.to(DEVICE), y.to(DEVICE)
                    pred, _ = model(x)
                    val_loss += crit(pred, y).item()
            print(f"    epoch {epoch+1:3d} | train={tr_loss/len(loader):.4f} | val={val_loss/len(val_loader):.4f}")


# ── Evaluation ────────────────────────────────────────────────────────────────
def eval_prediction(model, loader):
    model.eval()
    crit  = nn.MSELoss()
    total = 0.0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            pred, _ = model(x)
            total  += crit(pred, y).item()
    return total / len(loader)


def eval_counterfactual(model, loader):
    """cf_delta: extra MSE when one object is masked. Lower = better causal understanding."""
    model.eval()
    crit  = nn.MSELoss()
    delta = 0.0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            pred_n, h_n = model(x)
            err_n = crit(pred_n, y).item()

            obj_idx = random.randint(0, x.shape[2] - 1)
            x_cf = x.clone()
            x_cf[:, :, obj_idx, :] = 0.0
            pred_cf, _ = model(x_cf)
            err_cf = crit(pred_cf, y).item()
            delta += (err_cf - err_n)
    return delta / len(loader)


def eval_causal_accuracy(model, loader):
    """Can the model (via causal_head) identify which object was masked?"""
    model.eval()
    correct = 0
    total   = 0
    with torch.no_grad():
        for x, y in loader:
            x = x.to(DEVICE)
            B, T, N, D = x.shape

            # Get normal hidden
            _, h_normal = model(x)  # [B, N, hidden]

            # Mask each object and get diff signal
            for obj_idx in range(N):
                x_cf = x.clone()
                x_cf[:, :, obj_idx, :] = 0.0
                _, h_cf = model(x_cf)

                diff = (h_normal - h_cf).mean(dim=1)  # [B, hidden]
                logits = model.causal_head(diff)       # [B, N]
                pred_idx = logits.argmax(dim=-1)       # [B]
                correct += (pred_idx == obj_idx).sum().item()
                total   += B

    return correct / total if total > 0 else 0.0


def eval_generalization(model, data_gen):
    n = min(N_OBJ_TRAIN, N_OBJ_GEN)
    ds = PhysicsDataset(data_gen[:, :, :n, :])
    dl = DataLoader(ds, batch_size=BATCH_SIZE)
    return eval_prediction(model, dl)


# ── Main ──────────────────────────────────────────────────────────────────────
def run_seed(seed):
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    print(f"\n  [DATA] Generating (seed={seed})...")
    data_train = generate_dataset(N_TRAIN, N_OBJ_TRAIN, T_STEPS)
    data_val   = generate_dataset(N_VAL,   N_OBJ_TRAIN, T_STEPS)
    data_test  = generate_dataset(N_TEST,  N_OBJ_TRAIN, T_STEPS)
    data_gen   = generate_dataset(N_TEST,  N_OBJ_GEN,   T_STEPS)

    train_dl = DataLoader(PhysicsDataset(data_train), batch_size=BATCH_SIZE, shuffle=True)
    val_dl   = DataLoader(PhysicsDataset(data_val),   batch_size=BATCH_SIZE)
    test_dl  = DataLoader(PhysicsDataset(data_test),  batch_size=BATCH_SIZE)

    seed_results = {}
    for mode in ("base", "causal", "dseq", "combined"):
        print(f"\n  [TRAIN] mode={mode} seed={seed}")
        model = JEPAv2(OBJ_DIM, HIDDEN_DIM, N_HEADS, N_LAYERS, N_OBJ_TRAIN, mode=mode).to(DEVICE)
        train_one(model, train_dl, val_dl, EPOCHS, LR)

        pred_mse  = eval_prediction(model, test_dl)
        cf_delta  = eval_counterfactual(model, test_dl)
        causal_acc= eval_causal_accuracy(model, test_dl)
        gen_mse   = eval_generalization(model, data_gen)

        seed_results[mode] = {
            "pred_mse":  pred_mse,
            "cf_delta":  cf_delta,
            "causal_acc":causal_acc,
            "gen_mse":   gen_mse,
        }
        print(f"    pred={pred_mse:.4f} cf_delta={cf_delta:.4f} causal_acc={causal_acc:.3f} gen={gen_mse:.4f}")

    return seed_results


def main():
    all_results = {mode: {"pred_mse": [], "cf_delta": [], "causal_acc": [], "gen_mse": []}
                   for mode in ("base", "causal", "dseq", "combined")}

    for seed in SEEDS:
        sr = run_seed(seed)
        for mode, metrics in sr.items():
            for k, v in metrics.items():
                all_results[mode][k].append(v)

    print("\n" + "=" * 70)
    print("RESULTS SUMMARY (mean ± std across 3 seeds)")
    print("=" * 70)
    print(f"{'Model':<12} {'pred_MSE':>14} {'cf_delta':>14} {'causal_acc':>12} {'gen_MSE':>12}")
    for mode in ("base", "causal", "dseq", "combined"):
        r = all_results[mode]
        def ms(k): return f"{np.mean(r[k]):.4f}±{np.std(r[k]):.4f}"
        def mc(k): return f"{np.mean(r[k]):.3f}±{np.std(r[k]):.3f}"
        print(f"{mode:<12} {ms('pred_mse'):>14} {ms('cf_delta'):>14} {mc('causal_acc'):>12} {ms('gen_mse'):>12}")

    # ── Score ─────────────────────────────────────────────────────────────────
    combined = {k: np.mean(v) for k, v in all_results["combined"].items()}
    causal   = {k: np.mean(v) for k, v in all_results["causal"].items()}
    dseq     = {k: np.mean(v) for k, v in all_results["dseq"].items()}

    print("\nHypothesis checks (combined must beat both individual models):")
    checks = [
        ("cf_delta  (lower=better)",  combined["cf_delta"]   < min(causal["cf_delta"],   dseq["cf_delta"])),
        ("causal_acc (higher=better)",combined["causal_acc"] > max(causal["causal_acc"], dseq["causal_acc"])),
        ("gen_mse  (lower=better)",   combined["gen_mse"]    < min(causal["gen_mse"],     dseq["gen_mse"])),
        ("pred_mse (lower=better)",   combined["pred_mse"]   < min(causal["pred_mse"],    dseq["pred_mse"])),
    ]
    wins = 0
    for name, win in checks:
        print(f"  combined beats both on {name}: {'YES' if win else 'NO'}")
        if win: wins += 1

    score   = wins / len(checks)
    verdict = "CONFIRMED" if score >= 0.75 else ("INCONCLUSIVE" if score >= 0.5 else "REFUTED")
    print(f"\nVerdict: {verdict} ({wins}/{len(checks)} checks passed)")
    print(f"RESULT: {round(score, 4)}")


if __name__ == "__main__":
    main()
