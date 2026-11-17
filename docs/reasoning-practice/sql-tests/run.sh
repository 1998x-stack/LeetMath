#!/usr/bin/env bash
# Runs the smoke tests against a throwaway PostgreSQL database.
# Usage: PGHOST=... PGPORT=... PGUSER=... ./run.sh
set -euo pipefail
cd "$(dirname "$0")"
DB="leetmath_schema_smoke_$$"
createdb "$DB"
trap 'dropdb --if-exists "$DB"' EXIT
psql -X -q -v ON_ERROR_STOP=1 -d "$DB" -f 10_smoke.sql 2>&1
