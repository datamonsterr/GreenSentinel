# ---- Stage 1: Build ----
FROM python:3.11-slim AS builder

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download and verify fraud classifier artifacts at pinned revision
COPY models/r3d/manifest.json /app/models/r3d/manifest.json
COPY scripts/download_artifacts.py /app/scripts/download_artifacts.py
RUN python /app/scripts/download_artifacts.py --manifest /app/models/r3d/manifest.json --out-dir /app/models/r3d

# ---- Stage 2: Production ----
FROM python:3.11-slim

WORKDIR /app

# Runtime OS dependencies: libgomp1 required for LightGBM OpenMP support
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Security: run as non-root user
RUN useradd -m -u 1000 appuser

# Copy application code
COPY . .

# Copy pre-downloaded and verified fraud classifier artifacts from builder
COPY --from=builder /app/models/r3d /app/models/r3d

# Create data directory with correct ownership
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request, os; port = os.environ.get('PORT', '8000'); urllib.request.urlopen(f'http://localhost:{port}/health')" || exit 1

CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

