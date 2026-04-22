import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import numpy as np
import torchvision
import torchvision.transforms as transforms
from sklearn.metrics import accuracy_score

# Set device
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
        x = x.view(x.size(0), -1, 256)
        x = x + self.positional_embedding
        x = self.attention(x, x, x)[0]
        x = x.mean(dim=1)
        x = self.classifier(x)
        return x

# Define baseline model
class Baseline(nn.Module):
    def __init__(self):
        super(Baseline, self).__init__()
        self.conv = nn.Conv2d(3, 256, kernel_size=4, stride=4)
        self.fc = nn.Linear(256*64, 100)

    def forward(self, x):
        x = self.conv(x)
        x = x.view(x.size(0), -1)
        x = self.fc(x)
        return x

# Train models
def train(model, device, loader, optimizer, criterion):
    model.train()
    for batch_idx, (data, target) in enumerate(loader):
        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        loss = criterion(output, target)
        loss.backward()
        optimizer.step()

# Evaluate models
def evaluate(model, device, loader):
    model.eval()
    correct = 0
    with torch.no_grad():
        for data, target in loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            _, predicted = torch.max(output, 1)
            correct += (predicted == target).sum().item()
    accuracy = correct / len(loader.dataset)
    return accuracy

# Main
dataset = SyntheticDataset()
loader = DataLoader(dataset, batch_size=32, shuffle=True)

vit_4heads = ViT(4).to(DEVICE)
vit_8heads = ViT(8).to(DEVICE)
baseline = Baseline().to(DEVICE)

criterion = nn.CrossEntropyLoss()
optimizer_4heads = optim.Adam(vit_4heads.parameters(), lr=0.001)
optimizer_8heads = optim.Adam(vit_8heads.parameters(), lr=0.001)
optimizer_baseline = optim.Adam(baseline.parameters(), lr=0.001)

for epoch in range(10):
    train(vit_4heads, DEVICE, loader, optimizer_4heads, criterion)
    train(vit_8heads, DEVICE, loader, optimizer_8heads, criterion)
    train(baseline, DEVICE, loader, optimizer_baseline, criterion)

acc_4heads = evaluate(vit_4heads, DEVICE, loader)
acc_8heads = evaluate(vit_8heads, DEVICE, loader)
acc_baseline = evaluate(baseline, DEVICE, loader)

assert acc_4heads > 0.1, "4-heads model accuracy is too low"
assert acc_8heads > acc_4heads, "8-heads model accuracy is not higher than 4-heads"

print('OK All assertions passed')

delta_acc = acc_8heads - acc_4heads
score = delta_acc / (1 - acc_baseline)
print('Baseline accuracy:', acc_baseline)
print('4-heads accuracy:', acc_4heads)
print('8-heads accuracy:', acc_8heads)
print('Delta accuracy:', delta_acc)
print('Score:', score)
print('Summary:')
print('Model\tAccuracy')
print('Baseline\t', acc_baseline)
print('4-heads\t', acc_4heads)
print('8-heads\t', acc_8heads)
print('RESULT:', round(float(score), 4))