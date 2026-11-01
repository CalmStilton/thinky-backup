# thinky-backup

restic backups with consistent SQLite copies, freshness checks, scheduled restore drills and
Uptime Kuma push reporting. Runs as a container (`thinky-backup` entrypoint) or as a native
systemd unit on hosts without Docker.

## Commands

The image entrypoint is `thinky-backup <command>`. The default command is `schedule`.

| Command    | What it does |
|------------|--------------|
| `schedule` | Writes a crontab from `BACKUP_CRON`, `CHECK_CRON` and `DRILL_CRON`, then runs it in the foreground with supercronic. Needs at least one of the three. |
| `backup`   | Copies live SQLite databases to a clean scratch area (unless `SQLITE_SCAN=false`), checks that the files named in `FRESH_FILES` are recent, runs `restic backup` over `BACKUP_SOURCES`, then `restic forget --prune`. If `RESTIC_REPOSITORY2` is set, copies the new snapshots to that repo and prunes it too. Pushes one result to `KUMA_PUSH_BACKUP`. |
| `check`    | Runs `restic check --read-data-subset=$CHECK_READ_DATA_SUBSET` and pushes the result to `KUMA_PUSH_CHECK`. |
| `drill`    | Restores the latest snapshot's `DRILL_*` files into a temporary directory and proves they load: MariaDB dump loaded into a scratch server and row counted, SQLite `PRAGMA integrity_check`, `pg_restore --list` for a PostgreSQL dump. Pushes to `KUMA_PUSH_DRILL`. |
| `init`     | Initialises the restic repository if it does not exist yet. Safe to run more than once. |

## Configuration

All settings come from environment variables. `thinky_backup/config.py` is the source of truth:
the table below lists every variable it reads, with its default and meaning.

| Variable | Default | Meaning |
|----------|---------|---------|
| `RESTIC_REPOSITORY` | required | restic repository (path or URL) |
| `RESTIC_PASSWORD` | required | restic repository password |
| `BACKUP_HOST` | required | host label stored on snapshots (`--host`) |
| `BACKUP_TAG` | required | tag stored on snapshots (`--tag`) |
| `BACKUP_SOURCES` | empty | newline-separated paths to back up; `#` starts a comment line. Required by `backup`. |
| `BACKUP_EXCLUDES` | empty | newline-separated exclude patterns. A single name or glob (`logs`, `*.log`) matches a file or folder name anywhere. An absolute path (`/src/opt/app/cache`) excludes that path and everything under it. Nothing else is accepted: a relative pattern containing `/`, or a wildcard in an absolute path, is a configuration error. |
| `FORGET_ARGS` | `--keep-daily 7 --keep-weekly 4 --keep-monthly 6` | retention flags passed to `restic forget` |
| `SQLITE_SCAN` | `true` | find SQLite databases in `BACKUP_SOURCES` and back up consistent copies instead of the live files |
| `SCRATCH_DIR` | `/scratch` | working directory for SQLite copies and the generated exclude file |
| `FRESH_FILES` | empty | glob patterns for files other jobs produce (e.g. nightly dumps); `backup` fails if one is missing or older than `FRESH_MAX_AGE_HOURS` |
| `FRESH_MAX_AGE_HOURS` | `6` | maximum age, in hours, for `FRESH_FILES` |
| `CHECK_READ_DATA_SUBSET` | `5%` | share of pack data `check` reads on each run |
| `RESTIC_REPOSITORY2` | empty | optional second repository that receives a copy of each backup |
| `RESTIC_PASSWORD2` | empty | password for `RESTIC_REPOSITORY2`; required when that is set |
| `KUMA_PUSH_BACKUP` | empty | Uptime Kuma push URL for `backup` results |
| `KUMA_PUSH_CHECK` | empty | Uptime Kuma push URL for `check` results |
| `KUMA_PUSH_DRILL` | empty | Uptime Kuma push URL for `drill` results |
| `BACKUP_CRON` | empty | cron expression for `backup` (used by `schedule`) |
| `CHECK_CRON` | empty | cron expression for `check` (used by `schedule`) |
| `DRILL_CRON` | empty | cron expression for `drill` (used by `schedule`) |
| `DRILL_MARIADB_FILE` | empty | path inside the snapshot of a gzipped MariaDB dump to load in the drill |
| `DRILL_MARIADB_TABLE` | `entities` | table whose row count the MariaDB drill reports; plain names only |
| `DRILL_SQLITE_FILE` | empty | path inside the snapshot of a SQLite database to integrity-check |
| `DRILL_PGDUMP_FILE` | empty | path inside the snapshot of a PostgreSQL custom-format dump to list |
| `DRILL_RESTORE_APP` | empty | an app such as `opt/prowlarr`: the drill runs `thinky-restore app --dry-run` for it against the real repository; a failure is a drill failure |

