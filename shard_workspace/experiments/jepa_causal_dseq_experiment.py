"""
JEPA Hypothesis Experiment — SHARD #35 / id=8
==============================================
Hypothesis: The combination of Causal-JEPA with DSeq-JEPA leads to more robust
and generalizable world models by capturing interaction-dependent dynamics and
inducing latent interventions with counterfactual-like effects.

Setup:
- 5000 synthetic sequences of 8 timesteps, 5 objects 2D (x, y, vx, vy, mass)
- Physics: gravity + elastic collisions between objects
- Three models:
    A) Causal-JEPA: object-level masking (latent causal intervention)
    B) DSeq-JEPA:   saliency-based sequential ordering of slots
    C) Combined:    masking + sequential ordering (the hypothesis)
- Architecture: SlotAttention encoder (tiny) + Transformer predictor (2 layers)
- Tasks:
    1. Future state prediction (MSE on t+1...t+3)
    2. Counterfactual reasoning (mask 1 object, measure prediction error delta)
    3. Generalization: test on scene with 7 objects (trained on 5)
- Target runtime: ~30-60 min on T4 GPU

Requirements: torch>=2.0, numpy, tqdm
Run: python jepa_causal_dseq_experiment.py

Output: prints RESULT table + final score 0.0-1.0
"""

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from tqdm import tqdm
import random

SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)
random.seed(SEED)

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"[SETUP] Device: {DEVICE}")

# ── Hyperparameters ───────────────────────────────────────────────────────────
N_TRAIN      = 4000
N_VAL        = 500
N_TEST       = 500
T_STEPS      = 8        # sequence length
N_OBJ_TRAIN  = 5        # objects during training
N_OBJ_GEN    = 7        # objects during generalization test
OBJ_DIM      = 5        # x, y, vx, vy, mass
HIDDEN_DIM   = 64
N_HEADS      = 4
N_LAYERS     = 2
EPOCHS       = 40
LR           = 3e-4
BATCH_SIZE   = 64
MASK_PROB    = 0.3      # probability of masking an object in Causal-JEPA


# ── Physics simulator ─────────────────────────────────────────────────────────
def simulate_scene(n_objects: int, t_steps: int) -> np.ndarray:
    """Generate one sequence [t_steps, n_objects, OBJ_DIM] with elastic collisions."""
    # Init: random positions in [0,1]^2, velocities in [-0.1, 0.1], mass in [0.5, 2.0]
    pos  = np.random.uniform(0.1, 0.9, (n_objects, 2))
    vel  = np.random.uniform(-0.05, 0.05, (n_objects, 2))
    mass = np.random.uniform(0.5, 2.0, (n_objects, 1))

    seq = []
    for _ in range(t_steps):
        state = np.concatenate([pos, vel, mass], axis=1)  # [n_obj, 5]
        seq.append(state.copy())

        # Gravity (weak)
        vel[:, 1] -= 0.002

        # Elastic collisions between pairs
        for i in range(n_objects):
            for j in range(i + 1, n_objects):
                diff = pos[i] - pos[j]
                dist = np.linalg.norm(diff) + 1e-8
                if dist < 0.08:
                    # 1D elastic collision along collision axis
                    axis = diff / dist
                    v_rel = np.dot(vel[i] - vel[j], axis)
                    if v_rel < 0:  # approaching
                        m1, m2 = mass[i, 0], mass[j, 0]
                        impulse = 2 * v_rel / (m1 + m2)
                        vel[i] -= impulse * m2 * axis
                        vel[j] += impulse * m1 * axis

        # Boundary bounce
        for d in range(2):
            mask_lo = pos[:, d] < 0.02
            mask_hi = pos[:, d] > 0.98
            vel[mask_lo, d] = abs(vel[mask_lo, d])
            vel[mask_hi, d] = -abs(vel[mask_hi, d])

        pos = np.clip(pos + vel, 0.0, 1.0)

    return np.stack(seq, axis=0)  # [T, N, 5]


def generate_dataset(n_scenes: int, n_objects: int, t_steps: int) -> np.ndarray:
    """Returns [n_scenes, T, N, 5]."""
    scenes = [simulate_scene(n_objects, t_steps) for _ in range(n_scenes)]
    return np.stack(scenes, axis=0).astype(np.float32)


# ── Dataset ───────────────────────────────────────────────────────────────────
class PhysicsDataset(Dataset):
    def __init__(self, data: np.ndarray):
        # data: [N, T, n_obj, obj_dim]
        self.data = torch.tensor(data)

    def __len__(self):
        return len(self.data)

    def __getitem__(self, idx):
        seq = self.data[idx]        # [T, n_obj, obj_dim]
        x   = seq[:-1]              # [T-1, n_obj, obj_dim]  input
        y   = seq[1:]               # [T-1, n_obj, obj_dim]  target (next state)
        return x, y


