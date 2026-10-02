#!/bin/sh
set -eu

PORT_VALUE="${PORT:-8080}"
AUTO_FIX_PERMS="${APP_AUTO_FIX_DATA_PERMS:-1}"

# Default runtime identity (kept for compatibility with existing images).
DEFAULT_UID="${APP_UID:-10001}"
DEFAULT_GID="${APP_GID:-10001}"
TARGET_UID="$DEFAULT_UID"
TARGET_GID="$DEFAULT_GID"

# komari agent 
KOMARI_SERVER="${KOMARI_SERVER:-}"
KOMARI_SECRET="${KOMARI_SECRET:-}"

# run komari-agent
if [ -n "$KOMARI_SERVER" ] && [ -n "$KOMARI_SECRET" ]; then
    echo "INFO: Starting komari agent..."
    /app/komari-agent -e "$KOMARI_SERVER" -t "$KOMARI_SECRET" --disable-auto-update &
else
    echo "INFO: Komari agent skipped (credentials not configured)."
fi

# If /data is mounted, prefer running as its owner/group to avoid chmod 777.
if [ -d /data ]; then
  DATA_UID="$(stat -c '%u' /data 2>/dev/null || true)"
  DATA_GID="$(stat -c '%g' /data 2>/dev/null || true)"
  if [ -n "${DATA_UID}" ] && [ -n "${DATA_GID}" ]; then
    TARGET_UID="${DATA_UID}"
    TARGET_GID="${DATA_GID}"
  fi
fi

UVICORN_CMD="uvicorn backend.main:app --host 0.0.0.0 --port ${PORT_VALUE} --workers 1 --limit-concurrency 20"

if [ "$(id -u)" -eq 0 ]; then
  if [ "${AUTO_FIX_PERMS}" != "0" ] && [ -d /data ]; then
    echo "INFO: fixing /data permissions for ${TARGET_UID}:${TARGET_GID} ..."
    # Ensure core paths exist first.
    mkdir -p /data/.signer /data/sessions /data/logs || true

    # Repair ownership and write bits for existing historical files.
    # This avoids readonly sqlite and permission denied after image upgrades.
    chown -R "${TARGET_UID}:${TARGET_GID}" /data 2>/dev/null || true
    chmod -R u+rwX,g+rwX /data 2>/dev/null || true
  fi


  # If mounted volume is root-owned, keep root to preserve writability.
  if [ "${TARGET_UID}" = "0" ] || [ "${TARGET_GID}" = "0" ]; then
    exec $UVICORN_CMD
  fi
  exec gosu "${TARGET_UID}:${TARGET_GID}" $UVICORN_CMD
fi

exec $UVICORN_CMD
