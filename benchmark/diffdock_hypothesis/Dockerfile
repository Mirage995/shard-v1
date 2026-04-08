FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# System deps
RUN apt-get update && apt-get install -y \
    python3.10 python3-pip python3-dev \
    git wget curl libopenbabel-dev openbabel \
    && rm -rf /var/lib/apt/lists/*

RUN ln -sf /usr/bin/python3.10 /usr/bin/python

# Python deps for DiffDock
RUN pip install --no-cache-dir \
    torch==2.0.1+cu118 torchvision --index-url https://download.pytorch.org/whl/cu118

RUN pip install --no-cache-dir \
    torch-geometric==2.3.1 \
    torch-scatter torch-sparse torch-cluster \
    -f https://data.pyg.org/whl/torch-2.0.1+cu118.html

RUN pip install --no-cache-dir \
    e3nn==0.5.1 \
    spyrmsd \
    rdkit \
    biopython \
    pandas numpy scipy \
    matplotlib seaborn \
    tqdm requests

# Clone DiffDock
RUN git clone https://github.com/gcorso/DiffDock.git /diffdock
WORKDIR /diffdock

# Download model weights (HuggingFace, no auth needed)
RUN python - <<'EOF'
from huggingface_hub import hf_hub_download
import os
os.makedirs("workdir/paper_score_model", exist_ok=True)
os.makedirs("workdir/paper_confidence_model", exist_ok=True)
for fname in ["best_model.pt", "model_parameters.yml"]:
    hf_hub_download(
        repo_id="gcorso/DiffDock",
        filename=f"paper_score_model/{fname}",
        local_dir="workdir"
    )
    hf_hub_download(
        repo_id="gcorso/DiffDock",
        filename=f"paper_confidence_model/{fname}",
        local_dir="workdir"
    )
EOF

# Copy experiment scripts
COPY run_experiment.py /experiment/run_experiment.py
COPY analyze.py /experiment/analyze.py
COPY prepare_dataset.py /experiment/prepare_dataset.py

WORKDIR /experiment