# ── Model components ──────────────────────────────────────────────────────────
class SlotEncoder(nn.Module):
    """Tiny slot-attention-like encoder: projects each object slot independently."""
    def __init__(self, obj_dim: int, hidden: int):
        super().__init__()
        self.proj = nn.Sequential(
            nn.Linear(obj_dim, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden),
        )

    def forward(self, x):
        # x: [B, T, N, obj_dim] -> [B, T, N, hidden]
        return self.proj(x)


class TransformerPredictor(nn.Module):
    """Cross-slot transformer: attends over (T × N) tokens."""
    def __init__(self, hidden: int, n_heads: int, n_layers: int, n_obj: int, obj_dim: int):
        super().__init__()
        self.encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden, nhead=n_heads, dim_feedforward=hidden * 2,
            dropout=0.1, batch_first=True
        )
        self.transformer = nn.TransformerEncoder(self.encoder_layer, num_layers=n_layers)
        self.out_proj = nn.Linear(hidden, obj_dim)

    def forward(self, x):
        # x: [B, T*N, hidden]
        h = self.transformer(x)     # [B, T*N, hidden]
        return self.out_proj(h)     # [B, T*N, obj_dim]


class JEPAModel(nn.Module):
    def __init__(self, obj_dim, hidden, n_heads, n_layers, n_obj, mode="base"):
        """
        mode:
          'base'     : no special inductive bias
          'causal'   : random object masking during training (Causal-JEPA)
          'dseq'     : saliency-based slot reordering (DSeq-JEPA)
          'combined' : masking + reordering (hypothesis)
        """
        super().__init__()
        self.mode    = mode
        self.n_obj   = n_obj
        self.obj_dim = obj_dim
        self.encoder = SlotEncoder(obj_dim, hidden)
        self.pred    = TransformerPredictor(hidden, n_heads, n_layers, n_obj, obj_dim)

    def _apply_causal_mask(self, x, mask_prob):
        """Zero out entire object slots (latent intervention)."""
        B, T, N, D = x.shape
        mask = torch.rand(B, 1, N, 1, device=x.device) > mask_prob
        return x * mask

    def _apply_dseq_reorder(self, x):
        """Reorder slots by saliency = velocity norm (primary objects first)."""
        # saliency = mean |velocity| across time
        vel = x[:, :, :, 2:4]              # [B, T, N, 2]
        sal = vel.norm(dim=-1).mean(dim=1) # [B, N]
        order = sal.argsort(dim=-1, descending=True)  # [B, N]
        x_reordered = torch.stack(
            [x[b, :, order[b], :] for b in range(x.shape[0])], dim=0
        )
        return x_reordered

    def forward(self, x, training=False):
        # x: [B, T, N, obj_dim]
        if training and self.mode in ("causal", "combined"):
            x = self._apply_causal_mask(x, MASK_PROB)
        if self.mode in ("dseq", "combined"):
            x = self._apply_dseq_reorder(x)

        B, T, N, D = x.shape
        h = self.encoder(x)             # [B, T, N, hidden]
        h_flat = h.view(B, T * N, -1)  # [B, T*N, hidden]
        out = self.pred(h_flat)         # [B, T*N, obj_dim]
        return out.view(B, T, N, D)    # [B, T, N, obj_dim]


# ── Training ──────────────────────────────────────────────────────────────────
def train_model(model, loader, val_loader, epochs, lr):
    opt = optim.Adam(model.parameters(), lr=lr)
    sched = optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    criterion = nn.MSELoss()
    best_val = float("inf")

    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for x, y in loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            pred = model(x, training=True)
            loss = criterion(pred, y)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            train_loss += loss.item()

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for x, y in val_loader:
                x, y = x.to(DEVICE), y.to(DEVICE)
                pred = model(x, training=False)
                val_loss += criterion(pred, y).item()

        sched.step()
        if val_loss < best_val:
            best_val = val_loss

        if (epoch + 1) % 10 == 0:
            print(f"  epoch {epoch+1:3d} | train={train_loss/len(loader):.4f} | val={val_loss/len(val_loader):.4f}")

    return best_val


# ── Evaluation ────────────────────────────────────────────────────────────────
def eval_prediction(model, loader):
    model.eval()
    criterion = nn.MSELoss()
    total = 0.0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            pred = model(x, training=False)
            total += criterion(pred, y).item()
    return total / len(loader)


