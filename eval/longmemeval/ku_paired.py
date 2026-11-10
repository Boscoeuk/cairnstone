"""Phase 17 harness: four-arm paired consolidation test (P8).

The product's thesis is that a nightly consolidation pass improves a memory
over time. Phase 16 answered it with two arms; phase 17 widens the comparison
to four arms run in one pass per question (docs/phase17-brief.md P8.4, B2):

  (a) Cairnstone as the compiler left it — retrieve.build_brief against the
      PRISTINE <qid>.db, no consolidation call;
  (b) the same brain after one nightly pass — consolidate() with the CLI's
      default max_mutation_rate=0.2, run on a backup copy;
  (c) keyword retrieval as committed (lme_eval.keyword_backend, unchanged);
  (d) keyword retrieval, relevance first then recency
      (lme_eval.keyword_relevance_recency_backend, B2).

The pristine brain is compiled once into eval/results/ku-db/<qid>.db and is
never consolidated in place; the nightly pass runs on a SQLite backup copy
(<qid>.consolidated.db). Reuse of a compiled brain is conditional on a
fail-closed provenance sidecar (<qid>.meta.json, P8.8): a brain compiled by
pre-freeze code, or whose file hash no longer matches its sidecar, is
recompiled, never read.

Question selection is config-driven (P8.5, P11): the harness takes --ids-file
(the committed ids config) and runs the literal ids it lists, in the listed
order. There is no random call anywhere in this module.

The judge's /health identity is recorded per question (P8.6); a label change
from the run-start value stops the run.

One implementation note on the pristine hash: retrieve.build_brief is the only
code that writes to a compiled brain after compile_all (the embeddings cache,
retrieve.cached_embeddings). The harness warms that cache with the exact call
arm (a) is about to make, before the brain's hash is recorded, so the arm
itself finds every vector cached and writes nothing — the hash recorded in the
sidecar then stays valid for the whole run and for later resumes. With the
embedding endpoint down the warm-up degrades to the lexical path and writes
nothing.

Usage:

  PYTHONPATH=src:. .venv/bin/python eval/longmemeval/ku_paired.py \
      --ids-file eval/longmemeval/ku-phase17-config.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "eval"))
sys.path.insert(0, str(REPO / "eval" / "longmemeval"))

import harness  # noqa: E402
import lme_eval as lme  # noqa: E402
from cairnstone import compile as cairn_compile  # noqa: E402
from cairnstone import retrieve, store  # noqa: E402
from cairnstone.llm import LLMClient  # noqa: E402
from p17_recall_check import EXCLUDED  # noqa: E402  (pre-registered exclusions)

KU_DB_DIR = REPO / "eval" / "results" / "ku-db"
RESULTS_DIR = REPO / "eval" / "results"

REQUIRED_CONFIG_KEYS = ("frozen_code_sha", "dataset_path", "ids",
                        "eligible_ids", "budget_tokens", "max_mutation_rate")


class ContaminationError(RuntimeError):
    """The pristine brain's hash changed after answering started (P8.3)."""


# ------------------------------------------------------------------- helpers

