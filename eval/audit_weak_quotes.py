"""Throwaway phase-8 audit tool: re-run the unchanged extractor over the two eval
conversations into scratch DBs and record every fact the weak_quote guard rejects,
with its quote and subject, so the guard can be audited.

The phase-7 compile run did not persist its rejected proposals (only counts were
printed), so the audit regenerates them. The extractor and guards are untouched.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "eval")

from cairnstone import compile as C
from cairnstone import store
from harness import CairnBackend, RESULTS_DIR

OUT_PATH = RESULTS_DIR / "phase8-weak-quote-audit.json"
DB_DIR = RESULTS_DIR / "cairnstone-db"  # gitignored


def main() -> None:
    samples = json.loads((Path(__file__).parent / "datasets" / "locomo10.json")
                         .read_text())[:2]
    backend = CairnBackend(db_dir=DB_DIR)
    collected = []

    original_write_facts = C.write_facts

    def recording_write_facts(conn, page_id, version_id, capture_id, facts):
        accepted, rejected = original_write_facts(
            conn, page_id, version_id, capture_id, facts)
        for f in facts:
            if not C._weak_quote(f["text"], f["quote"], f["subject"]):
                continue
            # Only record if this proposal was actually rejected as weak_quote
            # (a subject_mismatch rejection fires first and takes precedence).
            if not any(r[0] == f["text"] and r[1].startswith("weak_quote")
                       for r in rejected):
                continue
            capture = store.get_capture(conn, capture_id)
            collected.append({
                "sample": sample_id,
                "capture_id": capture_id,
                "source_ref": capture["source_ref"],
                "fact_text": f["text"],
                "subject": f["subject"],
                "quote": f["quote"],
                "capture_excerpt": capture["content"][:400],
            })
        return accepted, rejected

    C.write_facts = recording_write_facts
    try:
        for sample in samples:
            sample_id = sample["sample_id"]
            db_path = DB_DIR / f"audit-{sample_id}.db"
            print(f"compiling {sample_id} ...", flush=True)
            backend._compile(sample, db_path)
            n = sum(1 for c in collected if c["sample"] == sample_id)
            print(f"  {sample_id}: {n} weak_quote rejections recorded", flush=True)
    finally:
        C.write_facts = original_write_facts

    OUT_PATH.write_text(json.dumps(collected, indent=2))
    print(f"wrote {len(collected)} weak_quote rejections to {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
