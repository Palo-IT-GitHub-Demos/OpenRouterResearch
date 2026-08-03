# Base: Python 3.11 dev container (Debian Bullseye)
FROM mcr.microsoft.com/devcontainers/python:3.11-bullseye

# ── System dependencies for data/AI workloads ─────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# ── Python tooling ─────────────────────────────────────────────────────────────
RUN pip install --upgrade pip

# Core data/AI packages — pin versions in pyproject.toml for production
RUN pip install \
    numpy \
    pandas \
    scikit-learn \
    httpx \
    pydantic

# gen-e2 Lab Registry MCP server
RUN pip install "git+https://github.com/Palo-IT-GitHub-Demos/lab-registry-mcp@v0.2.0"

# ── Node.js 20 (via nvm already available in base image) ──────────────────────
# The devcontainer feature handles Node — this is just a reminder to keep in sync
# with the version in devcontainer.json features block if you add one.

WORKDIR /workspaces/app
