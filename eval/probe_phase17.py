"""Phase 17 collateral probe: run the consolidation pass twice over SQLite
backup copies of the 27 real databases, reporting superseded / flagged /
duplicate-linked counts (the probe Tes ran at fe71ff1, re-run per
docs/phase17-brief.md).

Usage: .venv/bin/python eval/probe_phase17.py [--dump-pairs]
"""

import json
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cairnstone import compile as comp
from cairnstone import store

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The 27 real databases: dogfood session, the conv-26/conv-30 result DBs
# (both cairn-db and cairnstone-db variants), and the 22 LongMemEval DBs.
def corpus():
    dbs = [os.path.join(REPO, "eval", "dogfood", "session.db")]
    for sub in ("cairn-db", "cairnstone-db"):
        for name in ("conv-26.db", "conv-30.db"):
            dbs.append(os.path.join(REPO, "eval", "results", sub, name))
    lme = os.path.join(REPO, "eval", "results", "lme-db")
    dbs.extend(sorted(os.path.join(lme, n) for n in os.listdir(lme)
                      if n.endswith(".db")))
    return dbs


def probe(dump_pairs=False):
    total = {"superseded": 0, "flagged": 0, "duplicates_linked": 0}
    per_db = []
    with tempfile.TemporaryDirectory() as tmp:
        for src in corpus():
            dst = os.path.join(tmp, os.path.basename(src))
            # SQLite backup API copy, never touching the original file.
            src_conn = sqlite3.connect(src)
            dst_conn = sqlite3.connect(dst)
            src_conn.backup(dst_conn)
            src_conn.close()
            conn = store.init_db(dst)  # migrates the backup copy only
            brain = conn.execute(
                "SELECT id FROM brains").fetchone()[0]
            # Two passes, as in Tes's probe.
            r1 = comp.consolidate(conn, brain)
            r2 = comp.consolidate(conn, brain)
            for key in total:
                total[key] += r1[key] + r2[key]
            per_db.append((os.path.basename(src), r1, r2))
            if dump_pairs and (r1["superseded"] or r1["flagged"]):
                print("== %s: pass1 %s pass2 %s" % (
                    os.path.basename(src), json.dumps(r1), json.dumps(r2)))
                if dump_pairs:
                    _dump_mutations(conn, brain)
            conn.close()
            dst_conn.close()
    return total, per_db


def _dump_mutations(conn, brain):
    for row in conn.execute(
            "SELECT subject_id, payload_json FROM change_events"
            " WHERE kind = 'fact.contradiction_flagged'"):
        payload = json.loads(row["payload_json"])
        texts = []
        for fid in (row["subject_id"], payload["contradicts"]):
            t = conn.execute("SELECT text FROM facts WHERE id = ?",
                             (fid,)).fetchone()
            texts.append(t[0] if t else "?")
        print("  FLAG %s\n    a: %s\n    b: %s" % (
            payload["slot"][:90], texts[0][:110], texts[1][:110]))
    for row in conn.execute(
            "SELECT id, text, superseded_by FROM facts"
            " WHERE status = 'superseded'"):
        old = conn.execute("SELECT text FROM facts WHERE id = ?",
                           (row["superseded_by"],)).fetchone()
        print("  SUPERSEDED %s\n    by: %s" % (
            row["text"][:110], (old[0] if old else "?")[:110]))


if __name__ == "__main__":
    total, per_db = probe(dump_pairs="--dump-pairs" in sys.argv)
    print("TOTAL superseded=%d flagged=%d duplicates_linked=%d" % (
        total["superseded"], total["flagged"], total["duplicates_linked"]))
    print("databases: %d" % len(per_db))
