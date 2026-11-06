"""Phase 14 deterministic consolidation check (no model, no network).

Rebuilds the deterministic scenarios from reports/tes-consolidation-1.md
(B1 for D1, B3/C1 for D3, run_d for D4) against a throwaway SQLite database,
runs consolidation once and twice, and prints the fact table after each pass.
A second pass that changes nothing proves the nightly pass is idempotent.

Usage: python3 eval/consolidation_repro.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cairnstone import store
from cairnstone.compile import consolidate

CAPTURE_TEXT = "Caroline: (fact text cited in full)"


def new_brain(conn):
    ws = store.create_workspace(conn, "w")
    return store.create_brain(conn, ws, "b", "b")


def add_capture(conn, brain_id, text, captured_at):
    return store.add_capture(conn, brain_id, "conversation", text, "repro",
                             captured_at=captured_at)


def add_fact(conn, brain_id, text, capture_id):
    page = conn.execute(
        "SELECT id FROM pages WHERE brain_id = ? AND path = 'people/caroline'",
        (brain_id,)).fetchone()
    if page is None:
        page_id = store.create_page(conn, brain_id, "people/caroline",
                                    "people", "Caroline", body_md="")
    else:
        page_id = page["id"]
    version_id = conn.execute(
        "SELECT current_version_id FROM pages WHERE id = ?",
        (page_id,)).fetchone()[0]
    return store.add_fact(conn, page_id, version_id, text, capture_id,
                          0, len(CAPTURE_TEXT))


def fact_table(conn):
    rows = conn.execute(
        "SELECT f.id, f.text, f.status, f.superseded_by, f.duplicate_of,"
        " f.capture_id FROM facts f ORDER BY f.id").fetchall()
    lines = ["  id  text                                          status"
             "       sup_by  dup_of  cap"]
    for r in rows:
        lines.append("  %-3d %-45s %-10s %-7s %-7s %d"
                     % (r["id"], r["text"], r["status"],
                        r["superseded_by"] or "-", r["duplicate_of"] or "-",
                        r["capture_id"]))
    return "\n".join(lines)


def snapshot(conn):
    return conn.execute(
        "SELECT id, status, superseded_by, duplicate_of FROM facts"
        " ORDER BY id").fetchall(), conn.execute(
            "SELECT id, kind, subject_id FROM change_events ORDER BY id"
        ).fetchall()


def run_scenario(title, build):
    print("\n=== %s ===" % title)
    with tempfile.TemporaryDirectory() as tmp:
        conn = store.init_db(os.path.join(tmp, "repro.db"))
        brain = new_brain(conn)
        build(conn, brain)
        one = consolidate(conn, brain)
        print("after pass 1: %s" % one)
        print(fact_table(conn))
        snap1 = snapshot(conn)
        two = consolidate(conn, brain)
        print("after pass 2: %s" % two)
        assert snapshot(conn) == snap1, "second pass mutated the brain!"
        print("second pass changed nothing: OK")
        conn.close()


def scenario_b1(conn, brain):
    """D1: duplicate of 'single' must not hide the canonical fact from the
    'married' contradiction."""
    c1 = add_capture(conn, brain, CAPTURE_TEXT, "2023-05-01T00:00:00+00:00")
    c2 = add_capture(conn, brain, CAPTURE_TEXT, "2023-05-15T00:00:00+00:00")
    c3 = add_capture(conn, brain, CAPTURE_TEXT, "2023-06-01T00:00:00+00:00")
    add_fact(conn, brain, "Caroline is single", c1)
    add_fact(conn, brain, "Caroline is single", c2)
    add_fact(conn, brain, "Caroline is married", c3)


def scenario_b3(conn, brain):
    """D3: the backfilled May capture (higher capture id) must lose to the
    June capture."""
    c1 = add_capture(conn, brain, CAPTURE_TEXT, "2023-06-01T00:00:00+00:00")
    c2 = add_capture(conn, brain, CAPTURE_TEXT, "2023-05-01T00:00:00+00:00")
    add_fact(conn, brain, "Caroline has been a nurse for 5 years", c1)
    add_fact(conn, brain, "Caroline has been a nurse for 4 years", c2)


def scenario_run_d(conn, brain):
    """D4: fact ids out of capture order; the swap path must not supersede a
    fact by its own agreeing claim."""
    c1 = add_capture(conn, brain, CAPTURE_TEXT, "2023-05-01T00:00:00+00:00")
    c2 = add_capture(conn, brain, CAPTURE_TEXT, "2023-06-01T00:00:00+00:00")
    add_fact(conn, brain, "Caroline is married", c2)          # f1, June
    add_fact(conn, brain, "Caroline is single", c1)           # f2, May
    add_fact(conn, brain, "Caroline is married and happy", c2)  # f3, June


def main():
    run_scenario("Scenario B1 (D1: duplicate hides canonical fact)",
                 scenario_b1)
    run_scenario("Scenario B3 (D3: out-of-order captures)", scenario_b3)
    run_scenario("Scenario run_d (D4: swap records wrong value)", scenario_run_d)
    print("\nAll scenarios: one pass converged, second pass was a no-op.")


if __name__ == "__main__":
    main()
