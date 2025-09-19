# Multi-stage Dockerfile for Periodeec
# Optimized for size, security, and caching

# Build stage - contains all build dependencies
FROM python:3.11-slim-bookworm AS builder

# Install system dependencies needed for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set up Python environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements first for better layer caching
COPY requirements.txt /tmp/
RUN pip install --upgrade pip setuptools wheel \
    && pip install -r /tmp/requirements.txt

# Copy source code and install application
COPY . /app
WORKDIR /app
RUN pip install -e .

# Production stage - minimal runtime image
FROM python:3.11-slim-bookworm AS production

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create application user and group
ARG PUID=1000
ARG PGID=1000
ARG UNAME=periodeec

RUN groupadd -g $PGID -o $UNAME \
    && useradd -m -u $PUID -g $PGID -o -s /bin/bash $UNAME

# Set up application directories
ENV WORKDIR=/app \
    CONFIG_DIR=/config \
    DATA_DIR=/data \
    CACHE_DIR=/cache

RUN mkdir -p $WORKDIR $CONFIG_DIR $DATA_DIR $CACHE_DIR \
    && chown -R $PUID:$PGID $WORKDIR $CONFIG_DIR $DATA_DIR $CACHE_DIR

# Copy virtual environment from builder
COPY --from=builder --chown=$PUID:$PGID /opt/venv /opt/venv

# Copy application from builder
COPY --from=builder --chown=$PUID:$PGID /app $WORKDIR

# Set up environment
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=$CONFIG_DIR \
    XDG_CONFIG_HOME=$CONFIG_DIR \
    PERIODEEC_CONFIG=$CONFIG_DIR/config.yaml \
    PERIODEEC_CACHE_DIR=$CACHE_DIR

# Switch to non-root user
USER $UNAME
WORKDIR $WORKDIR

# Create cache directories with proper permissions
RUN mkdir -p $CACHE_DIR/spotify $CACHE_DIR/beets \
    && mkdir -p $DATA_DIR/music $DATA_DIR/downloads $DATA_DIR/failed

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from periodeec.config import load_config; load_config('$PERIODEEC_CONFIG')" || exit 1

# Expose commonly used ports (if web interface is added later)
EXPOSE 8080

# Set up signal handling and use exec form for proper signal propagation
ENTRYPOINT ["python", "-m", "periodeec.main"]
# Default to scheduled mode, but allow overriding via docker run arguments
CMD ["--run"]

# Labels for better maintainability
LABEL org.opencontainers.image.title="Periodeec" \
      org.opencontainers.image.description="Automated music synchronization system" \
      org.opencontainers.image.vendor="Periodeec Project" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/anatosun/periodeec"