FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml Makefile ./
COPY src/ ./src/
COPY --from=frontend /app/frontend/dist /app/src/crabagent/static

RUN pip install --no-cache-dir '.[serve]'

EXPOSE 5210

VOLUME ["/data"]
ENV CRAB_DB_URL=sqlite+aiosqlite:////data/crabagent.db

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5210/health || exit 1

ENTRYPOINT ["crabagent"]
CMD ["--serve"]