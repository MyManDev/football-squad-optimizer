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
#
# 3.13 for one demonstrated reason: the pinned set cannot be installed on 3.11.
# `numpy==2.5.2` and `scipy==1.18.0` declare `requires_python >=3.12`, so pip refuses them
# there before wheel availability is even consulted. An image that installs
# `constraints.txt` therefore runs 3.13, and the 3.11 support floor keeps its own proof
# where it already lived: CI's `gates (py3.11)` installs the declared ranges.
#
# What this earns, stated no wider than it is: the image holds the same package versions as
# `constraints.txt`. It does **not** establish numerical equivalence with the environment the
# committed measurements were recorded in — that was a different operating system, and
# comparing the two is its own measurement, not a packaging claim. Nor is this the repair of
# a build that was broken: the previous image installed the declared ranges and built fine.
# What changed is what the image pins to.
#
# `python:3.13-slim` is a mutable tag. It is the right thing to name in a build, and the
# wrong thing to name in a deployment: a release runs the digest of the image that was
# actually tested (see docs/backend_runbook.md), never the tag it was built from.
FROM --platform=linux/amd64 python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# One version source, the same file the 3.13 gate installs. `-c` constrains rather than
# requires, so the dev tools pinned alongside the runtime ones stay out of the image and no
# second dependency file has to exist to keep them out.
#
# This installs the pinned runtime environment; it is not a byte-reproducible build. pip does
# not apply `--constraint` to build requirements, so the wheel for this package itself is
# built under isolation against whatever `setuptools` pip fetches that day. That affects the
# packaging of our own pure-Python source only, never a pinned dependency.
COPY pyproject.toml README.md constraints.txt ./
COPY src ./src
RUN python -m pip install --no-cache-dir -c constraints.txt ".[api]"

# After the install, so the bytecode for the scientific stack is compiled once here instead of
# on every container start — and never written at runtime, where the filesystem is either
# read-only or a shared mount that has better things to hold.
ENV PYTHONDONTWRITEBYTECODE=1

# The commit is part of every answer's identity (it enters the cache key), and an image
# carries no .git for the process to ask. It is stamped after the install so that changing
# commits does not invalidate the dependency layer, and it is *checked here* rather than left
# to the runtime: the process's own fallback shells out to `git`, which this base image does
# not carry, so a forgotten build-arg would surface as a FileNotFoundError at request time
# instead of a refusal at build time.
ARG SQUADOPT_REPOSITORY_COMMIT=""
RUN printf '%s' "${SQUADOPT_REPOSITORY_COMMIT}" | grep -Eq '^[0-9a-f]{40}$' || { \
        echo "SQUADOPT_REPOSITORY_COMMIT must be 40 lowercase hex characters;" >&2; \
        echo "got '${SQUADOPT_REPOSITORY_COMMIT}'. Build with" >&2; \
        echo "  --build-arg SQUADOPT_REPOSITORY_COMMIT=\$(git rev-parse HEAD)" >&2; \
        exit 1; \
    }
ENV SQUADOPT_REPOSITORY_COMMIT=${SQUADOPT_REPOSITORY_COMMIT}
LABEL org.opencontainers.image.revision=${SQUADOPT_REPOSITORY_COMMIT} \
      org.opencontainers.image.source="https://github.com/MyManDev/football-squad-optimizer"

# The store is a mount, never image state: ADR 0006 rules out container-local storage
# because it is ephemeral across restart and replica replacement.
#
# So the image neither creates the directory nor defaults the variable that names it. Both
# were here and both were wrong: with them, a `docker run` that forgot its volume got a
# writable directory on the container's own disk, passed every capability check, and served
# happily until the next restart took the queue with it. Without them a forgotten volume
# fails at configuration, and a mistyped path fails at the probe.
#
# The group is created explicitly rather than with `useradd --user-group`, which takes its gid
# from the system range and would not mirror the uid. Whoever prepares the shared mount needs
# both numbers, and discovering them by running the image is the step that gets skipped — a
# store the runtime cannot write is a service that never becomes ready.
RUN groupadd --system --gid 10001 squadopt \
    && useradd --system --create-home --gid 10001 --uid 10001 squadopt
USER squadopt

EXPOSE 8000

# The api is the default because it is the one with ingress; the worker overrides the
# command. Neither is a shell form, so a stop signal reaches the process itself and the
# worker's graceful shutdown is not swallowed by an intermediate shell.
CMD ["uvicorn", "--factory", "squadopt.api.runtime:build_app", "--host", "0.0.0.0", "--port", "8000"]
