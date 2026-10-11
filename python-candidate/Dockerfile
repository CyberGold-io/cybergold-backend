# Local qualification artifact only; not wired into branch desired publication.
FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8
WORKDIR /candidate
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
COPY src ./src
COPY NOTICE-V8.txt ./NOTICE-V8.txt
ENV PYTHONPATH=/candidate/src PYTHONUNBUFFERED=1 NODE_ENV=production HOST=0.0.0.0 PORT=3000
ARG CYBERGOLD_BACKEND_COMMIT
ENV CYBERGOLD_BACKEND_COMMIT=${CYBERGOLD_BACKEND_COMMIT}
USER 65532:65532
EXPOSE 3000 3001
STOPSIGNAL SIGTERM
LABEL io.cybergold.backend.runtime="python"
CMD ["python", "-m", "cybergold_candidate.main"]
