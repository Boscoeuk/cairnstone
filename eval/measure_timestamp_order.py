"""Measure how many capture timestamp pairs sort wrongly, before and after the
phase 15 N2 normalisation. Uses copies of the LoCoMo evaluation databases, so the
originals are untouched.

Tes measured 81/171 wrongly ordered pairs on conv-26 and 79/171 on conv-30 when
`captured_at` was compared as a raw string. This prints the same count computed
against the raw stored text and against the normalised instants.
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from cairnstone import store

HERE = os.path.dirname(os.path.abspath(__file__))
DBS = ["conv-26", "conv-30"]


def pairs(stamps):
    out = []
    for i in range(len(stamps)):
        for j in range(i + 1, len(stamps)):
            out.append((stamps[i], stamps[j]))
    return out


def main():
    for name in DBS:
        src = os.path.join(HERE, "results", "cairn-db", name + ".db")
        if not os.path.exists(src):
            print("%s: missing (%s)" % (name, src))
            continue
        with tempfile.TemporaryDirectory() as tmp:
            dst = os.path.join(tmp, name + ".db")
            shutil.copyfile(src, dst)
            conn = store.init_db(dst)  # runs the phase 15 migration
            rows = conn.execute(
                "SELECT captured_at, captured_at_text FROM captures ORDER BY id"
            ).fetchall()
            raw = [r["captured_at_text"] or r["captured_at"] for r in rows]
            normalised = [r["captured_at"] for r in rows]
            total = len(pairs(raw))
            wrong_raw = sum(1 for a, b in pairs(raw) if (a < b) != (_parse(a) < _parse(b)))
            wrong_norm = sum(1 for a, b in pairs(normalised)
                             if (a < b) != (_parse(a) < _parse(b)))
            unparsed = sum(1 for s in normalised if _parse(s) is None)
            print("%s: %d captures, %d pairs | wrongly ordered before=%d after=%d"
                  " | unparseable=%d" % (name, len(rows), total, wrong_raw,
                                         wrong_norm, unparsed))
            conn.close()


def _parse(text):
    dt = store.parse_timestamp(text)
    return dt.timestamp() if dt is not None else float("-inf")


if __name__ == "__main__":
    main()
