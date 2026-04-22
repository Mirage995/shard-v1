import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms
import numpy as np

# Set device
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Device:', DEVICE)

# Hyperparameters
batch_size = 32
epochs = 10
lr = 0.001
seed = 42

# Set seed
torch.manual_seed(seed)
np.random.seed(seed)

# Synthetic data generation
transform = transforms.Compose([transforms.ToTensor()])
train_dataset = datasets.CIFAR100('~/.pytorch/CIFAR_data/', download=True, train=True, transform=transform)
test_dataset = datasets.CIFAR100('~/.pytorch/CIFAR_data/', download=True, train=False, transform=transform)
train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
test_loader = torch.utils.data.DataLoader(test_dataset, batch_size=batch_size, shuffle=False)

# Baseline model (ViT with 4 heads)
class BaselineViT(nn.Module):
    def __init__(self):
        super(BaselineViT, self).__init__()
        self.patch_embedding = nn.Conv2d(3, 256, kernel_size=4, stride=4)
        self.attn = nn.MultiheadAttention(256, 4, batch_first=True)
        self.fc = nn.Linear(256, 100)

    def forward(self, x):
        x = self.patch_embedding(x)
        x = x.view(-1, 256, 256)
        x = x.permute(0, 2, 1)
        x, _ = self.attn(x, x, x)
        x = x.mean(dim=1)
        x = self.fc(x)
        return x

# Model with 8 heads
class EightHeadsViT(nn.Module):
    def __init__(self):
        super(EightHeadsViT, self).__init__()
        self.patch_embedding = nn.Conv2d(3, 256, kernel_size=4, stride=4)
        self.attn = nn.MultiheadAttention(256, 8, batch_first=True)
        self.fc = nn.Linear(256, 100)

    def forward(self, x):
        x = self.patch_embedding(x)
        x = x.view(-1, 256, 256)
        x = x.permute(0, 2, 1)
        x, _ = self.attn(x, x, x)
        x = x.mean(dim=1)
        x = self.fc(x)
        return x

# Initialize models and optimizer
baseline_model = BaselineViT().to(DEVICE)
eight_heads_model = EightHeadsViT().to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer_baseline = optim.Adam(baseline_model.parameters(), lr=lr)
optimizer_eight_heads = optim.Adam(eight_heads_model.parameters(), lr=lr)

# Train models
for epoch in range(epochs):
    baseline_model.train()
    eight_heads_model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(DEVICE), target.to(DEVICE)
        optimizer_baseline.zero_grad()
        optimizer_eight_heads.zero_grad()
        output_baseline = baseline_model(data)
        output_eight_heads = eight_heads_model(data)
        loss_baseline = criterion(output_baseline, target)
        loss_eight_heads = criterion(output_eight_heads, target)
        loss_baseline.backward()
        loss_eight_heads.backward()
        optimizer_baseline.step()
        optimizer_eight_heads.step()

# Evaluate models
baseline_model.eval()
eight_heads_model.eval()
baseline_correct = 0
eight_heads_correct = 0
with torch.no_grad():
    for data, target in test_loader:
        data, target = data.to(DEVICE), target.to(DEVICE)
        output_baseline = baseline_model(data)
        output_eight_heads = eight_heads_model(data)
        _, predicted_baseline = torch.max(output_baseline, 1)
        _, predicted_eight_heads = torch.max(output_eight_heads, 1)
        baseline_correct += (predicted_baseline == target).sum().item()
        eight_heads_correct += (predicted_eight_heads == target).sum().item()

# Compute accuracy
baseline_accuracy = baseline_correct / len(test_dataset)
eight_heads_accuracy = eight_heads_correct / len(test_dataset)

# Compute delta accuracy
delta_accuracy = eight_heads_accuracy - baseline_accuracy

# Assertions
assert baseline_accuracy > 0.1, "Baseline accuracy is too low"
assert eight_heads_accuracy > baseline_accuracy, "Eight heads model does not outperform baseline"

print('OK All assertions passed')

# Compute score
score = delta_accuracy / 0.02 if delta_accuracy > 0.02 else 0.0

print('RESULT:', round(float(score), 4))