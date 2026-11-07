#!/bin/bash
# Phase 15 live verification: compile + consolidate on two local endpoints.
# Same capture set on both, separate databases. Prints the fact table after each pass.
set -u
ROOT="${HOME}/cairnstone"
OUT="${ROOT}/eval/consolidation-live"
mkdir -p "$OUT"
export PYTHONPATH="${ROOT}/src"

run_endpoint () {
  name="$1"; base="$2"; model="$3"
  db="${OUT}/${name}.db"
  rm -f "$db" "$db-wal" "$db-shm"
  echo "===== endpoint ${name}: ${base} model=${model} ====="
  CAIRNSTONE_BASE_URL="$base" CAIRNSTONE_MODEL="$model" \
    python3 -m cairnstone.cli init --db "$db" 2>&1 | tail -2

  printf 'Caroline: I live in Berlin and I am single.\n' > "${OUT}/${name}-1.txt"
  printf 'Caroline: I moved to Lisbon last month and I got married.\n' > "${OUT}/${name}-2.txt"
  printf 'Caroline: Things changed again, I am single now.\n' > "${OUT}/${name}-3.txt"
  printf 'Caroline: I live in Berlin and I am single.\n' > "${OUT}/${name}-4.txt"

  CAIRNSTONE_BASE_URL="$base" CAIRNSTONE_MODEL="$model" \
    python3 -m cairnstone.cli ingest --db "$db" --file "${OUT}/${name}-1.txt" --kind chat --source "live-${name}-1" --captured-at '2023-05-01T09:00:00+00:00' 2>&1 | tail -1
  CAIRNSTONE_BASE_URL="$base" CAIRNSTONE_MODEL="$model" \
    python3 -m cairnstone.cli ingest --db "$db" --file "${OUT}/${name}-2.txt" --kind chat --source "live-${name}-2" --captured-at '2023-06-01T09:00:00+00:00' 2>&1 | tail -1
  CAIRNSTONE_BASE_URL="$base" CAIRNSTONE_MODEL="$model" \
    python3 -m cairnstone.cli ingest --db "$db" --file "${OUT}/${name}-3.txt" --kind chat --source "live-${name}-3" --captured-at '2023-07-01T09:00:00+00:00' 2>&1 | tail -1
  CAIRNSTONE_BASE_URL="$base" CAIRNSTONE_MODEL="$model" \
    python3 -m cairnstone.cli ingest --db "$db" --file "${OUT}/${name}-4.txt" --kind chat --source "live-${name}-4" --captured-at '2023-08-01T09:00:00+00:00' 2>&1 | tail -1

  echo "-- compile --"
  CAIRNSTONE_BASE_URL="$base" CAIRNSTONE_MODEL="$model" \
    python3 -m cairnstone.cli compile --db "$db" --max-reject-rate 0.9 2>&1 | grep -E '^ok:|^error:' | tail -2
  echo "-- consolidate pass 1 --"
  python3 -m cairnstone.cli consolidate --db "$db" 2>&1 | grep -E '^ok:|^error:' | tail -2
  echo "-- consolidate pass 2 --"
  python3 -m cairnstone.cli consolidate --db "$db" 2>&1 | grep -E '^ok:|^error:' | tail -2

  echo "-- fact table --"
  python3 - "$db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1]); c.row_factory = sqlite3.Row
for r in c.execute("SELECT f.id, f.text, f.status, f.superseded_by, f.duplicate_of,"
                   " c.captured_at FROM facts f JOIN captures c ON c.id=f.capture_id"
                   " ORDER BY f.id"):
    print("  %-3s %-45s %-11s sup_by=%-4s dup_of=%-4s %s"
          % (r["id"], r["text"][:45], r["status"], r["superseded_by"],
             r["duplicate_of"], r["captured_at"]))
for r in c.execute("SELECT kind, subject_id, payload_json FROM change_events"
                   " WHERE kind='fact.contradiction_flagged'"):
    print("  FLAG fact=%s %s" % (r["subject_id"], r["payload_json"][:120]))
PY

  echo "-- brief --"
  CAIRNSTONE_BASE_URL="$base" CAIRNSTONE_MODEL="$model" \
    python3 -m cairnstone.cli brief --db "$db" 'Where does Caroline live?' 2>&1 | tail -6
}

run_endpoint glm 'http://127.0.0.1:8460/v1' 'glm-5.3-flash'
run_endpoint spark "${CAIRN_SECOND_URL:-http://127.0.0.1:8889/v1}" "${CAIRN_SECOND_MODEL:-local-judge}"