The native script (below) reads its own variables: `CONF_DIR` (default `/etc/thinky-backup`),
`FORGET_ARGS` (same default as above), `KUMA_PUSH_BACKUP`, and the four restic and host
variables. It takes its paths from `$CONF_DIR/sources.txt` and, optionally,
`$CONF_DIR/excludes.txt`.

## Second repository

`RESTIC_REPOSITORY2` is optional. `thinky-backup init` only initialises the primary repository.
Initialise the second one once, by hand, with the same password settings the job will use:

```sh
RESTIC_REPOSITORY=<repo2> RESTIC_PASSWORD=<pw2> \
  RESTIC_FROM_REPOSITORY=<repo1> RESTIC_FROM_PASSWORD=<pw1> \
  restic init --copy-chunker-params
```

`check` only checks the primary repository. The second repository is not checked by any job.

## How SQLite is backed up

Opening a live WAL database on a read-only mount fails, because SQLite must write the `-shm`
file. Opening it read-write as root can leave root-owned `-wal` and `-shm` files behind for the
application. So each database and its `-wal` and `-journal` files are copied into a private
temp directory, the copy is opened there (SQLite replays the WAL), integrity-checked, and
written out as one clean file with the SQLite backup API. A copy torn by a concurrent write
fails the integrity check and is retried. The clean copies are backed up in place of the live
files, which are excluded.

Snapshotted databases are stored in the snapshot at `/scratch/sqlite/<original absolute path>`
(the default `SCRATCH_DIR`). The live file is not in the snapshot. So `DRILL_SQLITE_FILE` and
`restic restore --include` must use the `/scratch/sqlite/...` path. For example,
`/src/opt/app/app.db` is stored as `/scratch/sqlite/src/opt/app/app.db`.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | the job succeeded |
| 1 | the job ran but found a problem (restic failed, a file was stale, a drill check failed). Kuma gets a down push. |
| 2 | usage error or configuration error (unknown command, missing required variable, bad value). If the configuration loaded and the job has a push URL, Kuma gets a down push. |

An unexpected exception pushes "crashed" to Kuma and is re-raised, so the container log shows
the traceback.

## Native mode (hosts without Docker)

