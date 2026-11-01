#!/usr/bin/env bash
# restic backup of the paths in $CONF_DIR/sources.txt, then prune, then report to Uptime Kuma.
# For hosts without Docker. The container image does the same job (plus SQLite copies).
set -uo pipefail
CONF_DIR=${CONF_DIR:-/etc/thinky-backup}
: "${RESTIC_REPOSITORY:?}" "${RESTIC_PASSWORD:?}" "${BACKUP_HOST:?}" "${BACKUP_TAG:?}"
FORGET_ARGS=${FORGET_ARGS:---keep-daily 7 --keep-weekly 4 --keep-monthly 6}
job="$BACKUP_HOST/$BACKUP_TAG backup"

push() {
  if [ -z "${KUMA_PUSH_BACKUP:-}" ]; then echo "no KUMA_PUSH_BACKUP; result: $1 $2"; return 0; fi
  curl -fsS -m 10 -G "${KUMA_PUSH_BACKUP%%\?*}" --data-urlencode "status=$1" \
    --data-urlencode "msg=$2" --data-urlencode "ping=" >/dev/null || echo "Kuma push failed" >&2
}

excludes=()
if [ -f "$CONF_DIR/excludes.txt" ]; then excludes=(--exclude-file "$CONF_DIR/excludes.txt"); fi

restic --retry-lock 30m backup --host "$BACKUP_HOST" --tag "$BACKUP_TAG" \
  --files-from "$CONF_DIR/sources.txt" ${excludes[@]+"${excludes[@]}"}
rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ]; then push down "$job: restic backup failed (exit $rc)"; exit 1; fi

# shellcheck disable=SC2086  # FORGET_ARGS is a list of flags
restic --retry-lock 30m forget --host "$BACKUP_HOST" --tag "$BACKUP_TAG" --group-by host,tags --prune $FORGET_ARGS
frc=$?
if [ "$rc" -eq 3 ]; then push down "$job: some source files could not be read (restic exit 3)"; exit 1; fi
if [ "$frc" -ne 0 ]; then push down "$job: restic forget failed (exit $frc)"; exit 1; fi
push up "$job ok"
