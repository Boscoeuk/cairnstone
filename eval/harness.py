"""Phase 0 evaluation harness: full-context baseline vs naive RAG over LoCoMo.

Usage:
    python -m eval.harness --backend full_context --limit 10
    python -m eval.harness --backend naive_rag --limit 10
    python -m eval.harness --baseline --limit 3
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import requests

DATASET = Path(__file__).parent / "datasets" / "locomo10.json"
RESULTS_DIR = Path(__file__).parent / "results"

ANSWER_URL = "http://127.0.0.1:8460/v1/chat/completions"
JUDGE_URL = "http://127.0.0.1:8889/v1/chat/completions"
EMBED_URL = "http://127.0.0.1:1234/v1/embeddings"
ANSWER_MODEL = "glm-5.3-flash"
JUDGE_MODEL = "local-judge"
EMBED_MODEL = "text-embedding-nomic-embed-text-v1.5"
TIMEOUT = 120
HEADERS = {"Authorization": "Bearer local", "Content-Type": "application/json"}

CATEGORY_NAMES = {
    1: "single-hop",
    2: "temporal",
    3: "multi-hop",
    4: "open-domain",
    5: "adversarial",
}


# ---------------------------------------------------------------- http helper
def _post(url: str, payload: dict) -> dict:
    last_err: Exception | None = None
    for attempt in range(3):  # initial try + 2 retries
        try:
            r = requests.post(url, headers=HEADERS, json=payload, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"POST {url} failed after 3 attempts: {last_err}")


def _chat(url: str, model: str, messages: list[dict], max_tokens: int = 256) -> tuple[str, dict]:
    data = _post(url, {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
    })
    text = data["choices"][0]["message"]["content"]
    return text, data.get("usage", {})


# ------------------------------------------------------------------- dataset
def load_locomo(path: Path = DATASET) -> list[dict]:
    """Load LoCoMo samples: {sample_id, conversation, qa:[{question,answer,evidence,category}]}."""
    with open(path) as f:
        return json.load(f)


def conversation_text(sample: dict) -> str:
    """Flatten a sample's conversation into one transcript string."""
    conv = sample["conversation"]
    lines: list[str] = []
    for key in sorted(conv):
        if key.endswith("_date_time"):
            lines.append(f"[{key.replace('_date_time', '')} date: {conv[key]}]")
            continue
        session = conv[key]
        if not isinstance(session, list):
            continue
        for turn in session:
            if "speaker" in turn and "text" in turn:
                lines.append(f"{turn['speaker']}: {turn['text']}")
            elif "text" in turn:  # image/blind turns carry text but no speaker
                lines.append(turn["text"])
    return "\n".join(lines)


# ------------------------------------------------------------------ backends
class Backend:
    name = "base"

    def ingest(self, sample: dict) -> None: ...
    def ask(self, question: str) -> dict: ...


class FullContextBackend(Backend):
    """Stuff the whole conversation into the prompt."""

    name = "full_context"

    def ingest(self, sample: dict) -> None:
        self.transcript = conversation_text(sample)

    def ask(self, question: str) -> dict:
        prompt = (
            "You are answering questions about a conversation. Use only the "
            "conversation below. Answer concisely.\n\n"
            f"### Conversation\n{self.transcript}\n\n"
            f"### Question\n{question}\n\nAnswer:"
        )
        t0 = time.perf_counter()
        answer, usage = _chat(ANSWER_URL, ANSWER_MODEL, [
            {"role": "user", "content": prompt},
        ])
        latency = time.perf_counter() - t0
        if usage.get("prompt_tokens") is not None:
            ctx_tokens = usage["prompt_tokens"]
            estimated = False
        else:
            ctx_tokens = len(prompt) // 4
            estimated = True
        return {
            "answer": answer.strip(),
            "context_tokens": ctx_tokens,
            "tokens_estimated": estimated,
            "latency_s": latency,
            "sources": ["full_conversation"],
        }


class NaiveRagBackend(Backend):
    """Chunk the conversation, embed locally, retrieve top-k, answer from chunks."""

    name = "naive_rag"

    def __init__(self, chunk_chars: int = 800, top_k: int = 5):
        self.chunk_chars = chunk_chars
        self.top_k = top_k

    def ingest(self, sample: dict) -> None:
        self.chunks: list[dict] = []
        conv = sample["conversation"]
        for key in sorted(conv):
            if key.endswith("_date_time"):
                continue
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
        resp = _post(EMBED_URL, {
            "model": EMBED_MODEL,
            "input": [c["text"] for c in self.chunks],
        })
        self.embeddings = [d["embedding"] for d in resp["data"]]

    def _retrieve(self, question: str) -> list[dict]:
        resp = _post(EMBED_URL, {"model": EMBED_MODEL, "input": [question]})
        q = resp["data"][0]["embedding"]
        def dot(e: list[float]) -> float:
            return sum(a * b for a, b in zip(q, e))
        scored = sorted(zip(self.embeddings, self.chunks), key=lambda p: dot(p[0]), reverse=True)
        return [c for _, c in scored[: self.top_k]]

    def ask(self, question: str) -> dict:
        chunks = self._retrieve(question)
        context = "\n\n".join(f"[{c['session']}]\n{c['text']}" for c in chunks)
        prompt = (
            "Answer the question using only the context below. Answer concisely.\n\n"
            f"### Context\n{context}\n\n### Question\n{question}\n\nAnswer:"
        )
        t0 = time.perf_counter()
        answer, usage = _chat(ANSWER_URL, ANSWER_MODEL, [
            {"role": "user", "content": prompt},
        ])
        latency = time.perf_counter() - t0
        if usage.get("prompt_tokens") is not None:
            ctx_tokens = usage["prompt_tokens"]
            estimated = False
        else:
            ctx_tokens = len(prompt) // 4
            estimated = True
        return {
            "answer": answer.strip(),
            "context_tokens": ctx_tokens,
            "tokens_estimated": estimated,
            "latency_s": latency,
            "sources": [c["session"] for c in chunks],
        }


