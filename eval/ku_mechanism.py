"""Recompute the phase 18 B2 mechanism metric from the frozen brains.

The run's own metric recorded `stale_in_brief_a/b` as substring checks against
`arm["brief"]`, but `lme_eval.cairnstone_backend` does not return the brief
text, so every check ran against an empty string and reported 0. This script
recomputes the metric exactly: it rebuilds both briefs from the stored brains
with retrieve.build_brief (deterministic, no model calls) and asks whether the
retired stale fact was actually SELECTED into arm (a)'s brief or arm (b)'s.

Brains are opened from sqlite backup copies, so the originals and their
provenance sidecars are never written.
"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, ".")

from cairnstone import store, retrieve
from eval.longmemeval import lme_eval as lme

RESULT = Path("eval/results/ku-paired-74q.json")
KU_DB = Path("eval/results/ku-db")
DATASET = Path("eval/datasets/longmemeval_s_cleaned.json")


def open_copy(src: Path, tmp: Path):
    dst = tmp / src.name
    s = sqlite3.connect(str(src))
    d = sqlite3.connect(str(dst))
    s.backup(d)
    s.close()
    d.close()
    conn = store.init_db(str(dst))
    brain = conn.execute("SELECT id FROM brains ORDER BY id LIMIT 1").fetchone()["id"]
    return conn, brain


def main():
    rows = json.loads(RESULT.read_text())["rows"]
    questions = {q["question_id"]: q for q in json.loads(DATASET.read_text())}
    totals = {"stale": 0, "in_a": 0, "in_b": 0, "q_a": 0, "q_b": 0, "missing": 0}
    detail = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for r in rows:
            qid = r["question_id"]
            pristine = KU_DB / ("%s.db" % qid)
            cons = KU_DB / ("%s.consolidated.db" % qid)
            if not pristine.exists() or not cons.exists():
                totals["missing"] += 1
                continue
            question = questions.get(qid)
            if question is None:
                totals["missing"] += 1
                continue
            ca, ba = open_copy(pristine, tmp)
            cb, bb = open_copy(cons, tmp)
            try:
                _sa, _va, sel_a = retrieve.build_brief(
                    ca, ba, question["question"], budget_tokens=600)
                _sb, _vb, sel_b = retrieve.build_brief(
                    cb, bb, question["question"], budget_tokens=600)
            except Exception as exc:  # noqa: BLE001 - report, do not abort
                print("%s: brief build failed: %s" % (qid, exc))
                ca.close(); cb.close()
                totals["missing"] += 1
                continue
            ids_a = {f["id"] for f in sel_a}
            ids_b = {f["id"] for f in sel_b}
            stale = cb.execute(
                "SELECT id, text FROM facts WHERE status = 'superseded'").fetchall()
            n = len(stale)
            in_a = sum(1 for f in stale if f["id"] in ids_a)
            in_b = sum(1 for f in stale if f["id"] in ids_b)
            totals["stale"] += n
            totals["in_a"] += in_a
            totals["in_b"] += in_b
            if in_a:
                totals["q_a"] += 1
            if in_b:
                totals["q_b"] += 1
            if n:
                detail.append({"question_id": qid, "stale": n, "in_a": in_a,
                               "in_b": in_b})
            ca.close(); cb.close()
    out = {"totals": totals, "per_question": detail}
    Path("eval/results/ku-paired-74q-mechanism.json").write_text(
        json.dumps(out, indent=1) + "\n")
    print(json.dumps(totals, indent=1))
    for d in detail:
        print("  %s stale=%d in_a=%d in_b=%d" % (d["question_id"], d["stale"],
                                                 d["in_a"], d["in_b"]))


if __name__ == "__main__":
    main()
