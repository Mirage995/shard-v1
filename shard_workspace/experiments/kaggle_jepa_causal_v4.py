import torch, torch.nn as nn, torch.optim as optim
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, transforms
import numpy as np, random, matplotlib.pyplot as plt
from copy import deepcopy

def _get_device():
    if torch.cuda.is_available():
        cap = torch.cuda.get_device_capability()
        if cap[0] >= 7:  
            return torch.device('cuda')
    return torch.device('cpu')

SEED = 42; torch.manual_seed(SEED); np.random.seed(SEED); random.seed(SEED)
DEVICE = _get_device()
print(f"Device: {DEVICE}")

transform = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))])
train_full = datasets.MNIST(".", train=True,  download=True, transform=transform)
test_full  = datasets.MNIST(".", train=False, download=True, transform=transform)

def split_by_labels(dataset, labels):
    idx = [i for i, (_, y) in enumerate(dataset) if y in labels]
    return Subset(dataset, idx)

def make_loader(dataset, labels, batch_size=256, train=True):
    return DataLoader(split_by_labels(dataset, labels), batch_size=batch_size, shuffle=train)

train1 = make_loader(train_full, set(range(5)),     train=True)
test1  = make_loader(test_full,  set(range(5)),     train=False)
train2 = make_loader(train_full, set(range(5, 10)), train=True)
test2  = make_loader(test_full,  set(range(5, 10)), train=False)

class JEPA(nn.Module):
    def __init__(self, hidden=256):
        super().__init__()
        self.net = nn.Sequential(nn.Flatten(), nn.Linear(784, hidden), nn.ReLU(),
                                 nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, 5))
        self.slot_attention = nn.MultiheadAttention(hidden, 8)
    def forward(self, x): 
        x = self.net[0](x)
        x = x.view(-1, 196, 4)
        x, _ = self.slot_attention(x, x)
        x = x.view(-1, 784)
        return self.net[2:](x)

class JEPA_Causal(nn.Module):
    def __init__(self, hidden=256):
        super().__init__()
        self.net = nn.Sequential(nn.Flatten(), nn.Linear(784, hidden), nn.ReLU(),
                                 nn.Linear(hidden, hidden), nn.ReLU(), nn.Linear(hidden, 5))
        self.slot_attention = nn.MultiheadAttention(hidden, 8)
    def forward(self, x): 
        x = self.net[0](x)
        x = x.view(-1, 196, 4)
        causal_mask = torch.triu(torch.ones(196, 196), diagonal=1).bool().to(DEVICE)
        x, _ = self.slot_attention(x, x, attn_mask=causal_mask)
        x = x.view(-1, 784)
        return self.net[2:](x)

def accuracy(model, loader, label_offset=0):
    model.eval(); correct = total = 0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(DEVICE), (y - label_offset).to(DEVICE)
            correct += (model(x).argmax(1) == y).sum().item(); total += len(y)
    return correct / total

def make_hook(sigma):
    def h(mod, inp, out): return out * (1 + sigma * torch.randn_like(out))
    return h

def train_epoch(model, loader, optimizer, label_offset=0, anv_noise=0.0, grad_proj_fn=None):
    model.train(); total_loss = 0; criterion = nn.CrossEntropyLoss()
    for x, y in loader:
        x, y = x.to(DEVICE), (y - label_offset).to(DEVICE)
        hooks = []
        if anv_noise > 0:
            for layer in model.net:
                if isinstance(layer, nn.ReLU):
                    hooks.append(layer.register_forward_hook(make_hook(anv_noise)))
        optimizer.zero_grad(); loss = criterion(model(x), y); loss.backward()
        if grad_proj_fn is not None: grad_proj_fn(model)
        optimizer.step()
        for h in hooks: h.remove()
        total_loss += loss.item()
    return total_loss / len(loader)

def collect_task_gradient_basis(model, loader, label_offset=0, n_batches=30):
    criterion = nn.CrossEntropyLoss(); basis = []
    for i, (x, y) in enumerate(loader):
        if i >= n_batches: break
        x, y = x.to(DEVICE), (y - label_offset).to(DEVICE)
        model.zero_grad(); criterion(model(x), y).backward()
        g = torch.cat([p.grad.data.clone().flatten() for p in model.parameters() if p.grad is not None])
        basis.append(g); model.zero_grad()
    return basis

def make_ogd_projector(basis_vecs, eps=1e-8):
    normed = [v / v.norm() for v in basis_vecs if v.norm() > eps]
    def project(model):
        g_flat = torch.cat([p.grad.data.flatten() for p in model.parameters() if p.grad is not None])
        for v in normed: g_flat = g_flat - (g_flat @ v) * v
        offset = 0
        for p in model.parameters():
            if p.grad is None: continue
            size = p.grad.data.numel()
            p.grad.data.copy_(g_flat[offset:offset + size].view_as(p.grad.data)); offset += size
    return project

EPOCHS_T1 = 5; EPOCHS_T2 = 5; LR = 1e-3; ANV_SIGMA = 0.15; OGD_BATCHES = 30
results = {}

def run_condition(name, model_type, use_anv=False, use_ogd=False):
    print(f"\n{'='*50}\n{name}\n{'='*50}")
    model = model_type().to(DEVICE)
    opt   = optim.SGD(model.parameters(), lr=LR, momentum=0.9)
    for ep in range(EPOCHS_T1):
        loss = train_epoch(model, train1, opt, label_offset=0, anv_noise=ANV_SIGMA if use_anv else 0.0)
        print(f"  T1 ep{ep+1}: loss={loss:.3f} acc={accuracy(model, test1):.3f}")
    t1_before = accuracy(model, test1, label_offset=0)
    proj_fn = None
    if use_ogd:
        proj_fn = make_ogd_projector(collect_task_gradient_basis(model, train1, n_batches=OGD_BATCHES))
    for ep in range(EPOCHS_T2):
        train_epoch(model, train2, opt, label_offset=5,
                    anv_noise=ANV_SIGMA if use_anv else 0.0, grad_proj_fn=proj_fn)
    t1_after = accuracy(model, test1, label_offset=0)
    t2_after = accuracy(model, test2, label_offset=5)
    bwt = t1_before - t1_after
    results[name] = dict(t1_before=t1_before, t1_after=t1_after, t2_after=t2_after, bwt=bwt)
    print(f"  BWT={bwt:.4f}  T2={t2_after:.4f}")

run_condition("Baseline (SGD)", JEPA, use_anv=False, use_ogd=False)
run_condition("Technique only", JEPA_Causal, use_anv=True, use_ogd=False)  
run_condition("OGD only", JEPA, use_anv=False, use_ogd=True)
run_condition("Combined", JEPA_Causal, use_anv=True, use_ogd=True)    

print("\n" + "="*60)
print(f"{'Condition':<20} {'T1_before':>10} {'T1_after':>9} {'T2_after':>9} {'BWT':>7}")
print("-"*60)
for k, r in results.items():
    print(f"{k:<20} {r['t1_before']:>10.4f} {r['t1_after']:>9.4f} {r['t2_after']:>9.4f} {r['bwt']:>7.4f}")
print("="*60)
assert results["Baseline (SGD)"]["t1_before"] >= 0.90, "Task-1 pre-training too weak"
baseline_bwt  = results["Baseline (SGD)"]["bwt"]
technique_bwt = results["Combined"]["bwt"]          
score = (baseline_bwt - technique_bwt) / (baseline_bwt + 1e-8)
score = round(min(max(float(score), 0.0), 1.0), 4)
print('OK All assertions passed')
print('RESULT:', score)