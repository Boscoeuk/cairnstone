"""Build a dogfood corpus from this profile's real Hermes session transcript.

Source: ~/.hermes/state.db (messages table) for the Cairnstone build session.
Only user and assistant messages are captured. Tool-result messages are skipped: they are mostly
raw command output, they dominate the byte count, and the claims we care about are in the prose.

Long messages are split into <=1500-character captures so a single extraction call never has to
handle an enormous turn. Each capture records the original message timestamp so the compiler can
resolve relative dates.
"""
import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cairnstone import store  # noqa: E402

STATE_DB = os.path.expanduser("~/.hermes/state.db")
CHUNK = 1500


def chunks(text):
    text = (text or "").strip()
    out = []
    while text:
        cut = text[:CHUNK]
        if len(text) > CHUNK:
            # prefer a paragraph or sentence boundary
            for sep in ("\n\n", "\n", ". "):
                i = cut.rfind(sep)
                if i > CHUNK // 2:
                    cut = cut[:i + len(sep)]
                    break
        out.append(cut.strip())
        text = text[len(cut):].lstrip()
    return [c for c in out if c]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--session", default=None, help="session id; default = most recent")
    ap.add_argument("--out", default="eval/dogfood/captures.jsonl")
    args = ap.parse_args()

    con = sqlite3.connect(STATE_DB)
    con.row_factory = sqlite3.Row
    sid = args.session or con.execute(
        "SELECT session_id FROM messages GROUP BY session_id"
        " ORDER BY MAX(timestamp) DESC LIMIT 1").fetchone()["session_id"]

    rows = list(con.execute(
        "SELECT role, content, timestamp FROM messages"
        " WHERE session_id = ? AND role IN ('user','assistant') ORDER BY id", (sid,)))

    conn = store.init_db(args.db)
    # The CLI addresses a "default"/"default" brain; keep the corpus addressable by it.
    ws = store.create_workspace(conn, "default")
    brain = store.create_brain(conn, ws, "default", "default")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    n = 0
    with open(args.out, "w", encoding="utf-8") as fh:
        for i, r in enumerate(rows):
            ts = r["timestamp"]
            stamp = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else None
            for j, part in enumerate(chunks(r["content"])):
                text = "%s: %s" % (r["role"], part)
                source = "session:%s:%d:%d" % (sid[:12], i, j)
                cid = store.add_capture(conn, brain, "chat", text, source, captured_at=stamp)
                fh.write(json.dumps({"id": cid, "source": source, "role": r["role"],
                                     "captured_at": stamp, "chars": len(text)}) + "\n")
                n += 1

    print("session:", sid)
    print("messages:", len(rows))
    print("captures:", n)
    print("db:", args.db)
    print("brain_id:", brain)


if __name__ == "__main__":
    main()
