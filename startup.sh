#!/usr/bin/env bash
# APEX OMEGA — startup.sh
# Safe startup: ensure data dir exists, then launch bot
set -e

echo "=== APEX OMEGA BOOT ==="
echo "Python: $(python --version)"
echo "DB_PATH: ${DB_PATH:-/var/data/apex_signals.db}"
echo "DATA_DIR: ${DATA_DIR:-/var/data}"

# Ensure data directory
mkdir -p "${DATA_DIR:-/var/data}" 2>/dev/null || mkdir -p /tmp/apex_data
export DATA_DIR="${DATA_DIR:-/var/data}"
export DB_PATH="${DB_PATH:-${DATA_DIR}/apex_signals.db}"

echo "Starting bot..."
exec python main.py
