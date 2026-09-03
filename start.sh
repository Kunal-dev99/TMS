#!/usr/bin/env bash
# Starts everything. One command, because two terminals on the day of a
# demonstration is one more thing to go wrong.
#
#   ./start.sh            the real API on 8000, and the surface
#   ./start.sh --mock     the mock server on 8001 instead
#   ./start.sh --reseed   drop and reload the seed first
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend="$root/backend"
frontend="$root/frontend"

mock=0
reseed=0
for arg in "$@"; do
  case "$arg" in
    --mock) mock=1 ;;
    --reseed) reseed=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$backend"
echo "Building the schema from the migrations."
python -m alembic upgrade head

if [[ $reseed -eq 1 || ! -f "$backend/treasury.db" ]]; then
  echo "Loading the seed."
  python -m seed.seed
fi

if [[ $mock -eq 1 ]]; then
  module="mock.main:app"; port=8001; label="mock"
else
  module="app.main:app"; port=8000; label="api"
fi

echo "Starting the $label on port $port."
python -m uvicorn "$module" --port "$port" --reload &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT

export TREASURY_API_ORIGIN="http://127.0.0.1:$port"

echo "Starting the surface on port 3000."
echo "Open http://localhost:3000"
cd "$frontend"
npm run dev
