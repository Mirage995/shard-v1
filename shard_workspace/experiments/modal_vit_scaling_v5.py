import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, transforms
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from torch.utils.data import Dataset, DataLoader, TensorDataset

# Set device
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Device:', DEVICE)

# Generate synthetic data
np.random.seed(0)
torch.manual_seed(0)
X = np.random.rand(500, 3, 32, 32)
y = np.random.randint(0, 100, 500)

# Define transforms
transform = transforms.Compose([transforms.ToTensor()])

# Define dataset and data loader
class SyntheticDataset(Dataset):
    def __init__(self, X, y, transform):
        self.X = X
        self.y = y
        self.transform = transform

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        x = self.X[idx]
        y = self.y[idx]
        if self.transform:
            x = self.transform(x)
        return x, y

dataset = SyntheticDataset(X, y, transform)
data_loader = DataLoader(dataset, batch_size=32, shuffle=True)

# Define baseline model
class BaselineModel(nn.Module):
    def __init__(self):
        super(BaselineModel, self).__init__()
        self.fc1 = nn.Linear(32*32*3, 128)
        self.fc2 = nn.Linear(128, 100)

    def forward(self, x):
        x = x.view(-1, 32*32*3)
        x = torch.relu(self.fc1(x))
        x = self.fc2(x)
        return x

# Define ViT model
class ViTModel(nn.Module):
    def __init__(self, num_heads):
        super(ViTModel, self).__init__()
        self.patch_embedding = nn.Conv2d(3, 128, kernel_size=4, stride=4)
        self.positional_embedding = nn.Parameter(torch.randn(1, 64, 128))
        self.attention = nn.MultiheadAttention(128, num_heads, batch_first=True)
        self.fc = nn.Linear(128, 100)

    def forward(self, x):
        x = self.patch_embedding(x)
        x = x.view(-1, 64, 128)
        x = x + self.positional_embedding
        x = self.attention(x, x, x)[0]
        x = x.mean(dim=1)
        x = self.fc(x)
        return x

# Train baseline model
baseline_model = BaselineModel().to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(baseline_model.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in data_loader:
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
optimizer = optim.Adam(vit_model_4heads.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in data_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        optimizer.zero_grad()
        output = vit_model_4heads(x)
        loss = criterion(output, y)
        loss.backward()
        optimizer.step()

optimizer = optim.Adam(vit_model_8heads.parameters(), lr=0.001)
for epoch in range(10):
    for x, y in data_loader:
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
baseline_predictions = []
vit_4heads_predictions = []
vit_8heads_predictions = []
with torch.no_grad():
    for x, y in data_loader:
        x, y = x.to(DEVICE), y.to(DEVICE)
        baseline_output = baseline_model(x)
        vit_4heads_output = vit_model_4heads(x)
        vit_8heads_output = vit_model_8heads(x)
        baseline_predictions.extend(torch.argmax(baseline_output, dim=1).cpu().numpy())
        vit_4heads_predictions.extend(torch.argmax(vit_4heads_output, dim=1).cpu().numpy())
        vit_8heads_predictions.extend(torch.argmax(vit_8heads_output, dim=1).cpu().numpy())

# Compute accuracy
baseline_accuracy = accuracy_score(y, baseline_predictions)
vit_4heads_accuracy = accuracy_score(y, vit_4heads_predictions)
vit_8heads_accuracy = accuracy_score(y, vit_8heads_predictions)

# Assertions
assert baseline_accuracy > 0.1, "Baseline accuracy is too low"
assert vit_8heads_accuracy > vit_4heads_accuracy, "ViT-8heads accuracy is not higher than ViT-4heads accuracy"
print('OK All assertions passed')

# Compute score
delta_acc = vit_8heads_accuracy - vit_4heads_accuracy
score = delta_acc / (1 - vit_4heads_accuracy)
print('Baseline accuracy:', baseline_accuracy)
print('ViT-4heads accuracy:', vit_4heads_accuracy)
print('ViT-8heads accuracy:', vit_8heads_accuracy)
print('Delta accuracy:', delta_acc)
print('Score:', score)
print('Summary table:')
print(pd.DataFrame({
    'Model': ['Baseline', 'ViT-4heads', 'ViT-8heads'],
    'Accuracy': [baseline_accuracy, vit_4heads_accuracy, vit_8heads_accuracy]
}))
print('RESULT:', round(float(score), 4))