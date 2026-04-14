FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=7860 \
    WHISPER_CACHE_DIR=/tmp/whisper_cache \
    ARGOS_MODELS_DIR=/tmp/argos_models \
    PIPER_VOICES_DIR=/tmp/piper_voices \
    GEMINI_CACHE_DB_PATH=/tmp/gemini_cache.db

# Install system dependencies
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
      ffmpeg \
      libsndfile1 \
      libgomp1 \
      wget \
      ca-certificates \
      git \
      curl \
      libjpeg-dev \
      zlib1g-dev \
      libpng-dev \
      libtiff-dev \
      libopenjp2-7-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

# Install Piper TTS binary
RUN wget -q https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz -O /tmp/piper.tar.gz && \
    mkdir -p /opt/piper && \
    tar -xzf /tmp/piper.tar.gz -C /opt/piper --strip-components=1 && \
    ln -sf /opt/piper/piper /usr/local/bin/piper && \
    rm -f /tmp/piper.tar.gz

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# 🔹 CRITICAL: Create /tmp directories with proper permissions for Hugging Face Spaces
RUN mkdir -p ${WHISPER_CACHE_DIR} ${ARGOS_MODELS_DIR} ${PIPER_VOICES_DIR} && \
    chmod -R 777 /tmp

# Pre-install Argos models
COPY scripts/install_argos_models.py /tmp/
RUN python /tmp/install_argos_models.py || echo "Argos models will download at runtime"

# Copy application code
COPY app/ ./app/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

EXPOSE ${PORT}

CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --log-level info