"""Throwaway phase-8 tool: re-run the compile with the relaxed weak_quote guard
(phase 8B) into scratch DBs, so the guard's effect on rejection counts is measured
on a real extraction run. The eval cache DBs are left untouched."""

import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "eval")

from cairn import store
from cairn.llm import LLMClient
from harness import CairnBackend, RESULTS_DIR

DB_DIR = RESULTS_DIR / "cairn-db"  # gitignored


def main() -> None:
    samples = json.loads((Path(__file__).parent / "datasets" / "locomo10.json")
                         .read_text())[:2]
    backend = CairnBackend(db_dir=DB_DIR)
    for sample in samples:
        db_path = DB_DIR / f"relaxed-{sample['sample_id']}.db"
        print(f"compiling {sample['sample_id']} with relaxed guard ...", flush=True)
        backend._compile(sample, db_path)
    # _compile prints its own rejection breakdown; recompute totals from the DBs.
    for sample in samples:
        conn = store.init_db(str(DB_DIR / f"relaxed-{sample['sample_id']}.db"))
        n_facts = conn.execute("SELECT COUNT(*) AS n FROM facts").fetchone()["n"]
        print(f"  {sample['sample_id']}: {n_facts} facts in relaxed corpus", flush=True)
        conn.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
