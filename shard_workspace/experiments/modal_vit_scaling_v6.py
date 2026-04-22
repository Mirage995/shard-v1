import torch
torch.set_default_dtype(torch.float32)
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import matplotlib.pyplot as plt

# Set device
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Device:', DEVICE)

# Synthetic data generation
np.random.seed(0)
X = np.random.rand(500, 32, 32, 3)
y = np.random.randint(0, 100, 500)

# Data preprocessing
transform = transforms.Compose([transforms.ToTensor()])
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Define ViT model
class ViT(nn.Module):
    def __init__(self, num_heads):
        super(ViT, self).__init__()
        self.patch_embedding = nn.Conv2d(3, 128, kernel_size=4, stride=4)
        self.positional_embedding = nn.Parameter(torch.randn(1, 64, 128))
        self.attn = nn.MultiheadAttention(128, num_heads, batch_first=True)
        self.mlp = nn.Sequential(
            nn.Linear(128, 256),
            nn.ReLU(),
            nn.Linear(256, 128)
        )
        self.classifier = nn.Linear(128, 100)

    def forward(self, x):
        x = self.patch_embedding(x)
        x = x.view(-1, 64, 128)
        x = x + self.positional_embedding
        x, _ = self.attn(x, x, x)
        x = x.mean(dim=1)
        x = self.mlp(x)
        x = self.classifier(x)
        return x

# Train ViT-4heads model
vit_4heads = ViT(4).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(vit_4heads.parameters(), lr=0.001)
X_train_tensor = torch.tensor(X_train).permute(0, 3, 1, 2).to(DEVICE)
y_train_tensor = torch.tensor(y_train).to(DEVICE)
for epoch in range(10):
    optimizer.zero_grad()
    outputs = vit_4heads(X_train_tensor)
    loss = criterion(outputs, y_train_tensor)
    loss.backward()
    optimizer.step()

# Train ViT-8heads model
vit_8heads = ViT(8).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(vit_8heads.parameters(), lr=0.001)
for epoch in range(10):
    optimizer.zero_grad()
    outputs = vit_8heads(X_train_tensor)
    loss = criterion(outputs, y_train_tensor)
    loss.backward()
    optimizer.step()

# Evaluate models
X_test_tensor = torch.tensor(X_test).permute(0, 3, 1, 2).to(DEVICE)
y_test_tensor = torch.tensor(y_test).to(DEVICE)
vit_4heads.eval()
vit_8heads.eval()
with torch.no_grad():
    outputs_4heads = vit_4heads(X_test_tensor)
    outputs_8heads = vit_8heads(X_test_tensor)
    _, predicted_4heads = torch.max(outputs_4heads, 1)
    _, predicted_8heads = torch.max(outputs_8heads, 1)
    acc_4heads = accuracy_score(y_test, predicted_4heads.cpu().numpy())
    acc_8heads = accuracy_score(y_test, predicted_8heads.cpu().numpy())

# Compute delta accuracy
delta_acc = acc_8heads - acc_4heads

# Assertions
assert acc_4heads > 0, "Accuracy of ViT-4heads is not greater than 0"
assert acc_8heads > 0, "Accuracy of ViT-8heads is not greater than 0"
print('OK All assertions passed')

# Compute score
score = (delta_acc - 0.02) / (1 - 0.02) if delta_acc > 0.02 else 0.0

# Print result
print('RESULT:', round(float(score), 4))