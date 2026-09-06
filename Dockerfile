# syntax=docker/dockerfile:1
#
# One image, two commands — the api and the worker, exactly as ADR 0006 decided. They share
# the image because they share the code that decides what an answer is; they are separate
# processes because only the worker is CPU-bound and only the api receives ingress.
#
#   docker build --platform linux/amd64 --build-arg SQUADOPT_REPOSITORY_COMMIT=$(git rev-parse HEAD) -t squadopt-backend .
#
#   api     uvicorn --factory squadopt.api.runtime:build_app --host 0.0.0.0 --port 8000
#   worker  python -m squadopt.platform.advice_worker
#
# linux/amd64 is required, and not for wheel availability: the pinned OR-Tools release
# publishes Linux aarch64 wheels too. The solver's determinism and its time budget were
# *measured* on x86-64, and a deployment on an unmeasured architecture would be claiming
# numbers nobody has. aarch64 becomes eligible the day its parity is measured.
FROM --platform=linux/amd64 python:3.11-slim

# The commit is part of every answer's identity (it enters the cache key), and an image
# carries no .git for the process to ask. Build without it and the backend refuses to fill a
# cache rather than filling one it cannot name.
ARG SQUADOPT_REPOSITORY_COMMIT=""
ENV SQUADOPT_REPOSITORY_COMMIT=${SQUADOPT_REPOSITORY_COMMIT} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir ".[api]"

# The store is a mount, never image state: ADR 0006 rules out container-local storage
# because it is ephemeral across restart and replica replacement. The directory exists so a
# misconfigured deployment fails its startup probe loudly instead of writing into the layer.
RUN useradd --system --create-home --uid 10001 squadopt \
    && mkdir -p /mnt/squadopt-store \
    && chown squadopt:squadopt /mnt/squadopt-store
USER squadopt

ENV SQUADOPT_BACKEND_STORE_ROOT=/mnt/squadopt-store

EXPOSE 8000

# The api is the default because it is the one with ingress; the worker overrides the
# command. Neither is a shell form, so a stop signal reaches the process itself and the
# worker's graceful shutdown is not swallowed by an intermediate shell.
CMD ["uvicorn", "--factory", "squadopt.api.runtime:build_app", "--host", "0.0.0.0", "--port", "8000"]
