"""Report the in-flight smoke brain's compile progress (read-only, no model calls)."""

import sqlite3

p = "eval/results/ku-db/71315a70.tmp"
conn = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
print("captures", conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0])
print("distinct capture ids in facts",
      conn.execute("SELECT COUNT(DISTINCT capture_id) FROM facts").fetchone()[0])
print("max capture_id in facts",
      conn.execute("SELECT MAX(capture_id) FROM facts").fetchone()[0])
print("facts", conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0])
