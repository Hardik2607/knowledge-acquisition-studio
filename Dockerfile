# Knowledge Acquisition Studio (KAS) — Docker Container
FROM python:3.11-slim-bookworm

# Environment configuration
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies:
# - ffmpeg: visual keyframe extraction & audio transcoding
# - git: codebase skill acquisition adapter
# - curl: healthcheck & network downloads
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python packaging tools and dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir yt-dlp

# Copy source code and install package
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Copy project workspaces, configurations, and runtime skeleton
COPY config/ ./config/
COPY projects/ ./projects/
COPY runtime/ ./runtime/

# Expose Web Studio port
EXPOSE 8765

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8765/api/projects || exit 1

# Launch Web Studio
CMD ["kas", "serve", "--host", "0.0.0.0", "--port", "8765"]