`native/thinky-backup-native.sh` runs `restic backup --files-from $CONF_DIR/sources.txt`, then
`restic forget --prune`, then pushes to `KUMA_PUSH_BACKUP`. It does not copy SQLite databases;
use the container for those. `native/thinky-backup.service` and `native/thinky-backup.timer`
run it nightly. A missing required variable exits before any Kuma push, so no result arrives;
the monitor's heartbeat interval is what catches it. A missing restic binary is reported as a
failed backup, so Kuma gets a down push. Put the variables in `/etc/thinky-backup/env` (the unit's `EnvironmentFile`),
install the script as `/usr/local/bin/thinky-backup-native`, and override the timer's
`OnCalendar` with a drop-in for each host's schedule.

## Guided restores: `thinky-restore`

`restore/thinky-restore` is one bash script that restores from these repositories by asking
questions, so nobody has to type multi-line shell during an emergency. It needs bash, `restic`
or `docker`, and root.

```sh
R=https://raw.githubusercontent.com/CalmStilton/thinky-backup/<commit>/restore
curl -fsSLo thinky-restore $R/thinky-restore
curl -fsSLo thinky-stack.map $R/thinky-stack.map     # optional, see below; keep it beside the script
sudo bash thinky-restore
```

| Menu choice | What it does |
|---|---|
| 1. Restore one app | Fetches the app's folder and its clean SQLite copies from a snapshot, shows what will change, stops the containers that use it, moves the current folder aside, copies the backup in, puts the SQLite copies over the live databases (removing stale `-wal` and `-shm` files), starts the containers again and prints how to undo. |
| 2. Restore a database | BookStack (MariaDB dump) or ReadMeABook (PostgreSQL dump). Saves the current database first, then loads the dump into the running container. `--scratch` loads it into a throwaway container with no network instead, to prove the dump works. |
| 3. Rebuild a whole machine | Lays down every app folder, creates and fills the Docker volumes, puts the SQLite copies over their live files and offers to start Portainer. Nothing existing is overwritten: it is moved aside. |
| 4. Ebooks or audiobooks | Finds a title or author in the media repository and copies it into a folder, or restores everything and puts it back where the map says. |
| 5. What is in the backups | Snapshots per machine with dates and sizes; `--filter TEXT` also lists matching files. |

The same commands work without the menu, which is how the tests drive it:
`thinky-restore app --host H --app NAME [--snapshot ID] [--dry-run] [--yes]`, and likewise
`db`, `host`, `media` and `snapshots` (`thinky-restore --help` lists the options).

Rules it keeps:

- **Nothing is replaced without you typing `yes`**, and `--dry-run` shows the plan and changes nothing.
- **Nothing is deleted.** What was there is renamed to `<path>.before-restore-YYYYmmdd-HHMM`. A database is
  saved to a file before the dump is loaded.
- **Secrets are never printed, logged, written to disk or put on a command line.** They are read with
  `read -s` (or taken from the environment) and passed to Docker as `-e NAME`. The script refuses to run
  with `bash -x`.
- Where restic runs: inside a running backup container if there is one (`backup-configs`, `backup-frigate`,
  `backup-alfiecodes`, `backup-media`: nothing to type); otherwise with the local `restic`; otherwise in a
  one-off container from `THINKY_RESTORE_IMAGE` (default `ghcr.io/calmstilton/thinky-backup:latest`).
  `--backend local|exec|image` and `--container NAME` override that.

Where snapshot folders belong on the machine: `/src/opt/NAME` goes to `/opt/NAME` and `/src/vol/NAME` to the
Docker volume `NAME`. Anything else needs a line in a map file (`/snapshot/path=/live/path`). The script
reads `thinky-stack.map` from beside itself, or the file named by `--map` or `THINKY_RESTORE_MAP`. A native
host (a snapshot without `/src`) is put back at the real paths, two levels down (for example
`/opt/AdGuardHome`). Optional non-secret defaults go in `/etc/thinky-restore.conf` (or
`THINKY_RESTORE_CONF`): `CONFIGS_REPOSITORY=` and `MEDIA_REPOSITORY=`.

Other settings: `THINKY_RESTORE_ENV_FILE` (a native host's saved settings, default
`/etc/thinky-backup/env`), `THINKY_RESTORE_MARIADB_IMAGE`, `THINKY_RESTORE_POSTGRES_IMAGE`,
`THINKY_RESTORE_PORTAINER_IMAGE`, and `TR_ROOT` (a prefix for every live path, used by the tests and
for restoring onto a mounted disk).

The image also ships the script as `/usr/local/bin/thinky-restore`. Setting `DRILL_RESTORE_APP` (for example
`opt/prowlarr`) makes the restore drill run a `--dry-run` of the `app` command against the real repository, so
the tool and the snapshot layout cannot drift apart unnoticed.

## Restoring a file

Restores run from the container. Restore into a scratch directory, then copy out what you need:

```sh
docker exec <ctr> restic restore latest --host H --tag T --target /scratch/restore --include <path>
# then copy the files out of /scratch/restore, for example
docker cp <ctr>:/scratch/restore/<path> ./restored/
```

Replace `H` and `T` with the `BACKUP_HOST` and `BACKUP_TAG` values, and `<path>` with the
absolute path as it was backed up. Restore a SQLite database this way and open the restored
file, not the live one.

## Build and test

```sh
scripts/test.sh            # runs the test suite in an Alpine container with the image's packages
docker build --target test .   # what CI runs
```

CI builds the test stage on every push and pull request, and publishes the final image on
pushes to `main`.
