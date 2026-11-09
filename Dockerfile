# One image for every Python component; each Deployment/Job picks its module:
#   gateway: python -m rapport_gateway     briefer: python -m rapport_briefer
#   delegate: python -m rapport_delegate   operator: python -m rapport_operator
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONPATH=/app/src PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
COPY src ./src
COPY web ./web
EXPOSE 8080
CMD ["python", "-m", "rapport_gateway"]
