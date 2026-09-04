FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install build dependencies needed for building Python packages from source
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential ca-certificates ffmpeg git wget curl \
       libssl-dev libffi-dev pkg-config cargo \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /capture

# Install uv and install project and its dependencies into /app/.venv
COPY pyproject.toml ./
COPY bdfr ./bdfr
RUN pip install --no-cache-dir uv \
    && uv sync

# Final runtime image: smaller, without build tools
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Runtime deps (no compilers)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates ffmpeg wget \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /capture

# Copy the prepared virtualenv and app code from the builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/bdfr ./bdfr

VOLUME ["/capture"]

# Run the installed console script directly (from /app/.venv/bin)
ENTRYPOINT ["bdfr"]
# Default args: options file then capture directory
CMD ["clone", "/capture", "--opts", "/config.yml"]