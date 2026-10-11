# syntax=docker/dockerfile:1.7
# Python owns RPC/cache; the isolated Node SDK worker only computes snapshots.
FROM node:26.10.0-bookworm-slim@sha256:662933cf47f013bc8e4beb31a6116448427a82057ba7c42c97e4c5ba766504c2 AS sdk
WORKDIR /sdk
COPY package.json package-lock.json ./
COPY vendor ./vendor
COPY scripts/patch-uniswap-sdk.mjs ./scripts/patch-uniswap-sdk.mjs
RUN npm ci --omit=dev --ignore-scripts && node scripts/patch-uniswap-sdk.mjs
COPY src/uniswap-sdk ./src/uniswap-sdk
FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8
WORKDIR /candidate
COPY python-candidate/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libatomic1 && rm -rf /var/lib/apt/lists/*
COPY --from=sdk /usr/local/bin/node /usr/local/bin/node
COPY --from=sdk /sdk/node_modules ./node_modules
COPY --from=sdk /sdk/vendor ./vendor
COPY --from=sdk /sdk/src/uniswap-sdk ./src/uniswap-sdk
COPY --from=sdk /sdk/package.json ./package.json
COPY python-candidate/src ./src
COPY python-candidate/schema ./schema
COPY python-candidate/NOTICE-V8.txt ./NOTICE-V8.txt
ENV PYTHONPATH=/candidate/src PYTHONUNBUFFERED=1 NODE_ENV=production HOST=0.0.0.0 PORT=3000
ARG CYBERGOLD_BACKEND_COMMIT
ENV CYBERGOLD_BACKEND_COMMIT=${CYBERGOLD_BACKEND_COMMIT}
USER 65532:65532
EXPOSE 3000 3001
STOPSIGNAL SIGTERM
LABEL io.cybergold.backend.runtime="python"
CMD ["python", "-m", "cybergold_candidate.main"]
