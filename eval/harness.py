"""Phase 0 evaluation harness: full-context baseline vs naive RAG over LoCoMo.

the maintainer owns this file. It was first drafted by an coding-agent worker and then corrected on
independent review for four defects: a judge that substring-matched "correct" inside
"INCORRECT", thinking left on (which empties `content` on TensorFold), no cap on the
number of questions (a 3-sample run was ~600 questions), and no engine telemetry.

Usage:
    python -m eval.harness --baseline --limit 1 --max-questions 12
    python -m eval.harness --backend naive_rag --limit 2 --max-questions 40

Numbers produced here are LOCAL-JUDGED (local-judge), not GPT-judged. They are
comparable in shape to published LoCoMo figures, not identical in judge.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import time
from pathlib import Path

import requests

from cairn import compile as cairn_compile
from cairn import retrieve
from cairn import store as cairn_store
from cairn.llm import LLMClient

DATASET = Path(__file__).parent / "datasets" / "locomo10.json"
RESULTS_DIR = Path(__file__).parent / "results"

ANSWER_URL = "http://127.0.0.1:8460/v1/chat/completions"
JUDGE_URL = "http://127.0.0.1:8889/v1/chat/completions"
EMBED_URL = "http://127.0.0.1:1234/v1/embeddings"
ANSWER_MODEL = "glm-5.3-flash"
JUDGE_MODEL = "local-judge"
EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"
TIMEOUT = 180
HEADERS = {"Authorization": "Bearer local", "Content-Type": "application/json"}

# Category numbers are NOT documented in the LoCoMo README. This mapping is inferred from
# the question content and the per-category counts (1:282, 2:321, 3:96, 4:841, 5:446).
CATEGORY_NAMES = {
    1: "multi-hop",
    2: "temporal",
    3: "commonsense",
    4: "single-hop",
    5: "adversarial",
}


# ---------------------------------------------------------------- http helper
def _post(url: str, payload: dict) -> dict:
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.post(url, headers=HEADERS, json=payload, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"POST {url} failed after 3 attempts: {last_err}")


def _chat(url: str, model: str, messages: list[dict], max_tokens: int = 256,
          think: bool = False) -> dict:
    """One completion. Returns text, usage and TensorFold engine telemetry.

    TensorFold ignores a top-level `enable_thinking`; the supported switch is
    chat_template_kwargs.enable_thinking. With thinking on, the answer can land in
    reasoning_content with `content` empty, so both are inspected.
    """
    t0 = time.perf_counter()
    data = _post(url, {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "chat_template_kwargs": {"enable_thinking": think},
    })
    wall = time.perf_counter() - t0
    msg = data["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    flags = []
    if not content and reasoning:
        content = reasoning
        flags.append("content_empty_used_reasoning")
    tf = data.get("tensorfold", {}) or {}
    usage = data.get("usage", {}) or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    return {
        "text": content,
        "usage": usage,
        "flags": flags,
        "engine": {
            "engine": tf.get("engine"),
            "tokens_per_second": tf.get("tokens_per_second"),
            "prefill_seconds": tf.get("prefill_seconds"),
            "time_to_first_token": tf.get("time_to_first_token"),
            "cached_tokens": cached,
            "wall_seconds": round(wall, 3),
        },
    }


# ------------------------------------------------------------------- dataset
def load_locomo(path: Path = DATASET) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _session_sort_key(key: str) -> tuple:
    m = re.search(r"(\d+)$", key)
    return (int(m.group(1)) if m else 0, key)


def conversation_text(sample: dict) -> str:
    conv = sample["conversation"]
    lines: list[str] = []
    for key in sorted(conv, key=_session_sort_key):
        if key.endswith("_date_time"):
            lines.append(f"[{key.replace('_date_time', '')} date: {conv[key]}]")
            continue
        session = conv[key]
        if not isinstance(session, list):
            continue
        for turn in session:
            if "speaker" in turn and "text" in turn:
                lines.append(f"{turn['speaker']}: {turn['text']}")
            elif "text" in turn:
                lines.append(turn["text"])
    return "\n".join(lines)


# ------------------------------------------------------------------ backends
class Backend:
    name = "base"

    def ingest(self, sample: dict) -> None: ...
    def ask(self, question: str) -> dict: ...


class FullContextBackend(Backend):
    """Stuff the whole conversation into the prompt. The reference baseline."""

    name = "full_context"

    def ingest(self, sample: dict) -> None:
        self.transcript = conversation_text(sample)

    def ask(self, question: str) -> dict:
        # TensorFold reuses a cached prompt only at a message boundary: the stable
        # context must be its own leading message, with the volatile question after it.
        # Measured: 26s TTFT cold vs 0.12s cached across different questions. Putting
        # the transcript and the question in one user message defeats reuse entirely.
        stable = (
            "You are answering questions about a conversation. Use only the conversation "
            "below. Answer with a short phrase, not a sentence.\n\n"
            f"### Conversation\n{self.transcript}"
        )
        out = _chat(ANSWER_URL, ANSWER_MODEL, [
            {"role": "system", "content": stable},
            {"role": "user", "content": f"### Question\n{question}\n\nAnswer:"},
        ], 128)
        return self._result(out, stable, ["full_conversation"])

    def _result(self, out: dict, prompt: str, sources: list[str]) -> dict:
        pt = out["usage"].get("prompt_tokens")
        return {
            "answer": out["text"],
            "context_tokens": pt if pt is not None else len(prompt) // 4,
            "tokens_estimated": pt is None,
            "latency_s": out["engine"]["wall_seconds"],
            "sources": sources,
            "flags": out["flags"],
            "engine": out["engine"],
        }


class NaiveRagBackend(FullContextBackend):
    """Chunk, embed locally, retrieve top-k, answer from those chunks."""

    name = "naive_rag"

    def __init__(self, chunk_chars: int = 800, top_k: int = 5):
        self.chunk_chars = chunk_chars
        self.top_k = top_k

    def ingest(self, sample: dict) -> None:
        self.chunks: list[dict] = []
        conv = sample["conversation"]
        for key in sorted(conv, key=_session_sort_key):
            session = conv[key]
            if not isinstance(session, list):
                continue
            buf: list[str] = []
            for turn in session:
                line = (f"{turn['speaker']}: {turn['text']}"
                        if "speaker" in turn and "text" in turn else turn.get("text", ""))
                if not line:
                    continue
                buf.append(line)
                if sum(len(b) for b in buf) >= self.chunk_chars:
                    self.chunks.append({"session": key, "text": "\n".join(buf)})
                    buf = []
            if buf:
                self.chunks.append({"session": key, "text": "\n".join(buf)})
        if not self.chunks:
            self.chunks = [{"session": "none", "text": "(empty)"}]
        resp = _post(EMBED_URL, {"model": EMBED_MODEL,
                                 "input": [c["text"] for c in self.chunks]})
        self.embeddings = [d["embedding"] for d in resp["data"]]

    def _retrieve(self, question: str) -> list[dict]:
        resp = _post(EMBED_URL, {"model": EMBED_MODEL, "input": [question]})
        q = resp["data"][0]["embedding"]

        def dot(e: list[float]) -> float:
            return sum(a * b for a, b in zip(q, e))

        ranked = sorted(zip(self.embeddings, self.chunks), key=lambda p: dot(p[0]),
                        reverse=True)
        return [c for _, c in ranked[: self.top_k]]

    def ask(self, question: str) -> dict:
        chunks = self._retrieve(question)
        context = "\n\n".join(f"[{c['session']}]\n{c['text']}" for c in chunks)
        stable = (
            "Answer the question using only the context below. Answer with a short "
            "phrase, not a sentence.\n\n"
            f"### Context\n{context}"
        )
        out = _chat(ANSWER_URL, ANSWER_MODEL, [
            {"role": "system", "content": stable},
            {"role": "user", "content": f"### Question\n{question}\n\nAnswer:"},
        ], 128)
        return self._result(out, stable, [c["session"] for c in chunks])


BACKENDS = {b.name: b for b in (FullContextBackend(), NaiveRagBackend())}


class CairnBackend(FullContextBackend):
    """Compile each conversation into a per-sample Cairn brain, answer from the
    prefix-stable brief (P9): stable compiled content in its own leading system
    message, the question as the user message — mandatory for TensorFold prefix reuse.

    The compiled SQLite DB is cached per sample under eval/results/cairn-db/<sample>.db;
    compiling (419 LLM extraction calls for sample 0) is the expensive part and happens
    once. `--recompile` forces a rebuild.
    """

    name = "cairn"

    def __init__(self, db_dir: Path = RESULTS_DIR / "cairn-db", recompile: bool = False,
                 brief_budget: int = 4000):
        self.db_dir = db_dir
        self.recompile = recompile
        self.brief_budget = brief_budget

    # ------------------------------------------------------------- compilation
    def _captures(self, sample: dict) -> list[tuple[str, str, str]]:
        """(text, captured_at, source_ref) for every conversation turn."""
        conv = sample["conversation"]
        out: list[tuple[str, str, str]] = []
        for key in sorted(conv, key=_session_sort_key):
            session = conv[key]
            if not isinstance(session, list):
                continue
            stamp = conv.get(f"{key}_date_time", "unknown")
            for i, turn in enumerate(session):
                text = (f"{turn['speaker']}: {turn['text']}"
                        if "speaker" in turn and "text" in turn else turn.get("text", ""))
                if text:
                    out.append((text, stamp, f"locomo:{sample['sample_id']}:{key}:{i}"))
        return out

    def _compile(self, sample: dict, db_path: Path) -> None:
        """Compile into a temp DB first, then atomically rename, so a crashed run
        never leaves a half-compiled brain in the cache."""
        self.db_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = db_path.with_suffix(".tmp")
        if tmp_path.exists():
            tmp_path.unlink()
        conn = cairn_store.init_db(str(tmp_path))
        ws = cairn_store.create_workspace(conn, "eval")
        brain = cairn_store.create_brain(conn, ws, sample["sample_id"], sample["sample_id"])
        captures = self._captures(sample)
        capture_ids = [
            cairn_store.add_capture(conn, brain, "conversation", text, ref,
                                    captured_at=stamp)
            for text, stamp, ref in captures
        ]
        client = LLMClient()
        summary = cairn_compile.compile_all(conn, brain, capture_ids, client)
        n_pages = conn.execute(
            "SELECT COUNT(*) AS n FROM pages WHERE brain_id = ?", (brain,)).fetchone()["n"]
        conn.close()
        tmp_path.replace(db_path)
        print(f"  compiled {sample['sample_id']}: {len(captures)} captures, "
              f"{summary['facts_accepted']} facts, {n_pages} pages, "
              f"{len(summary['failed_captures'])} failed captures", flush=True)

    def ingest(self, sample: dict) -> None:
        db_path = self.db_dir / f"{sample['sample_id']}.db"
        if not db_path.exists() or self.recompile:
            self._compile(sample, db_path)
        self.conn = cairn_store.init_db(str(db_path))
        self.brain_id = self.conn.execute(
            "SELECT id FROM brains ORDER BY id").fetchone()["id"]

    # ------------------------------------------------------------------ asking
    def ask(self, question: str) -> dict:
        stable, _ = retrieve.build_brief(self.conn, self.brain_id, question,
                                         budget_tokens=self.brief_budget)
        out = _chat(ANSWER_URL, ANSWER_MODEL, [
            {"role": "system", "content": stable},
            {"role": "user", "content": (
                f"### Question\n{question}\n\n"
                "Reply with a single short answer only — a date, name, number, place or "
                "short phrase. Do not restate the supporting fact. Do not use markdown "
                "or bold. If the records do not answer it, reply exactly: Not recorded.\n\n"
                "Answer:")},
        ], 128)

        # Hybrid retrieval for the evidence appendix (does not touch the stable prefix).
        hits = retrieve.search(self.conn, self.brain_id, question, k=8)
        fact_ids = [h["id"] for h in hits if h["kind"] == "fact"]
        evidence = retrieve.render_citations(self.conn, fact_ids)

        facts = retrieve.eligible_facts(self.conn, self.brain_id,
                                        include_superseded=retrieve.is_history_question(question))
        facts_in_brief = [f for f in facts if f["text"] in stable]
        citations_used = stable.count("[capture ")

        result = self._result(out, stable, [e["source_ref"].rsplit(":", 2)[0]
                                            for e in evidence])
        result.update({
            "brief_tokens": len(stable) // 4,
            "facts_used": len(facts_in_brief),
            "citations_used": citations_used,
            # A superseded fact in the brief is a defect per P10; flag it.
            "superseded_used": any(f["status"] == "superseded" for f in facts_in_brief),
        })
        if result["superseded_used"]:
            result["flags"] = result["flags"] + ["superseded_fact_in_brief"]
        return result


BACKENDS["cairn"] = CairnBackend()


# --------------------------------------------------------------------- judge
JUDGE_PROMPT = """You grade a question-answering system. Decide whether the PREDICTED
answer conveys the same fact as the GOLD answer. Accept paraphrases and different formats
that mean the same thing. Ignore extra detail that does not contradict the gold answer.

