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
    def __init__(self, size):
        self.size = size
        self.data = np.random.rand(size, 3, 32, 32)
        self.labels = np.random.randint(0, 100, size)

    def __len__(self):
        return self.size

    def __getitem__(self, idx):
        return self.data[idx], self.labels[idx]

# Load dataset
dataset = SyntheticDataset(500)
dataloader = DataLoader(dataset, batch_size=32, shuffle=True)

# Define ViT model
class ViT(nn.Module):
    def __init__(self, num_heads):
        super(ViT, self).__init__()
        self.patch_embedding = nn.Conv2d(3, 256, kernel_size=4, stride=4)
        self.positional_encoding = nn.Parameter(torch.randn(1, 64, 256))
        self.attention = nn.MultiheadAttention(256, num_heads, batch_first=True)
        self.classifier = nn.Linear(256, 100)

    def forward(self, x):
        x = self.patch_embedding(x)
        x = x.view(-1, 64, 256)
        x = x + self.positional_encoding
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
        self.fc1 = nn.Linear(128 * 6 * 6, 128)
        self.fc2 = nn.Linear(128, 100)

    def forward(self, x):
        x = torch.relu(self.conv1(x))
        x = torch.relu(self.conv2(x))
        x = x.view(-1, 128 * 6 * 6)
        x = torch.relu(self.fc1(x))
        x = self.fc2(x)
        return x

# Train models
def train(model, dataloader, epochs):
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    for epoch in range(epochs):
        for x, y in dataloader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            optimizer.zero_grad()
            outputs = model(x)
            loss = criterion(outputs, y)
            loss.backward()
            optimizer.step()
    return model

# Train ViT models
vit_4heads = ViT(4).to(DEVICE)
vit_8heads = ViT(8).to(DEVICE)
vit_4heads = train(vit_4heads, dataloader, 10)
vit_8heads = train(vit_8heads, dataloader, 10)

# Train baseline model
baseline = Baseline().to(DEVICE)
baseline = train(baseline, dataloader, 10)

# Evaluate models
def evaluate(model, dataloader):
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for x, y in dataloader:
            x, y = x.to(DEVICE), y.to(DEVICE)
            outputs = model(x)
            _, predicted = torch.max(outputs, 1)
            correct += (predicted == y).sum().item()
            total += y.size(0)
    return correct / total

vit_4heads_acc = evaluate(vit_4heads, dataloader)
vit_8heads_acc = evaluate(vit_8heads, dataloader)
baseline_acc = evaluate(baseline, dataloader)

# Assertions
assert vit_4heads_acc > 0.1, "ViT 4 heads accuracy is too low"
assert vit_8heads_acc > vit_4heads_acc, "ViT 8 heads accuracy is not higher than ViT 4 heads"

print('OK All assertions passed')

# Compute score
delta_acc = vit_8heads_acc - vit_4heads_acc
score = delta_acc / (1 - baseline_acc)
print("Baseline accuracy:", baseline_acc)
print("ViT 4 heads accuracy:", vit_4heads_acc)
print("ViT 8 heads accuracy:", vit_8heads_acc)
print("Delta accuracy:", delta_acc)
print("Score:", score)

# Print summary table
print("Summary table:")
print("Model\tAccuracy")
print("Baseline\t", baseline_acc)
print("ViT 4 heads\t", vit_4heads_acc)
print("ViT 8 heads\t", vit_8heads_acc)

print('RESULT:', round(float(score), 4))