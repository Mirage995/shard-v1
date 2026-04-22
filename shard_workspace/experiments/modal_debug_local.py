import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
from torch.utils.data import DataLoader
import numpy as np

# Set device
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Device:', DEVICE)

# Set random seed
np.random.seed(42)
torch.manual_seed(42)

# Load CIFAR-100 dataset
transform = transforms.Compose([transforms.ToTensor()])
train_ds = datasets.CIFAR100(root='.', train=True, download=True, transform=transform)
test_ds  = datasets.CIFAR100(root='.', train=False, download=True, transform=transform)
train_loader = DataLoader(train_ds, batch_size=128, shuffle=True)
test_loader  = DataLoader(test_ds, batch_size=128, shuffle=False)

# Define ViT model
class ViT(nn.Module):
    def __init__(self, num_heads):
        super(ViT, self).__init__()
        self.patch_embedding = nn.Conv2d(3, 256, kernel_size=4, stride=4)
        self.positional_encoding = nn.Parameter(torch.randn(1, 64, 256))
        self.attn = nn.MultiheadAttention(256, num_heads, batch_first=True)
        self.classifier = nn.Linear(256, 100)

    def forward(self, x):
        x = self.patch_embedding(x)
        x = x.view(-1, 64, 256)
        x = x + self.positional_encoding
        x = self.attn(x, x, x)[0]
        x = x.mean(dim=1)
        x = self.classifier(x)
        return x

# Train ViT with 4 heads
vit_4heads = ViT(4).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(vit_4heads.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in train_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        outputs = vit_4heads(x)
        loss = criterion(outputs, y)
        loss.backward()
        optimizer.step()

# Evaluate ViT with 4 heads
vit_4heads.eval()
acc_4heads = 0
with torch.no_grad():
    for x, y in test_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        outputs = vit_4heads(x)
        _, predicted = torch.max(outputs, 1)
        acc_4heads += (predicted == y).sum().item()
acc_4heads /= len(test_ds)

# Train ViT with 8 heads
vit_8heads = ViT(8).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(vit_8heads.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in train_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        outputs = vit_8heads(x)
        loss = criterion(outputs, y)
        loss.backward()
        optimizer.step()

# Evaluate ViT with 8 heads
vit_8heads.eval()
acc_8heads = 0
with torch.no_grad():
    for x, y in test_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        outputs = vit_8heads(x)
        _, predicted = torch.max(outputs, 1)
        acc_8heads += (predicted == y).sum().item()
acc_8heads /= len(test_ds)

# Compute delta_acc
delta_acc = acc_8heads - acc_4heads

# Add assertions
assert acc_4heads > 0.1, "4-heads accuracy is too low"
assert acc_8heads > acc_4heads, "8-heads accuracy is not higher than 4-heads accuracy"
print('OK All assertions passed')

# Compute score
score = delta_acc / (1 - acc_4heads + 1e-8) if acc_4heads < 1 else delta_acc
score = max(0.0, min(score, 1.0))

# Print summary table
print("Summary Table:")
print("Model\tAccuracy")
print("4-heads\t{:.4f}".format(acc_4heads))
print("8-heads\t{:.4f}".format(acc_8heads))

# Print result
print('RESULT:', round(float(score), 4))