def sha256_file(path) -> str:
    """sha256 of a file, streamed."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sidecar_path(db_path: Path) -> Path:
    """<qid>.db -> <qid>.meta.json (P8.8)."""
    return db_path.with_suffix(".meta.json")


def consolidated_path(db_path: Path) -> Path:
    """<qid>.db -> <qid>.consolidated.db (P8.2)."""
    return db_path.with_suffix(".consolidated.db")


def checkpointed_sha(conn, db_path) -> str:
    """Flush the WAL into the main db file, then hash it.

    A hash taken without the checkpoint would miss committed writes still
    sitting in the WAL, so the non-contamination assertions (P8.3) would be
    vacuous whenever a write did land on the pristine brain.
    """
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return sha256_file(db_path)


def open_and_hash(db_path):
    """Open a brain and return (conn, brain_id, canonical_sha).

    store.init_db runs migrations on every open (_migrate_timestamps,
    _backfill_compiled_at), so the file's bytes are not stable across the first
    reopen of a freshly written brain: the backfill stamps compiled_at on
    captures that already produced facts and rewrites pages doing it. A hash
    taken before that rewrite can never match the hash of the same brain after
    it, which is why a pre-open file hash refused every reuse of a brain the
    harness had just compiled (P8.1).

    The identity hash is therefore defined as "after the open, its migrations
    and a WAL checkpoint". That is the state every later open reproduces byte
    for byte, so the sidecar rule compares like with like.
    """
    conn = store.init_db(str(db_path))
    brain_id = conn.execute(
        "SELECT id FROM brains ORDER BY id LIMIT 1").fetchone()["id"]
    return conn, brain_id, checkpointed_sha(conn, db_path)


def _canonical_sha(db_path) -> str:
    """Canonical hash of a brain the caller is not holding open.

    Opens it so store.init_db's migrations run, checkpoints the WAL and closes,
    which is the only state whose hash is reproducible across opens.
    """
    conn, _brain_id, sha = open_and_hash(db_path)
    conn.close()
    return sha


def warm_embedding_cache(conn, brain_id, question, budget) -> None:
    """Populate the embedding cache before the pristine brain's hash is taken.

    Calls retrieve.build_brief with the exact arguments arm (a) will use, so
    the arm finds every vector cached and writes nothing after the hash is
    recorded. With the endpoint down this degrades to the lexical path and
    writes nothing (retrieve.cached_embeddings fails open, misses uncached).
    """
    retrieve.build_brief(conn, brain_id, question["question"],
                         budget_tokens=budget)


def sqlite_backup_copy(src_path, dst_path) -> None:
    """Copy a brain with the sqlite3 backup API (P8.2) — never a file copy, so
    the copy is a consistent snapshot even while the source is open."""
    for stale in (dst_path, Path(str(dst_path) + "-wal"),
                  Path(str(dst_path) + "-shm")):
        if stale.exists():
            stale.unlink()
    src = sqlite3.connect(str(src_path))
    try:
        dst = sqlite3.connect(str(dst_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


# ------------------------------------------------- provenance sidecars (P8.8)

def check_sidecar(db_path, frozen_code_sha, config_sha256, dataset_sha256,
                  current_sha=None):
    """The fail-closed reuse rule, as one unit-tested function (P8.8).

    The brain may be read only when a parseable sidecar exists whose code_sha,
    config_sha256 and dataset_sha256 match the frozen values and whose
    db_sha256 matches the brain's canonical hash. Anything else — missing
    sidecar, unparseable JSON, any mismatch — refuses the brain: the caller
    must recompile and rewrite the sidecar, never read.

    `current_sha` is the canonical hash the caller already took from an open
    connection (`open_and_hash`). When it is omitted this function opens the
    brain itself: a bare file hash is taken before store.init_db's one-time
    migration rewrite and can miss writes still sitting in the WAL, so it can
    never match a sidecar written after the open.
    """
    if not db_path.exists():
        return False, "db-missing", None
    sp = sidecar_path(db_path)
    if not sp.exists():
        return False, "sidecar-missing", None
    try:
        meta = json.loads(sp.read_text())
    except (OSError, ValueError):
        return False, "sidecar-mismatch", None
    if not isinstance(meta, dict):
        return False, "sidecar-mismatch", None
    required = ("question_id", "code_sha", "config_sha256", "dataset_sha256",
                "compile_started_utc", "compile_finished_utc", "captures",
                "facts", "db_sha256")
    if any(k not in meta for k in required):
        return False, "sidecar-mismatch", None
    if current_sha is None:
        conn, _brain_id, current_sha = open_and_hash(db_path)
        conn.close()
    if (meta["code_sha"] != frozen_code_sha
            or meta["config_sha256"] != config_sha256
            or meta["dataset_sha256"] != dataset_sha256
            or meta["db_sha256"] != current_sha):
        return False, "sidecar-mismatch", None
    return True, "sidecar-ok", meta


def write_sidecar(db_path, *, question_id, code_sha, config_sha256,
                  dataset_sha256, summary, started_utc, db_sha256=None):
    """Write the pristine brain's provenance sidecar (P8.8). The harness owns
    it; it is never repaired by hand.

    `db_sha256` must be the CHECKPOINTED hash (see `checkpointed_sha`). Hashing
    the file directly misses committed writes still in the WAL, so the sidecar
    would record a hash that the reuse check can never match — every reuse would
    look like a sidecar mismatch and silently recompile, which is the failure
    this sidecar exists to prevent.
    """
    meta = {
        "question_id": question_id,
        "code_sha": code_sha,
        "config_sha256": config_sha256,
        "dataset_sha256": dataset_sha256,
        "compile_started_utc": started_utc,
        "compile_finished_utc": _utcnow(),
        "captures": summary["captures"],
        "facts": summary["facts_accepted"],
        "db_sha256": db_sha256 or _canonical_sha(db_path),
    }
    sidecar_path(db_path).write_text(
        json.dumps(meta, indent=1, sort_keys=True) + "\n")
    return meta


def check_consolidated_sidecar(cons_path, pristine_sha, frozen_code_sha,
                               config_sha256, current_sha=None):
    """Fail-closed reuse rule for the consolidated copy (P8.8): it is reused
    only when its sidecar exists and parses, was derived from the current
    pristine hash, and its own db_sha256 still matches the copy's canonical
    hash. Otherwise the copy is rebuilt, not reused."""
    if not cons_path.exists():
        return False, None
    sp = cons_path.with_suffix(".meta.json")
    if not sp.exists():
        return False, None
    try:
        meta = json.loads(sp.read_text())
    except (OSError, ValueError):
        return False, None
    if not isinstance(meta, dict):
        return False, None
    if current_sha is None:
        current_sha = _canonical_sha(cons_path)
    if (meta.get("code_sha") != frozen_code_sha
            or meta.get("config_sha256") != config_sha256
            or meta.get("source_db_sha256") != pristine_sha
            or meta.get("db_sha256") != current_sha):
        return False, None
    return True, meta


def write_consolidated_sidecar(cons_path, *, question_id, code_sha,
                               config_sha256, source_db_sha256,
                               max_mutation_rate, counts, db_sha256=None):
    """Sidecar for the consolidated copy: the pristine hash it was derived
    from, the rate used, the returned counts, and its own db hash (P8.8)."""
    meta = {
        "question_id": question_id,
        "code_sha": code_sha,
        "config_sha256": config_sha256,
        "source_db_sha256": source_db_sha256,
        "max_mutation_rate": max_mutation_rate,
        "consolidation": counts,
        "db_sha256": db_sha256 or _canonical_sha(cons_path),
        "created_utc": _utcnow(),
    }
    cons_path.with_suffix(".meta.json").write_text(
        json.dumps(meta, indent=1, sort_keys=True) + "\n")
    return meta


# ----------------------------------------------------------------- ids config

def load_config(path, pool=None):
    """Load the committed ids config and fail closed on any disagreement with
    the dataset's eligible set (P8.5, P11)."""
    path = Path(path)
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError("ids config %s is missing or unparseable: %s"
                         % (path, exc)) from exc
    if not isinstance(cfg, dict):
        raise ValueError("ids config must be a JSON object")
    missing = [k for k in REQUIRED_CONFIG_KEYS if k not in cfg]
    if missing:
        raise ValueError("ids config is missing keys: %s" % ", ".join(missing))
    dataset_path = Path(cfg["dataset_path"])
    if not dataset_path.is_absolute():
        dataset_path = REPO / dataset_path
    if pool is not None:
        ku = {q["question_id"] for q in pool
              if q.get("question_type") == "knowledge-update"}
        eligible = sorted(ku - set(EXCLUDED))
        if sorted(set(cfg["eligible_ids"])) != eligible:
            raise ValueError(
                "config eligible_ids disagree with the dataset's eligible "
                "knowledge-update set (P11 fail-closed)")
    ids = cfg["ids"]
    if len(set(ids)) != len(ids):
        raise ValueError("config ids contain duplicates")
    unknown = sorted(set(ids) - set(cfg["eligible_ids"]))
    if unknown:
        raise ValueError("config ids outside the eligible set: %s"
                         % ", ".join(unknown))
    cfg = dict(cfg)
    cfg["_path"] = str(path)
    cfg["_config_sha256"] = sha256_file(path)
    cfg["_dataset_path"] = dataset_path
    cfg["_dataset_sha256"] = sha256_file(dataset_path)
    return cfg


