FROM python:3.13-alpine AS base
COPY apk-packages.txt /tmp/apk-packages.txt
RUN apk add --no-cache $(cat /tmp/apk-packages.txt)
WORKDIR /app
COPY pyproject.toml ./
COPY thinky_backup ./thinky_backup
COPY --chmod=755 restore/thinky-restore /usr/local/bin/thinky-restore
RUN pip install --no-cache-dir --root-user-action=ignore .
ENTRYPOINT ["thinky-backup"]
CMD ["schedule"]

FROM base AS test
RUN apk add --no-cache bash curl coreutils grep findutils sed shellcheck
ENV THINKY_TEST_CONTAINER=1
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements-dev.txt
COPY tests ./tests
COPY native ./native
COPY restore ./restore
RUN python -m pytest -q

FROM base