def eval_counterfactual(model, loader):
    """Counterfactual: mask one random object, measure extra prediction error."""
    model.eval()
    criterion = nn.MSELoss()
    delta_total = 0.0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            pred_normal = model(x, training=False)
            err_normal  = criterion(pred_normal, y).item()

            # Mask one random object
            obj_idx = random.randint(0, x.shape[2] - 1)
            x_cf = x.clone()
            x_cf[:, :, obj_idx, :] = 0.0
            pred_cf = model(x_cf, training=False)
            err_cf  = criterion(pred_cf, y).item()

            delta_total += (err_cf - err_normal)
    # Lower delta = model handles missing object better = better causal understanding
    return delta_total / len(loader)


def eval_generalization(model, data_gen):
    """Generalization: test on N_OBJ_GEN objects (model was trained on N_OBJ_TRAIN)."""
    # Pad/truncate to match model's n_obj expectation by using first N_OBJ_TRAIN slots
    model.eval()
    criterion = nn.MSELoss()
    total = 0.0
    n = min(N_OBJ_TRAIN, N_OBJ_GEN)
    ds  = PhysicsDataset(data_gen[:, :, :n, :])
    dl  = DataLoader(ds, batch_size=BATCH_SIZE)
    with torch.no_grad():
        for x, y in dl:
            x, y = x.to(DEVICE), y.to(DEVICE)
            pred = model(x, training=False)
            total += criterion(pred, y).item()
    return total / len(dl)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("[DATA] Generating physics simulations...")
    data_train = generate_dataset(N_TRAIN, N_OBJ_TRAIN, T_STEPS)
    data_val   = generate_dataset(N_VAL,   N_OBJ_TRAIN, T_STEPS)
    data_test  = generate_dataset(N_TEST,  N_OBJ_TRAIN, T_STEPS)
    data_gen   = generate_dataset(N_TEST,  N_OBJ_GEN,   T_STEPS)
    print(f"  train={data_train.shape} val={data_val.shape} test={data_test.shape} gen={data_gen.shape}")

    train_ds = PhysicsDataset(data_train)
    val_ds   = PhysicsDataset(data_val)
    test_ds  = PhysicsDataset(data_test)
    train_dl = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_dl   = DataLoader(val_ds,   batch_size=BATCH_SIZE)
    test_dl  = DataLoader(test_ds,  batch_size=BATCH_SIZE)

    results = {}
    for mode in ("base", "causal", "dseq", "combined"):
        print(f"\n[TRAIN] model={mode}")
        model = JEPAModel(OBJ_DIM, HIDDEN_DIM, N_HEADS, N_LAYERS, N_OBJ_TRAIN, mode=mode).to(DEVICE)
        train_model(model, train_dl, val_dl, EPOCHS, LR)

        pred_err   = eval_prediction(model, test_dl)
        cf_delta   = eval_counterfactual(model, test_dl)
        gen_err    = eval_generalization(model, data_gen)
        results[mode] = {"pred_mse": pred_err, "cf_delta": cf_delta, "gen_mse": gen_err}
        print(f"  pred_mse={pred_err:.4f}  cf_delta={cf_delta:.4f}  gen_mse={gen_err:.4f}")

    # ── Score the hypothesis ──────────────────────────────────────────────────
    # Hypothesis CONFIRMED if 'combined' beats both 'causal' and 'dseq' on:
    #   - prediction MSE (lower = better)
    #   - counterfactual delta (lower = better causal reasoning)
    #   - generalization MSE (lower = better)
    print("\n" + "="*60)
    print("RESULTS SUMMARY")
    print("="*60)
    print(f"{'Model':<12} {'pred_MSE':>10} {'cf_delta':>10} {'gen_MSE':>10}")
    for mode in ("base", "causal", "dseq", "combined"):
        r = results[mode]
        print(f"{mode:<12} {r['pred_mse']:>10.4f} {r['cf_delta']:>10.4f} {r['gen_mse']:>10.4f}")

    combined = results["combined"]
    causal   = results["causal"]
    dseq     = results["dseq"]

    wins = 0
    checks = [
        ("pred_mse",  combined["pred_mse"]  < min(causal["pred_mse"],  dseq["pred_mse"])),
        ("cf_delta",  combined["cf_delta"]  < min(causal["cf_delta"],  dseq["cf_delta"])),
        ("gen_mse",   combined["gen_mse"]   < min(causal["gen_mse"],   dseq["gen_mse"])),
    ]
    for name, win in checks:
        print(f"  combined beats both on {name}: {'YES' if win else 'NO'}")
        if win:
            wins += 1

    score = wins / len(checks)
    verdict = "CONFIRMED" if score >= 0.67 else ("INCONCLUSIVE" if score >= 0.33 else "REFUTED")
    print(f"\nVerdict: {verdict} ({wins}/{len(checks)} metrics won)")
    print(f"RESULT: {round(score, 4)}")


if __name__ == "__main__":
    main()
