import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
import numpy as np
import torchvision
import torchvision.transforms as transforms

# Set device
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print('Device:', DEVICE)

# Synthetic dataset
class SyntheticDataset(Dataset):
    def __init__(self, size=500):
        self.size = size
        self.data = np.random.rand(size, 3, 32, 32)
        self.labels = np.random.randint(0, 100, size)

    def __len__(self):
        return self.size

    def __getitem__(self, idx):
        return self.data[idx], self.labels[idx]

# Data loader
dataset = SyntheticDataset()
data_loader = DataLoader(dataset, batch_size=32, shuffle=True)

# ViT model
class ViT(nn.Module):
    def __init__(self, num_heads):
        super(ViT, self).__init__()
        self.patch_embedding = nn.Conv2d(3, 256, kernel_size=4, stride=4)
        self.positional_embedding = nn.Parameter(torch.randn(1, 64, 256))
        self.attention = nn.MultiHeadAttention(256, num_heads, batch_first=True)
        self.classifier = nn.Linear(256, 100)

    def forward(self, x):
        x = self.patch_embedding(x)
        x = x.view(x.size(0), -1, 256)
        x = x + self.positional_embedding
        x = self.attention(x, x, x)[0]
        x = x.mean(dim=1)
        x = self.classifier(x)
        return x

# Baseline model (4 heads)
baseline_model = ViT(4).to(DEVICE)

# Intervention model (8 heads)
intervention_model = ViT(8).to(DEVICE)

# Loss function and optimizer
criterion = nn.CrossEntropyLoss()
optimizer_baseline = optim.Adam(baseline_model.parameters(), lr=0.001)
optimizer_intervention = optim.Adam(intervention_model.parameters(), lr=0.001)

# Train models
for epoch in range(10):
    baseline_model.train()
    intervention_model.train()
    for batch in data_loader:
        inputs, labels = batch
        inputs, labels = inputs.to(DEVICE), labels.to(DEVICE)
        optimizer_baseline.zero_grad()
        optimizer_intervention.zero_grad()
        outputs_baseline = baseline_model(inputs)
        outputs_intervention = intervention_model(inputs)
        loss_baseline = criterion(outputs_baseline, labels)
        loss_intervention = criterion(outputs_intervention, labels)
        loss_baseline.backward()
        loss_intervention.backward()
        optimizer_baseline.step()
        optimizer_intervention.step()

# Evaluate models
baseline_model.eval()
intervention_model.eval()
baseline_correct = 0
intervention_correct = 0
with torch.no_grad():
    for batch in data_loader:
        inputs, labels = batch
        inputs, labels = inputs.to(DEVICE), labels.to(DEVICE)
        outputs_baseline = baseline_model(inputs)
        outputs_intervention = intervention_model(inputs)
        _, predicted_baseline = torch.max(outputs_baseline, 1)
        _, predicted_intervention = torch.max(outputs_intervention, 1)
        baseline_correct += (predicted_baseline == labels).sum().item()
        intervention_correct += (predicted_intervention == labels).sum().item()

# Compute accuracy
baseline_accuracy = baseline_correct / len(dataset)
intervention_accuracy = intervention_correct / len(dataset)

# Assertions
assert baseline_accuracy >= 0 and baseline_accuracy <= 1, "Baseline accuracy out of range"
assert intervention_accuracy >= 0 and intervention_accuracy <= 1, "Intervention accuracy out of range"
print('OK All assertions passed')

# Compute score
delta_acc = intervention_accuracy - baseline_accuracy
score = delta_acc / 0.02 if delta_acc > 0.02 else 0.0

# Print result
print('RESULT:', round(float(score), 4))