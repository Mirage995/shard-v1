import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import numpy as np
import torchvision
import torchvision.transforms as transforms

# Define constants
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Device:', DEVICE)

# Synthetic dataset
class SyntheticDataset(Dataset):
    def __init__(self, size, num_classes):
        self.size = size
        self.num_classes = num_classes
        self.data = np.random.rand(size, 3, 32, 32)
        self.labels = np.random.randint(0, num_classes, size)

    def __len__(self):
        return self.size

    def __getitem__(self, idx):
        return self.data[idx], self.labels[idx]

# Load synthetic dataset
dataset = SyntheticDataset(500, 100)
dataloader = DataLoader(dataset, batch_size=32, shuffle=True)

# Baseline model (simple CNN)
class BaselineModel(nn.Module):
    def __init__(self):
        super(BaselineModel, self).__init__()
        self.conv1 = nn.Conv2d(3, 6, 5)
        self.pool = nn.MaxPool2d(2, 2)
        self.conv2 = nn.Conv2d(6, 16, 5)
        self.fc1 = nn.Linear(16 * 5 * 5, 120)
        self.fc2 = nn.Linear(120, 84)
        self.fc3 = nn.Linear(84, 100)

    def forward(self, x):
        x = self.pool(nn.functional.relu(self.conv1(x)))
        x = self.pool(nn.functional.relu(self.conv2(x)))
        x = x.view(-1, 16 * 5 * 5)
        x = nn.functional.relu(self.fc1(x))
        x = nn.functional.relu(self.fc2(x))
        x = self.fc3(x)
        return x

# ViT model
class ViTModel(nn.Module):
    def __init__(self, num_heads):
        super(ViTModel, self).__init__()
        self.patch_embedding = nn.Conv2d(3, 256, kernel_size=4, stride=4)
        self.positional_embedding = nn.Parameter(torch.randn(1, 64, 256))
        self.attn = nn.MultiheadAttention(256, num_heads, batch_first=True)
        self.fc = nn.Linear(256, 100)

    def forward(self, x):
        x = self.patch_embedding(x)
        x = x.flatten(2)
        x = x.transpose(1, 2)
        x = x + self.positional_embedding
        x = self.attn(x, x, x)[0]
        x = x.mean(dim=1)
        x = self.fc(x)
        return x

# Train baseline model
baseline_model = BaselineModel().to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.SGD(baseline_model.parameters(), lr=0.01)
for epoch in range(10):
    for x, y in dataloader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        output = baseline_model(x)
        loss = criterion(output, y)
        loss.backward()
        optimizer.step()

# Train ViT models
vit_model_4heads = ViTModel(4).to(DEVICE)
vit_model_8heads = ViTModel(8).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.SGD(vit_model_4heads.parameters(), lr=0.01)
for epoch in range(10):
    for x, y in dataloader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        output = vit_model_4heads(x)
        loss = criterion(output, y)
        loss.backward()
        optimizer.step()

optimizer = optim.SGD(vit_model_8heads.parameters(), lr=0.01)
for epoch in range(10):
    for x, y in dataloader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        output = vit_model_8heads(x)
        loss = criterion(output, y)
        loss.backward()
        optimizer.step()

# Evaluate models
baseline_model.eval()
vit_model_4heads.eval()
vit_model_8heads.eval()
baseline_acc = 0
vit_4heads_acc = 0
vit_8heads_acc = 0
with torch.no_grad():
    for x, y in dataloader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        output = baseline_model(x)
        _, predicted = torch.max(output, 1)
        baseline_acc += (predicted == y).sum().item()

        output = vit_model_4heads(x)
        _, predicted = torch.max(output, 1)
        vit_4heads_acc += (predicted == y).sum().item()

        output = vit_model_8heads(x)
        _, predicted = torch.max(output, 1)
        vit_8heads_acc += (predicted == y).sum().item()

baseline_acc /= len(dataset)
vit_4heads_acc /= len(dataset)
vit_8heads_acc /= len(dataset)

# Assertions
assert baseline_acc > 0, "Baseline accuracy is zero"
assert vit_4heads_acc > 0, "ViT 4heads accuracy is zero"
assert vit_8heads_acc > 0, "ViT 8heads accuracy is zero"
print('OK All assertions passed')

# Compute score
delta_acc = vit_8heads_acc - vit_4heads_acc
score = max(0, min(1, delta_acc / 0.02))

# Print results
print("Baseline accuracy:", baseline_acc)
print("ViT 4heads accuracy:", vit_4heads_acc)
print("ViT 8heads accuracy:", vit_8heads_acc)
print("Delta accuracy:", delta_acc)
print("Score:", score)
print("Summary table:")
print("Model\tAccuracy")
print("Baseline\t", baseline_acc)
print("ViT 4heads\t", vit_4heads_acc)
print("ViT 8heads\t", vit_8heads_acc)

print('RESULT:', round(float(score), 4))