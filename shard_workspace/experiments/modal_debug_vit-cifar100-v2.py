import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
import numpy as np

# Define device
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Device:', DEVICE)

# Set random seed
torch.manual_seed(42)
np.random.seed(42)

# Define data
transform = transforms.Compose([transforms.ToTensor()])
train_ds = datasets.CIFAR100(root='.', train=True, download=True, transform=transform)
test_ds  = datasets.CIFAR100(root='.', train=False, download=True, transform=transform)
train_loader = DataLoader(train_ds, batch_size=128, shuffle=True)
test_loader = DataLoader(test_ds, batch_size=128, shuffle=False)

# Define model
class ViT(nn.Module):
    def __init__(self, num_heads):
        super(ViT, self).__init__()
        self.patch_embedding = nn.Conv2d(3, 256, kernel_size=4, stride=4)
        self.positional_encoding = nn.Parameter(torch.randn(1, 64, 256))
        self.attention = nn.MultiheadAttention(256, num_heads, batch_first=True)
        self.classifier = nn.Linear(256, 100)

    def forward(self, x):
        x = self.patch_embedding(x)
        x = x.view(x.size(0), -1, 256)
        x = x + self.positional_encoding
        x = self.attention(x, x, x)[0]
        x = x.mean(dim=1)
        x = self.classifier(x)
        return x

# Train model with 4 heads
model_4heads = ViT(4).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model_4heads.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in train_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        output = model_4heads(x)
        loss = criterion(output, y)
        loss.backward()
        optimizer.step()

# Evaluate model with 4 heads
model_4heads.eval()
acc_4heads = 0
with torch.no_grad():
    for x, y in test_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        output = model_4heads(x)
        _, predicted = torch.max(output, 1)
        acc_4heads += (predicted == y).sum().item()
acc_4heads /= len(test_ds)

# Train model with 8 heads
model_8heads = ViT(8).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model_8heads.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in train_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        output = model_8heads(x)
        loss = criterion(output, y)
        loss.backward()
        optimizer.step()

# Evaluate model with 8 heads
model_8heads.eval()
acc_8heads = 0
with torch.no_grad():
    for x, y in test_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        output = model_8heads(x)
        _, predicted = torch.max(output, 1)
        acc_8heads += (predicted == y).sum().item()
acc_8heads /= len(test_ds)

# Baseline model
class Baseline(nn.Module):
    def __init__(self):
        super(Baseline, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, kernel_size=3)
        self.conv2 = nn.Conv2d(64, 128, kernel_size=3)
        self.conv3 = nn.Conv2d(128, 256, kernel_size=3)
        self.classifier = nn.Linear(256*4*4, 100)

    def forward(self, x):
        x = nn.functional.relu(nn.functional.max_pool2d(self.conv1(x), 2))
        x = nn.functional.relu(nn.functional.max_pool2d(self.conv2(x), 2))
        x = nn.functional.relu(nn.functional.max_pool2d(self.conv3(x), 2))
        x = x.view(x.size(0), -1)
        x = self.classifier(x)
        return x

# Train baseline model
baseline_model = Baseline().to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(baseline_model.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in train_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        output = baseline_model(x)
        loss = criterion(output, y)
        loss.backward()
        optimizer.step()

# Evaluate baseline model
baseline_model.eval()
acc_baseline = 0
with torch.no_grad():
    for x, y in test_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        output = baseline_model(x)
        _, predicted = torch.max(output, 1)
        acc_baseline += (predicted == y).sum().item()
acc_baseline /= len(test_ds)

# Assertions
assert acc_4heads >= 0.0 and acc_4heads <= 1.0, "Accuracy out of range"
assert acc_8heads >= 0.0 and acc_8heads <= 1.0, "Accuracy out of range"
assert acc_baseline >= 0.0 and acc_baseline <= 1.0, "Accuracy out of range"
print('OK All assertions passed')

# Compute score
delta_acc = acc_8heads - acc_4heads
score = max(0.0, min(1.0, delta_acc / 0.02))

# Print summary table
print("Summary Table:")
print(f"Baseline Accuracy: {acc_baseline:.4f}")
print(f"4 Heads Accuracy: {acc_4heads:.4f}")
print(f"8 Heads Accuracy: {acc_8heads:.4f}")
print(f"Delta Accuracy: {delta_acc:.4f}")

print('RESULT:', round(float(score), 4))