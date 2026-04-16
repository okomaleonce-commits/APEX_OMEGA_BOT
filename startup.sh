#!/usr/bin/env bash
# APEX OMEGA — startup.sh
set -e
echo "=== APEX OMEGA BOOT $(date -u) ==="
echo "Python: $(python --version)"
echo "PORT:   ${PORT:-10000}"
echo "DB:     ${DB_PATH:-/var/data/apex_signals.db}"

# Ensure data dir writable (Render disk may take a moment)
for dir in "${DATA_DIR:-/var/data}" "/tmp"; do
  if mkdir -p "$dir" 2>/dev/null && touch "$dir/.test" 2>/dev/null; then
    rm -f "$dir/.test"
    export DATA_DIR="$dir"
    export DB_PATH="$dir/apex_signals.db"
    echo "DATA_DIR resolved: $DATA_DIR"
    break
  fi
done

exec python main.py