BACKENDS = {b.name: b for b in (FullContextBackend(), NaiveRagBackend())}


# --------------------------------------------------------------------- judge
JUDGE_PROMPT = """You are grading a QA system. Decide whether the PREDICTED answer is
correct given the GOLD answer. Accept paraphrases and different formats that convey the
same fact. Answer with exactly one word: CORRECT or INCORRECT.

Question: {question}
Gold answer: {gold}
Predicted answer: {predicted}

Verdict (CORRECT or INCORRECT):"""


def judge(question: str, gold: str, predicted: str, model: str = JUDGE_MODEL) -> bool:
    text, _ = _chat(JUDGE_URL, model, [
        {"role": "user", "content": JUDGE_PROMPT.format(
            question=question, gold=gold, predicted=predicted)},
    ], max_tokens=8)
    return "correct" in text.strip().lower()


# -------------------------------------------------------------------- runner
def run_backend(backend: Backend, samples: list[dict], judge_model: str) -> list[dict]:
    rows = []
    for sample in samples:
        backend.ingest(sample)
        for qa in sample["qa"]:
            result = backend.ask(qa["question"])
            correct = judge(qa["question"], qa["answer"], result["answer"], judge_model)
            rows.append({
                "sample_id": sample["sample_id"],
                "question": qa["question"],
                "gold": qa["answer"],
                "predicted": result["answer"],
                "correct": correct,
                "category": qa["category"],
                "category_name": CATEGORY_NAMES.get(qa["category"], str(qa["category"])),
                "context_tokens": result["context_tokens"],
                "tokens_estimated": result["tokens_estimated"],
                "latency_s": round(result["latency_s"], 3),
                "sources": result["sources"],
            })
    return rows


def aggregate(rows: list[dict]) -> dict:
    by_cat: dict[str, list[bool]] = {}
    for r in rows:
        by_cat.setdefault(r["category_name"], []).append(r["correct"])
    return {
        cat: {"n": len(v), "accuracy": round(sum(v) / len(v), 3)}
        for cat, v in sorted(by_cat.items())
    }


def save_results(backend_name: str, rows: list[dict], judge_model: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    path = RESULTS_DIR / f"{date}-{backend_name}.json"
    doc = {
        "dataset": DATASET.name,
        "backend": backend_name,
        "judge_model": judge_model,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "aggregate_accuracy_by_category": aggregate(rows),
        "mean_context_tokens": round(
            sum(r["context_tokens"] for r in rows) / max(len(rows), 1), 1),
        "mean_latency_s": round(sum(r["latency_s"] for r in rows) / max(len(rows), 1), 3),
        "rows": rows,
    }
    path.write_text(json.dumps(doc, indent=2))
    return path


def comparison_table(results: dict[str, dict]) -> str:
    lines = [
        "| backend | accuracy | mean context tokens | mean latency (s) |",
        "|---|---|---|---|",
    ]
    for name, doc in results.items():
        acc = sum(r["correct"] for r in doc["rows"]) / max(len(doc["rows"]), 1)
        lines.append(
            f"| {name} | {acc:.1%} | {doc['mean_context_tokens']} | {doc['mean_latency_s']} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 0 memory-quality harness")
    ap.add_argument("--backend", choices=sorted(BACKENDS), help="backend to run")
    ap.add_argument("--baseline", action="store_true", help="run both backends + table")
    ap.add_argument("--limit", type=int, default=None, help="max samples to evaluate")
    ap.add_argument("--judge-model", default=JUDGE_MODEL)
    args = ap.parse_args()

    if not args.baseline and not args.backend:
        ap.error("specify --backend or --baseline")

    samples = load_locomo()
    if args.limit:
        samples = samples[: args.limit]

    names = sorted(BACKENDS) if args.baseline else [args.backend]
    saved: dict[str, dict] = {}
    for name in names:
        print(f"=== running backend: {name} ({len(samples)} samples) ===", flush=True)
        rows = run_backend(BACKENDS[name], samples, args.judge_model)
        path = save_results(name, rows, args.judge_model)
        saved[name] = json.loads(path.read_text())
        print(f"wrote {path}", flush=True)

    if args.baseline:
        print()
        print(comparison_table(saved))


if __name__ == "__main__":
    main()