# ------------------------------------------------------------------- judging

def judge_identity():
    """GET the judge's /health and return its identity (P8.6)."""
    base = lme.JUDGE_URL.rsplit("/v1", 1)[0]
    req = urllib.request.Request(base + "/health",
                                 headers={"Authorization": "Bearer local"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {
        "name": data.get("name"),
        "label": data.get("label"),
        "upstream_model": data.get("upstream_model"),
        "utc": _utcnow(),
    }


# ---------------------------------------------------------------- statistics

def mcnemar_exact(b, c):
    """Two-sided exact McNemar p for discordant counts b and c."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    # P(X <= k) for X ~ Binomial(n, 0.5), doubled for a two-sided test.
    tail = sum(_binom(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def _binom(n, k):
    out = 1
    for i in range(k):
        out = out * (n - i) // (i + 1)
    return out


# ----------------------------------------------------------------- the brains

def _open_pristine(question, db_path, client, budget, frozen_sha, config_sha,
                   dataset_sha):
    """Open (or compile) the pristine brain under the fail-closed sidecar rule
    (P8.1, P8.8). Returns (conn, brain_id, compile_stats, reused, reason, sha).

    On reuse the brain is opened, its embedding cache warmed and its file
    re-hashed; if the hash no longer matches the sidecar (only possible when
    the cache was cold at compile time and the endpoint is up now), the brain
    is refused and recompiled — never read by any arm.
    """
    qid = question["question_id"]
    reason = "db-missing"
    meta = None
    if db_path.exists():
        # Open first: store.init_db's migrations rewrite a freshly written
        # brain on its first reopen, so the identity hash must be taken after
        # that rewrite (open_and_hash), never from the pre-open file.
        conn, brain_id, sha = open_and_hash(db_path)
        ok, reason, meta = check_sidecar(db_path, frozen_sha, config_sha,
                                         dataset_sha, current_sha=sha)
        if ok and meta is not None:
            warm_embedding_cache(conn, brain_id, question, budget)
            sha = checkpointed_sha(conn, db_path)
            if sha == meta["db_sha256"]:
                comp = {"captures": meta["captures"], "facts": meta["facts"]}
                return conn, brain_id, comp, True, reason, sha
            conn.close()
            reason = "sidecar-mismatch"
        else:
            conn.close()
    started = _utcnow()
    conn, brain_id, summary = lme.compile_question(question, db_path, client,
                                                   True)
    warm_embedding_cache(conn, brain_id, question, budget)
    sha = checkpointed_sha(conn, db_path)
    write_sidecar(db_path, question_id=qid, code_sha=frozen_sha,
                  config_sha256=config_sha, dataset_sha256=dataset_sha,
                  summary=summary, started_utc=started, db_sha256=sha)
    comp = {"captures": summary["captures"],
            "facts": summary["facts_accepted"],
            "report": lme.compile_report(summary)}
    return conn, brain_id, comp, False, reason, sha


def _open_consolidated(db_path, cons_path, question, budget, pristine_sha,
                       frozen_sha, config_sha, rate):
    """Open (or rebuild) the consolidated copy (P8.2, P8.8). The nightly pass
    runs on the backup copy, never on the original. Returns
    (conn, brain_id, counts, reused)."""
    qid = question["question_id"]
    if cons_path.exists():
        conn, brain_id, sha = open_and_hash(cons_path)
        warm_embedding_cache(conn, brain_id, question, budget)
        sha = checkpointed_sha(conn, cons_path)
        ok, meta = check_consolidated_sidecar(cons_path, pristine_sha,
                                              frozen_sha, config_sha,
                                              current_sha=sha)
        if ok and meta is not None:
            return conn, brain_id, meta["consolidation"], True
        conn.close()
    sqlite_backup_copy(db_path, cons_path)
    conn, brain_id, _ = open_and_hash(cons_path)
    try:
        counts = cairn_compile.consolidate(conn, brain_id,
                                           max_mutation_rate=rate)
    except cairn_compile.PolicyHalt as exc:
        counts = {"policy_halt": True, "error": str(exc)}
    warm_embedding_cache(conn, brain_id, question, budget)
    cons_sha = checkpointed_sha(conn, cons_path)
    write_consolidated_sidecar(cons_path, question_id=qid, code_sha=frozen_sha,
                               config_sha256=config_sha,
                               source_db_sha256=pristine_sha,
                               db_sha256=cons_sha,
                               max_mutation_rate=rate, counts=counts)
    return conn, brain_id, counts, False


# ----------------------------------------------------------------- the harness

def run_one(question, budget, client, config, start_label=None):
    """One question, four arms, one pass (P8.4).

    `client` is the extraction/answer endpoint client; the answering backends
    use lme_eval's module client (lme._client), which main() points at the
    same endpoint. `start_label` is the judge label recorded at run start; a
    per-question change stops the run (P8.6).
    """
    qid = question["question_id"]
    db_path = KU_DB_DIR / ("%s.db" % qid)
    frozen_sha = config["frozen_code_sha"]
    config_sha = config["_config_sha256"]
    dataset_sha = config["_dataset_sha256"]
    rate = config["max_mutation_rate"]

    conn, brain_id, comp, reused, reason, pristine_sha = _open_pristine(
        question, db_path, client, budget, frozen_sha, config_sha, dataset_sha)

    row = {
        "question_id": qid,
        "question": question["question"],
        "gold": question["answer"],
        "answer_session_ids": question.get("answer_session_ids", []),
        "compile": comp,
        "reused": reused,
        "reuse_reason": reason,
        "pristine_db_sha256": pristine_sha,
        "max_mutation_rate": rate,
    }

    # ---- P8.3: the pristine brain is asserted unconsolidated immediately
    # before arm (a) reads it.
    if checkpointed_sha(conn, db_path) != pristine_sha:
        conn.close()
        raise ContaminationError(
            "%s: pristine brain changed before arm (a)" % qid)

    # ---- the nightly pass on a backup copy, never on the original (P8.2)
    cons_path = consolidated_path(db_path)
    cons_conn, cons_brain, cons_counts, cons_reused = _open_consolidated(
        db_path, cons_path, question, budget, pristine_sha, frozen_sha,
        config_sha, rate)

    # ---- arm (a): the pristine brief (B2 (a))
    arm_a = lme.cairnstone_backend(conn, brain_id, question, budget)
    # ---- arm (b): the consolidated copy's brief (B2 (b))
    arm_b = lme.cairnstone_backend(cons_conn, cons_brain, question, budget)
    # ---- arms (c) and (d): dataset only, no brain, no embeddings (P8.4)
    arm_c = lme.keyword_backend(question)
    arm_d = lme.keyword_relevance_recency_backend(question)

    # ---- P8.6: judge identity, immediately before judging this question
    identity = judge_identity()
    if start_label is not None and identity.get("label") != start_label:
        conn.close()
        cons_conn.close()
        raise RuntimeError(
            "judge label changed from %r to %r; stopping the run (B11)"
            % (start_label, identity.get("label")))

    for arm_key, arm in (("a", arm_a), ("b", arm_b), ("c", arm_c), ("d", arm_d)):
        ok, amb = harness.judge(question["question"], question["answer"],
                                arm["answer"], model=lme.JUDGE_MODEL)
        arm["correct"] = ok
        arm["judge_ambiguous"] = amb

    row["judge_identity"] = identity
    row["arm_a"] = arm_a
    row["arm_b"] = arm_b
    row["arm_c"] = arm_c
    row["arm_d"] = arm_d
    row["consolidation"] = cons_counts
    row["consolidated_reused"] = cons_reused
    row["consolidated_db_sha256"] = checkpointed_sha(cons_conn, cons_path)
    row["facts"] = {
        "active_pristine": conn.execute(
            "SELECT COUNT(*) FROM facts WHERE status = 'active'"
        ).fetchone()[0],
        "superseded_pristine": conn.execute(
            "SELECT COUNT(*) FROM facts WHERE status = 'superseded'"
        ).fetchone()[0],
        "active_consolidated": cons_conn.execute(
            "SELECT COUNT(*) FROM facts WHERE status = 'active'"
        ).fetchone()[0],
        "superseded_consolidated": cons_conn.execute(
            "SELECT COUNT(*) FROM facts WHERE status = 'superseded'"
        ).fetchone()[0],
    }

    # ---- P8.3: assert the pristine brain again after the whole question
    final_sha = checkpointed_sha(conn, db_path)
    conn.close()
    cons_conn.close()
    if final_sha != pristine_sha:
        raise ContaminationError(
            "%s: pristine brain hash changed during the run" % qid)
    return row


def aggregate(rows):
    """Paired counts and the honest summary statistics (B1: the thesis holds
    only if (b) beats (a) AND (b) beats (d); anything else is reported as
    "not shown at this n")."""
    if not rows:
        return {"label": "LOCAL-JUDGED", "n": 0}

    def acc(arm):
        return round(sum(1 for r in rows if r[arm]["correct"]) / len(rows), 3)

    def paired(base, other):
        gained = sum(1 for r in rows
                     if not r[base]["correct"] and r[other]["correct"])
        lost = sum(1 for r in rows
                   if r[base]["correct"] and not r[other]["correct"])
        return gained, lost

    a_gained, a_lost = paired("arm_a", "arm_b")
    d_gained, d_lost = paired("arm_d", "arm_b")
    return {
        "label": "LOCAL-JUDGED",
        "n": len(rows),
        "arm_accuracy": {a: acc("arm_" + a) for a in "abcd"},
        "b_vs_a": {"gained": a_gained, "lost": a_lost,
                   "mcnemar_exact_p": round(mcnemar_exact(a_gained, a_lost), 4)},
        "b_vs_d": {"gained": d_gained, "lost": d_lost,
                   "mcnemar_exact_p": round(mcnemar_exact(d_gained, d_lost), 4)},
        "questions_mutated_by_consolidation": sum(
            1 for r in rows if r["consolidation"].get("superseded")
            or r["consolidation"].get("duplicates_linked")),
        "total_superseded": sum(r["consolidation"].get("superseded", 0)
                                for r in rows),
        "total_duplicates_linked": sum(r["consolidation"].get("duplicates_linked", 0)
                                       for r in rows),
        "total_flagged": sum(r["consolidation"].get("flagged", 0)
                             for r in rows),
        "judge_ambiguous_count": sum(r[arm]["judge_ambiguous"] for r in rows
                                     for arm in ("arm_a", "arm_b", "arm_c",
                                                 "arm_d")),
    }


# ----------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="Phase 17 four-arm paired consolidation test (P8)")
    ap.add_argument("--ids-file", required=True,
                    help="committed ids config (P11, B5)")
    ap.add_argument("--budget", type=int, default=None,
                    help="brief token budget (default: config budget_tokens)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--resume", action="store_true",
                    help="skip questions already present in --out")
    args = ap.parse_args()

    pool = json.load(open(REPO / "eval" / "datasets"
                          / "longmemeval_s_cleaned.json"))
    cfg = load_config(args.ids_file, pool)
    by_id = {q["question_id"]: q for q in pool}
    missing = [qid for qid in cfg["ids"] if qid not in by_id]
    if missing:
        raise SystemExit("ids not in dataset: %s" % ", ".join(missing))
    budget = args.budget if args.budget is not None else cfg["budget_tokens"]

    client = LLMClient(base_url=lme.ANSWER_BASE_URL, model=lme.ANSWER_MODEL)
    lme._client = client
    harness.JUDGE_URL = lme.JUDGE_URL.rstrip("/") + "/chat/completions"
    harness.JUDGE_MODEL = lme.JUDGE_MODEL

    start_identity = judge_identity()
    print("judge at start: name=%s label=%s upstream_model=%s"
          % (start_identity.get("name"), start_identity.get("label"),
             start_identity.get("upstream_model")), flush=True)

    out = Path(args.out) if args.out else RESULTS_DIR / (
        "ku-paired-b%d-%s.json" % (budget,
                                   datetime.now(timezone.utc)
                                   .strftime("%Y%m%d-%H%M%SZ")))
    rows = []
    done = set()
    if args.resume and out.exists():
        prev = json.load(open(out))
        rows = prev.get("rows", [])
        done = {r["question_id"] for r in rows}
        print("resuming: %d questions already done" % len(done), flush=True)

    t0 = time.monotonic()
    for i, qid in enumerate(cfg["ids"], 1):
        if qid in done:
            print("[%d/%d] %s (cached)" % (i, len(cfg["ids"]), qid), flush=True)
            continue
        print("[%d/%d] %s" % (i, len(cfg["ids"]), qid), flush=True)
        rows.append(run_one(by_id[qid], budget, client, cfg,
                            start_label=start_identity.get("label")))
        # Write after every question so an interrupted run can be resumed
        # rather than paying for the compile of a 48-session haystack twice.
        json.dump({"config_sha256": cfg["_config_sha256"],
                   "frozen_code_sha": cfg["frozen_code_sha"],
                   "budget_tokens": budget,
                   "max_mutation_rate": cfg["max_mutation_rate"],
                   "aggregate": aggregate(rows), "rows": rows,
                   "partial": True,
                   "elapsed_s": round(time.monotonic() - t0, 1)},
                  open(out, "w"), indent=1)

    agg = aggregate(rows)
    json.dump({"config_sha256": cfg["_config_sha256"],
               "frozen_code_sha": cfg["frozen_code_sha"],
               "budget_tokens": budget,
               "max_mutation_rate": cfg["max_mutation_rate"],
               "aggregate": agg, "rows": rows, "partial": False,
               "elapsed_s": round(time.monotonic() - t0, 1)},
              open(out, "w"), indent=1)
    print("\n" + json.dumps(agg, indent=1))
    print("wrote %s" % out)
    print("elapsed %.1f s" % (time.monotonic() - t0))


if __name__ == "__main__":
    main()
