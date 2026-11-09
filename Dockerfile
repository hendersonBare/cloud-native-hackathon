# One image for every Python component; each Deployment/Job picks its module:
#   gateway: python -m rapport_gateway     briefer: python -m rapport_briefer
#   delegate: python -m rapport_delegate   operator: python -m rapport_operator
# Built by .github/workflows/deploy.yaml on every push to main and pushed to GHCR (public).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
COPY contracts ./contracts
COPY src ./src
COPY web ./web
# The commit SHA the Action built; the gateway reports it on /healthz so a deploy can be verified.
ARG APP_VERSION=dev
ENV RAPPORT_VERSION=$APP_VERSION
# Non-root with a numeric UID so `runAsNonRoot: true` can be verified. HOME=/tmp for libraries that cache.
ENV HOME=/tmp
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "rapport_gateway"]
