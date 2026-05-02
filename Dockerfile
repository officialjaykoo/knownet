FROM rust:1-bookworm AS core-builder
WORKDIR /app/apps/core
COPY apps/core/Cargo.toml apps/core/Cargo.lock ./
COPY apps/core/src ./src
COPY apps/api/knownet_api/db/schema.sql /app/apps/api/knownet_api/db/schema.sql
RUN cargo build --release

FROM node:20-bookworm AS web-builder
WORKDIR /app/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
ARG NEXT_PUBLIC_API_BASE=
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
RUN mkdir -p public
RUN npm run build

FROM python:3.10-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    SQLITE_PATH=/data/knownet.db \
    RUST_CORE_PATH=/app/bin/knownet-core \
    LOCAL_EMBEDDING_AUTO_LOAD=false \
    LOCAL_EMBEDDING_LOCAL_FILES_ONLY=true \
    NEXT_PUBLIC_API_BASE= \
    KNOWNET_API_INTERNAL=http://127.0.0.1:8000 \
    PORT=3000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm tini \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api /app/apps/api
RUN pip install --no-cache-dir -e /app/apps/api

COPY --from=core-builder /app/apps/core/target/release/knownet-core /app/bin/knownet-core
COPY --from=web-builder /app/apps/web/.next /app/apps/web/.next
COPY --from=web-builder /app/apps/web/public /app/apps/web/public
COPY --from=web-builder /app/apps/web/package.json /app/apps/web/package.json
COPY --from=web-builder /app/apps/web/package-lock.json /app/apps/web/package-lock.json
COPY docker/entrypoint.sh /app/docker/entrypoint.sh

WORKDIR /app/apps/web
RUN npm ci --omit=dev && chmod +x /app/bin/knownet-core /app/docker/entrypoint.sh

EXPOSE 3000
VOLUME ["/data"]

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
