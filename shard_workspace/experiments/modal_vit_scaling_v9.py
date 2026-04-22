import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import numpy as np
import torchvision
from torchvision import transforms
import pandas as pd
import matplotlib.pyplot as plt
from sklearn.metrics import accuracy_score

# Define DEVICE
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Device:', DEVICE)

# Generate synthetic data
class SyntheticDataset(Dataset):
    def __init__(self, size=500):
        self.size = size
        self.data = np.random.rand(size, 3, 32, 32).astype(np.float32)
        self.labels = np.random.randint(0, 100, size)

    def __len__(self):
        return self.size

    def __getitem__(self, idx):
        return self.data[idx], self.labels[idx]

# Define data transforms
transform = transforms.Compose([transforms.ToTensor()])

# Load synthetic dataset
dataset = SyntheticDataset()
dataloader = DataLoader(dataset, batch_size=32, shuffle=True)

# Define ViT model
class ViT(nn.Module):
    def __init__(self, num_heads):
        super(ViT, self).__init__()
        self.patch_embedding = nn.Conv2d(3, 256, kernel_size=4, stride=4)
        self.positional_embedding = nn.Parameter(torch.randn(1, 64, 256))
        self.attention = nn.MultiheadAttention(256, num_heads, batch_first=True)
        self.classifier = nn.Linear(256, 100)

    def forward(self, x):
        x = self.patch_embedding(x)
        x = x.view(-1, 64, 256)
        x = x + self.positional_embedding
        x = self.attention(x, x, x)[0]
        x = x.mean(dim=1)
        x = self.classifier(x)
        return x

# Define baseline model
class Baseline(nn.Module):
    def __init__(self):
        super(Baseline, self).__init__()
        self.conv1 = nn.Conv2d(3, 64, kernel_size=3)
        self.conv2 = nn.Conv2d(64, 128, kernel_size=3)
        self.fc1 = nn.Linear(128*6*6, 128)
        self.fc2 = nn.Linear(128, 100)

    def forward(self, x):
        x = nn.functional.relu(nn.functional.max_pool2d(self.conv1(x), 2))
        x = nn.functional.relu(nn.functional.max_pool2d(self.conv2(x), 2))
        x = x.view(-1, 128*6*6)
        x = nn.functional.relu(self.fc1(x))
        x = self.fc2(x)
        return x

# Train ViT-4heads model
vit_4heads = ViT(4).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(vit_4heads.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in dataloader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        outputs = vit_4heads(x)
        loss = criterion(outputs, y)
        loss.backward()
        optimizer.step()

# Train ViT-8heads model
vit_8heads = ViT(8).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(vit_8heads.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in dataloader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        outputs = vit_8heads(x)
        loss = criterion(outputs, y)
        loss.backward()
        optimizer.step()

# Train baseline model
baseline = Baseline().to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(baseline.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in dataloader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        outputs = baseline(x)
        loss = criterion(outputs, y)
        loss.backward()
        optimizer.step()

# Evaluate models
vit_4heads.eval()
vit_8heads.eval()
baseline.eval()
vit_4heads_acc = 0
vit_8heads_acc = 0
baseline_acc = 0
with torch.no_grad():
    for x, y in dataloader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        outputs = vit_4heads(x)
        _, predicted = torch.max(outputs, 1)
        vit_4heads_acc += (predicted == y).sum().item()

        outputs = vit_8heads(x)
        _, predicted = torch.max(outputs, 1)
        vit_8heads_acc += (predicted == y).sum().item()

        outputs = baseline(x)
        _, predicted = torch.max(outputs, 1)
        baseline_acc += (predicted == y).sum().item()

vit_4heads_acc /= len(dataset)
vit_8heads_acc /= len(dataset)
baseline_acc /= len(dataset)

# Assertions
assert vit_4heads_acc > 0.1, "ViT-4heads accuracy is too low"
assert vit_8heads_acc > vit_4heads_acc, "ViT-8heads accuracy is not higher than ViT-4heads"
print('OK All assertions passed')

# Compute score
delta_acc = vit_8heads_acc - vit_4heads_acc
score = delta_acc / (1 - baseline_acc)

# Print results
print("ViT-4heads Accuracy:", vit_4heads_acc)
print("ViT-8heads Accuracy:", vit_8heads_acc)
print("Baseline Accuracy:", baseline_acc)
print("Delta Accuracy:", delta_acc)
print("Score:", score)

# Print summary table
print("Summary Table:")
print(pd.DataFrame({
    "Model": ["Baseline", "ViT-4heads", "ViT-8heads"],
    "Accuracy": [baseline_acc, vit_4heads_acc, vit_8heads_acc]
}))

# FINAL line
print('RESULT:', round(float(score), 4))