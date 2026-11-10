"""Phase 17: dataset-only recall check for arm (d) (relevance-then-recency).

No model calls and no brains: it replays the committed keyword_backend scoring
exactly (same `tokens`, same overlap/length normalisation, same ordering) over
the 74 eligible knowledge-update questions and reports how often an answer
session survives into arm (d)'s 3 kept sessions under two date-granularity
rules:

  full  - parse "%Y/%m/%d (%a) %H:%M" (what the haystack carries)
  day   - parse "%Y/%m/%d" only, same-day ties broken by score descending

The brief pre-registers the `full` rule; the `day` column exists so the table
cannot be quoted without its parse rule.

Usage:
  PYTHONPATH=src:. .venv/bin/python eval/longmemeval/p17_recall_check.py
"""

import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "eval"))
sys.path.insert(0, str(REPO / "eval" / "longmemeval"))

from lme_eval import tokens  # noqa: E402  (same tokeniser as keyword_backend)

FULL_FMT = "%Y/%m/%d (%a) %H:%M"
DAY_FMT = "%Y/%m/%d"
KS = [3, 4, 5, 6, 8, 10]
EXCLUDED = {"08e075c7", "0f05491a", "2133c1b5_abs", "71315a70"}


def parse(date: str, fmt: str):
    try:
        return datetime.strptime(date, fmt)
    except (ValueError, TypeError):
        return None


def scored_sessions(question: dict):
    """Exactly keyword_backend's scoring, kept as (score, si) with no text."""
    q = Counter(tokens(question["question"]))
    scored = []
    for si, session in enumerate(question["haystack_sessions"]):
        text = "\n".join(f"{t['role']}: {t['content']}" for t in session)
        t = Counter(tokens(text))
        overlap = sum(min(q[w], t[w]) for w in q)
        if overlap:
            scored.append((overlap / (1 + math.log(1 + sum(t.values()))), si))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored


def kept(question: dict, scored, k: int, fmt: str):
    """Top-k by relevance, then newest first; keep 3. Unparseable last,
    tie-break score descending, then session index (deterministic)."""
    top = scored[:k]
    dates = {si: parse(question["haystack_dates"][si], fmt) for _, si in top}
    ordered = sorted(
        top,
        key=lambda x: (
            dates[x[1]] is not None,
            dates[x[1]] or datetime.min,
            x[0],
            -x[1],
        ),
        reverse=True,
    )
    return [si for _, si in ordered[:3]]


def main() -> int:
    data = json.load(open(REPO / "eval" / "datasets" / "longmemeval_s_cleaned.json"))
    ku = [q for q in data if q.get("question_type") == "knowledge-update"]
    eligible = sorted((q for q in ku if q["question_id"] not in EXCLUDED),
                      key=lambda q: q["question_id"])

    sessions_per_q = []
    overlap_per_q = []
    answer_counts = []
    unparsed_full = 0
    same_day_top4 = 0
    rule_disagrees = 0
    full = {k: {"any": 0, "latest": 0} for k in KS}
    day = {k: {"any": 0, "latest": 0} for k in KS}
    c_any = 0
    c_latest = 0

    for q in eligible:
        scored = scored_sessions(q)
        sessions_per_q.append(len(q["haystack_sessions"]))
        overlap_per_q.append(len(scored))
        ids = list(q.get("answer_session_ids") or [])
        answer_counts.append(len(ids))
        sid_index = {sid: i for i, sid in enumerate(q["haystack_session_ids"])}
        answer_idx = [sid_index[s] for s in ids if s in sid_index]
        if not answer_idx:
            print("WARN no answer session index for", q["question_id"])
            continue
        for si in answer_idx:
            if parse(q["haystack_dates"][si], FULL_FMT) is None:
                unparsed_full += 1

        latest_idx = max(
            answer_idx,
            key=lambda si: parse(q["haystack_dates"][si], FULL_FMT) or datetime.min,
        )

        # (c) as committed: top-3 by score, no reordering.
        c_keep = [si for _, si in scored[:3]]
        c_any += int(any(si in c_keep for si in answer_idx))
        c_latest += int(latest_idx in c_keep)

        # Same-day ties within the relevance top 4 (date-only equality).
        top4_days = [q["haystack_dates"][si][:10] for _, si in scored[:4]]
        if len(top4_days) == 4 and len(set(top4_days)) < 4:
            same_day_top4 += 1

        for k in KS:
            kf = kept(q, scored, k, FULL_FMT)
            kd = kept(q, scored, k, DAY_FMT)
            full[k]["any"] += int(any(si in kf for si in answer_idx))
            full[k]["latest"] += int(latest_idx in kf)
            day[k]["any"] += int(any(si in kd for si in answer_idx))
            day[k]["latest"] += int(latest_idx in kd)
            if k == 4 and set(kf) != set(kd):
                rule_disagrees += 1

    n = len(eligible)
    print("eligible_n %d" % n)
    print("sessions_per_q mean %.1f min %d max %d" %
          (sum(sessions_per_q) / n, min(sessions_per_q), max(sessions_per_q)))
    print("sessions_with_overlap mean %.1f min %d" %
          (sum(overlap_per_q) / n, min(overlap_per_q)))
    print("answer_sessions_per_q set %s" % sorted(set(answer_counts)))
    print("unparsed_full_timestamp %d" % unparsed_full)
    print("questions_with_same_day_tie_in_top4 %d" % same_day_top4)
    print("questions_where_full_and_day_k4_keep_differ %d" % rule_disagrees)
    print("c_top3_any_answer %d/%d latest %d/%d" % (c_any, n, c_latest, n))
    print("k  full_any full_latest day_any day_latest")
    for k in KS:
        print("%-2d %-8d %-11d %-7d %d" %
              (k, full[k]["any"], full[k]["latest"], day[k]["any"], day[k]["latest"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
