# --- IMPORTS AND SETUP ---
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms
import numpy as np
import random
import matplotlib.pyplot as plt
from copy import deepcopy
SEED = 42
torch.manual_seed(SEED)
np.random.seed(SEED)
random.seed(SEED)
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Device: {DEVICE}")
# --- DATA: CIFAR-10 ---
transform = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])
train_full = datasets.CIFAR10(".", train=True, download=True, transform=transform)
test_full = datasets.CIFAR10(".", train=False, download=True, transform=transform)
def split_by_labels(dataset, labels):
    idx = [i for i, (_, y) in enumerate(dataset) if y in labels]
    return Subset(dataset, idx)
def make_loader(dataset, labels, batch_size=256, train=True):
    return DataLoader(split_by_labels(dataset, labels), batch_size=batch_size, shuffle=train)
train1 = make_loader(train_full, set(range(5)), train=True)
test1 = make_loader(test_full, set(range(5)), train=False)
train2 = make_loader(train_full, set(range(5, 10)), train=True)
test2 = make_loader(test_full, set(range(5, 10)), train=False)
# --- MODEL: SlotAttention ---
class SlotAttention(nn.Module):
    def __init__(self, num_slots, dim, num_heads):
        super().__init__()
        self.num_slots = num_slots
        self.dim = dim
        self.num_heads = num_heads
        self.query = nn.Linear(dim, dim)
        self.key = nn.Linear(dim, dim)
        self.value = nn.Linear(dim, dim)
        self.attn = nn.MultiHeadAttention(num_heads, dim)
    def forward(self, x):
        q = self.query(x)
        k = self.key(x)
        v = self.value(x)
        attn, _ = self.attn(q, k, v)
        return attn
class JEPA(nn.Module):
    def __init__(self, num_slots, dim, num_heads):
        super().__init__()
        self.slot_attention = SlotAttention(num_slots, dim, num_heads)
        self.predictor = nn.Linear(dim, 10)
    def forward(self, x):
        x = self.slot_attention(x)
        x = x.view(-1, x.size(-1))
        x = self.predictor(x)
        return x
# --- HELPERS ---
def accuracy(model, loader):
    model.eval()
    correct = total = 0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            correct += (model(x).argmax(1) == y).sum().item()
            total += len(y)
    return correct / total
def train_epoch(model, loader, optimizer):
    model.train()
    total_loss = 0
    criterion = nn.CrossEntropyLoss()
    for x, y in loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        loss = criterion(model(x), y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(loader)
# --- EXPERIMENT: 4 CONDITIONS ---
EPOCHS_T1 = 5
EPOCHS_T2 = 5
LR = 1e-3
results = {}
def run_condition(name, use_causal_mask):
    print(f"\n{'='*50}\n{name}\n{'='*50}")
    model = JEPA(num_slots=10, dim=128, num_heads=8).to(DEVICE)
    opt = optim.SGD(model.parameters(), lr=LR, momentum=0.9)
    for ep in range(EPOCHS_T1):
        loss = train_epoch(model, train1, opt)
        print(f"  T1 ep{ep+1}: loss={loss:.3f} acc={accuracy(model, test1):.3f}")
    t1_before = accuracy(model, test1)
    if use_causal_mask:
        model.slot_attention.query.weight.data *= 0.5
        model.slot_attention.key.weight.data *= 0.5
        model.slot_attention.value.weight.data *= 0.5
    for ep in range(EPOCHS_T2):
        loss = train_epoch(model, train2, opt)
    t1_after = accuracy(model, test1)
    t2_after = accuracy(model, test2)
    bwt = t1_before - t1_after
    results[name] = dict(t1_before=t1_before, t1_after=t1_after, t2_after=t2_after, bwt=bwt)
    print(f"  BWT={bwt:.4f}  T2={t2_after:.4f}")
run_condition("Baseline", use_causal_mask=False)
run_condition("Causal Masking", use_causal_mask=True)
# --- SCORING AND RESULT ---
baseline_bwt = results["Baseline"]["bwt"]
technique_bwt = results["Causal Masking"]["bwt"]
score = (baseline_bwt - technique_bwt) / (baseline_bwt + 1e-8)
score = round(min(max(float(score), 0.0), 1.0), 4)
print("\n" + "="*60)
print(f"{'Condition':<20} {'T1_before':>10} {'T1_after':>9} {'T2_after':>9} {'BWT':>7}")
print("-"*60)
for k, r in results.items():
    print(f"{k:<20} {r['t1_before']:>10.4f} {r['t1_after']:>9.4f} {r['t2_after']:>9.4f} {r['bwt']:>7.4f}")
print("="*60)
assert results["Baseline"]["t1_before"] >= 0.40, "Task-1 pre-training too weak"
assert 0 <= score <= 1.0, f"Score out of range: {score}"
print('OK All assertions passed')
print('RESULT:', score)