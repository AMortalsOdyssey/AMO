FROM python:3.13-slim

ARG cacheDir=/tmp/cache

WORKDIR /app

# Install uv via pip (faster than pulling from ghcr.io)
RUN pip install uv -i https://pypi.tuna.tsinghua.edu.cn/simple

# Copy dependency files first (for better layer caching)
# Dependencies change rarely, code changes often
COPY server/pyproject.toml server/uv.lock ./

# Install dependencies with cache directory
# Uses platform-provided cache when available
ENV UV_CACHE_DIR=${cacheDir}/uv
RUN uv sync --frozen --no-dev

# Copy application code last (changes here won't invalidate dependency cache)
COPY server/app/ app/

EXPOSE 8100

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
