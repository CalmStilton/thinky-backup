#!/usr/bin/env bash
# Run the tests with the same Alpine packages the image uses.
# CI builds the real image; this works where `docker build` can't (e.g. an LXC with AppArmor).
set -euo pipefail
cd "$(dirname "$0")/.."
docker run --rm --security-opt apparmor=unconfined -e THINKY_TEST_CONTAINER=1 -v "$PWD:/repo:ro" python:3.13-alpine sh -euc '
  apk add --no-cache -q $(cat /repo/apk-packages.txt) bash curl coreutils grep findutils sed shellcheck >/dev/null
  cp -r /repo /w && cd /w
  pip install -q --root-user-action=ignore -r requirements-dev.txt .
  python -m pytest -q "$@"' sh "$@"
