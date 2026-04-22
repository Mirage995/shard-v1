import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
import numpy as np
import time

# Set device
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Device:', DEVICE)

# Set seed for reproducibility
torch.manual_seed(42)
np.random.seed(42)

# Define data transforms
transform = transforms.Compose([transforms.ToTensor()])

# Load CIFAR-100 dataset
train_dataset = datasets.CIFAR100('~/.pytorch/CIFAR_data/', download=True, train=True, transform=transform)
test_dataset = datasets.CIFAR100('~/.pytorch/CIFAR_data/', download=True, train=False, transform=transform)

# Define data loaders
train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=128, shuffle=True)
test_loader = torch.utils.data.DataLoader(test_dataset, batch_size=128, shuffle=False)

# Define patch embedding layer
class PatchEmbed(nn.Module):
    def __init__(self, img_size, patch_size, embed_dim):
        super().__init__()
        self.patch_size = patch_size
        self.proj = nn.Conv2d(3, embed_dim, kernel_size=patch_size, stride=patch_size)

    def forward(self, x):
        x = self.proj(x).flatten(2).transpose(1, 2)
        return x

# Define ViT model
class ViT(nn.Module):
    def __init__(self, img_size, patch_size, embed_dim, num_heads, num_classes):
        super().__init__()
        self.patch_embed = PatchEmbed(img_size, patch_size, embed_dim)
        self.attn = nn.MultiheadAttention(embed_dim, num_heads, batch_first=True)
        self.fc = nn.Linear(embed_dim, num_classes)

    def forward(self, x):
        x = self.patch_embed(x)
        x, _ = self.attn(x, x)
        x = x.mean(dim=1)
        x = self.fc(x)
        return x

# Define baseline ViT model with 4 heads
baseline_model = ViT(img_size=32, patch_size=4, embed_dim=256, num_heads=4, num_classes=100).to(DEVICE)

# Define ViT model with 8 heads
vit_8heads_model = ViT(img_size=32, patch_size=4, embed_dim=256, num_heads=8, num_classes=100).to(DEVICE)

# Define optimizer and loss function
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(baseline_model.parameters(), lr=0.001)

# Train baseline model
baseline_model.train()
for epoch in range(10):
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(DEVICE), target.to(DEVICE)
        optimizer.zero_grad()
        output = baseline_model(data)
        loss = criterion(output, target)
        loss.backward()
        optimizer.step()

# Train ViT model with 8 heads
vit_8heads_model.train()
optimizer = optim.Adam(vit_8heads_model.parameters(), lr=0.001)
for epoch in range(10):
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(DEVICE), target.to(DEVICE)
        optimizer.zero_grad()
        output = vit_8heads_model(data)
        loss = criterion(output, target)
        loss.backward()
        optimizer.step()

# Evaluate models
baseline_model.eval()
vit_8heads_model.eval()
baseline_correct = 0
vit_8heads_correct = 0
with torch.no_grad():
    for data, target in test_loader:
        data, target = data.to(DEVICE), target.to(DEVICE)
        output = baseline_model(data)
        _, predicted = torch.max(output, 1)
        baseline_correct += (predicted == target).sum().item()

        output = vit_8heads_model(data)
        _, predicted = torch.max(output, 1)
        vit_8heads_correct += (predicted == target).sum().item()

baseline_acc = baseline_correct / len(test_dataset)
vit_8heads_acc = vit_8heads_correct / len(test_dataset)

# Compute delta accuracy
delta_acc = vit_8heads_acc - baseline_acc

# Verify meaningful output values
assert delta_acc >= -0.1, "Delta accuracy is too low"
assert vit_8heads_acc > 0.1, "ViT-8heads accuracy is too low"

print('OK All assertions passed')

# Compute score
score = delta_acc / 0.02

# Print summary table
print("Summary Table:")
print("Model\tAccuracy")
print(f"Baseline\t{baseline_acc:.4f}")
print(f"ViT-8heads\t{vit_8heads_acc:.4f}")

# Print result
print('RESULT:', round(float(max(0.0, min(score, 1.0))), 4))