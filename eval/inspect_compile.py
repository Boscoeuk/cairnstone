
import json, sys, tempfile, os
sys.path.insert(0, "src")
from cairnstone import store, compile as C
from cairnstone.llm import LLMClient

data = json.load(open("eval/datasets/locomo10.json"))
conv = data[0]["conversation"]
stamp = conv.get("session_1_date_time")
turns = conv["session_1"][:10]
tmp = os.path.join(tempfile.gettempdir(), "cairnstone-smoke")
os.makedirs(tmp, exist_ok=True)
db = os.path.join(tmp, "inspect.db")
if os.path.exists(db): os.remove(db)
conn = store.init_db(db)
ws = store.create_workspace(conn, "w"); brain = store.create_brain(conn, ws, "b", "b")
cids = [store.add_capture(conn, brain, "conversation", "%s: %s" % (t["speaker"], t["text"]),
        "locomo:%d" % i, captured_at=stamp) for i, t in enumerate(turns)]
client = LLMClient()
res = C.compile_all(conn, brain, cids, client)
print("session stamp:", stamp)
print("accepted:", res["facts_accepted"], "rejected:", len(res["facts_rejected"]))
for f in conn.execute("SELECT text, quote FROM facts ORDER BY id").fetchall():
    print("FACT:", f["text"])
    print("  quote:", f["quote"][:90].replace("\n", " "))
print("uncited:", C.uncited_facts(conn, brain))
REL = ("yesterday","today","tomorrow","last week","next week","last month","ago","recently")
bad = [f["text"] for f in conn.execute("SELECT text FROM facts").fetchall()
       if any(w in f["text"].lower() for w in REL)]
print("facts still containing relative time:", bad)
