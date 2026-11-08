#!/bin/sh
# Drop privileges to PUID:PGID after making the data volume writable.
# Unraid users typically run 99:100 (nobody:users); most Linux users are 1000:1000.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
  if ! getent group "$PGID" >/dev/null 2>&1; then
    groupadd -g "$PGID" ruleshelf
  fi
  if ! getent passwd "$PUID" >/dev/null 2>&1; then
    # The image already ships a "ruleshelf" user at 1000, so use a unique name
    # when the requested uid differs (Unraid's 99, for example).
    useradd -u "$PUID" -g "$PGID" -M -s /usr/sbin/nologin "ruleshelf_${PUID}"
  fi
  mkdir -p /data
  chown -R "$PUID:$PGID" /data
  exec gosu "$PUID:$PGID" "$@"
fi

exec "$@"