Question: {question}
Gold answer: {gold}
Predicted answer: {predicted}

Reply with exactly one word: CORRECT or INCORRECT."""


def judge(question: str, gold: str, predicted: str, model: str = JUDGE_MODEL) -> tuple[bool, bool]:
    """Returns (correct, ambiguous).

    Parsed strictly: 'INCORRECT' is tested before 'CORRECT' because it contains it.
    An empty prediction is incorrect without asking the model.
    """
    if not predicted.strip():
        return False, False
    out = _chat(JUDGE_URL, model, [{"role": "user", "content": JUDGE_PROMPT.format(
        question=question, gold=gold, predicted=predicted)}], max_tokens=12)
    text = out["text"].strip().upper()
    if text.startswith("INCORRECT"):
        return False, False
    if text.startswith("CORRECT"):
        return True, False
    if re.search(r"\bINCORRECT\b", text):
        return False, False
    if re.search(r"\bCORRECT\b", text):
        return True, False
    return False, True


# -------------------------------------------------------------------- runner
def run_backend(backend: Backend, samples: list[dict], judge_model: str,
                max_questions: int | None) -> list[dict]:
    rows = []
    asked = 0
    for sample in samples:
        backend.ingest(sample)
        for qa in sample["qa"]:
            if max_questions is not None and asked >= max_questions:
                break
            asked += 1
            result = backend.ask(qa["question"])
            correct, ambiguous = judge(qa["question"], str(qa["answer"]),
                                       result["answer"], judge_model)
            row = {
                "sample_id": sample["sample_id"],
                "question": qa["question"],
                "gold": str(qa["answer"]),
                "predicted": result["answer"],
                "correct": correct,
                "judge_ambiguous": ambiguous,
                "category": qa["category"],
                "category_name": CATEGORY_NAMES.get(qa["category"], str(qa["category"])),
                "context_tokens": result["context_tokens"],
                "tokens_estimated": result["tokens_estimated"],
                "latency_s": result["latency_s"],
                "sources": result["sources"],
                "flags": result["flags"],
                "engine": result["engine"],
            }
            # Backend-specific metrics (cairn: brief_tokens, facts_used,
            # citations_used, superseded_used) ride along without affecting the
            # other backends' rows.
            row.update(result)
            rows.append(row)
        if max_questions is not None and asked >= max_questions:
            break
    return rows


def aggregate(rows: list[dict]) -> dict:
    by_cat: dict[str, list[bool]] = {}
    for r in rows:
        by_cat.setdefault(r["category_name"], []).append(r["correct"])
    engine = [r["engine"] for r in rows if r["engine"]]
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None  # noqa: E731
    return {
        "accuracy_by_category": {
            cat: {"n": len(v), "accuracy": round(sum(v) / len(v), 3)}
            for cat, v in sorted(by_cat.items())
        },
        "n_questions": len(rows),
        "accuracy_overall": round(sum(r["correct"] for r in rows) / max(len(rows), 1), 3),
        "judge_ambiguous_count": sum(r["judge_ambiguous"] for r in rows),
        "mean_context_tokens": mean([r["context_tokens"] for r in rows]),
        "mean_latency_s": mean([r["latency_s"] for r in rows]),
        "mean_engine_tokens_per_second": mean(
            [e["tokens_per_second"] for e in engine if e.get("tokens_per_second")]),
        "mean_engine_prefill_seconds": mean(
            [e["prefill_seconds"] for e in engine if e.get("prefill_seconds") is not None]),
        "prompt_cache_hit_rate": mean(
            [1.0 if e.get("cached_tokens") else 0.0 for e in engine]),
    }


def save_results(backend_name: str, rows: list[dict], judge_model: str,
                 answer_model: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    path = RESULTS_DIR / f"{date}-{backend_name}.json"
    doc = {
        "dataset": DATASET.name,
        "dataset_license": "LoCoMo, Snap Research, ACL 2024 (research use)",
        "backend": backend_name,
        "answer_model": answer_model,
        "judge_model": judge_model,
        "judge_note": "local-judged; not GPT-judged, so not directly comparable to "
                      "published LoCoMo figures",
        "engine": "TensorFold (tensorfold-native)",
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "aggregate": aggregate(rows),
        "rows": rows,
    }
    path.write_text(json.dumps(doc, indent=2))
    return path


def comparison_table(results: dict[str, dict]) -> str:
    lines = ["| backend | accuracy | questions | mean context tokens | mean latency (s) | "
             "cache hit |", "|---|---|---|---|---|---|"]
    for name, doc in results.items():
        a = doc["aggregate"]
        lines.append(
            f"| {name} | {a['accuracy_overall']:.1%} | {a['n_questions']} | "
            f"{a['mean_context_tokens']} | {a['mean_latency_s']} | "
            f"{a['prompt_cache_hit_rate']} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 0 memory-quality harness")
    ap.add_argument("--backend", choices=sorted(BACKENDS))
    ap.add_argument("--baseline", action="store_true", help="run both backends + table")
    ap.add_argument("--limit", type=int, default=None, help="max samples (conversations)")
    ap.add_argument("--max-questions", type=int, default=25,
                    help="max questions per run (default 25; use 0 for all)")
    ap.add_argument("--judge-model", default=JUDGE_MODEL)
    ap.add_argument("--recompile", action="store_true",
                    help="cairn backend: rebuild the per-sample compiled DBs")
    ap.add_argument("--brief-budget", type=int, default=4000,
                    help="cairn backend: brief token budget. Lower it to force retrieval "
                         "to select facts instead of fitting the whole brain")
    args = ap.parse_args()

    if not args.baseline and not args.backend:
        ap.error("specify --backend or --baseline")

    if args.recompile or args.brief_budget != 4000:
        BACKENDS["cairn"] = CairnBackend(recompile=args.recompile,
                                         brief_budget=args.brief_budget)

    samples = load_locomo()
    if args.limit:
        samples = samples[: args.limit]
    max_q = None if args.max_questions == 0 else args.max_questions

    names = sorted(BACKENDS) if args.baseline else [args.backend]
    saved: dict[str, dict] = {}
    for name in names:
        print(f"=== {name}: {len(samples)} sample(s), "
              f"{'all' if max_q is None else max_q} question(s) ===", flush=True)
        t0 = time.perf_counter()
        rows = run_backend(BACKENDS[name], samples, args.judge_model, max_q)
        label = (f"cairn-b{args.brief_budget}"
                 if name == "cairn" and args.brief_budget != 4000 else name)
        path = save_results(label, rows, args.judge_model, ANSWER_MODEL)
        saved[name] = json.loads(path.read_text())
        print(f"wrote {path} in {time.perf_counter() - t0:.1f}s", flush=True)

    if args.baseline:
        print()
        print(comparison_table(saved))


if __name__ == "__main__":
    main()
