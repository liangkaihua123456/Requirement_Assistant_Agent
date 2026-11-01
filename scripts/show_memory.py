"""记忆系统只读体检：一条命令看清 短期/长期/归档 三层记忆的现状。

用法:
    python scripts/show_memory.py            # 全局概览
    python scripts/show_memory.py shop-A     # 看某个项目
    python scripts/show_memory.py '' fba5b06d  # 看某任务的短期记忆
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PROJECT = (sys.argv[1] or None) if len(sys.argv) > 1 else None
TASK_ID = (sys.argv[2] or None) if len(sys.argv) > 2 else None
DB = str(ROOT / "data" / "tasks.db")
CKPT = str(ROOT / "data" / "checkpoints" / "langgraph_checkpoints_v2.sqlite")

def section(title): print(f"\n══ {title} ══")

section("① 短期记忆（LangGraph state.task_memory + checkpoint）")
snap_rows = sqlite3.connect(DB).execute(
    "select task_id,status from tasks order by created_at desc limit 6").fetchall()
for tid, st in snap_rows:
    snap = json.loads(sqlite3.connect(DB).execute("select state_snapshot from tasks where task_id=?", (tid,)).fetchone()[0] or "{}")
    tm = snap.get("task_memory") or []
    if TASK_ID and tid != TASK_ID: continue
    print(f"  任务 {tid} [{st}] 短期记忆 {len(tm)} 条:")
    for e in tm[-4:]:
        print(f"    · [{e.get('node')}] iter{e.get('iteration')} {(e.get('summary') or '')[:56]}")
try:
    cp = sqlite3.connect(CKPT)
    rows = cp.execute("select thread_id, count(*) from checkpoints group by thread_id").fetchall()
    print(f"  checkpoint 现存线程: {rows if rows else '（空——终态任务已回收，正常）'}")
    cp.close()
except Exception as e:
    print("  checkpoint:", e)

section("② 长期记忆归档账本（SQLite project_memory）")
conn = sqlite3.connect(DB)
q = "select project_id, memory_type, memory_key, overall_score, substr(replace(content,'\n',' '),1,42) from project_memory"
p: list = []
if PROJECT: q += " where project_id=?"; p=[PROJECT]
rows = conn.execute(q + " order by created_at desc limit 12", p).fetchall()
if not rows:
    print("  （空）→ 只有「评审通过 且 评分≥7」的任务完成时才会写入；你的历史任务多为未通过，属正常")
for r in rows: print("  ", r)

section("③ 向量记忆库（Chroma，按项目分 collection）")
try:
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    import chromadb
    from chromadb.config import Settings
    cl = chromadb.PersistentClient(path=str(ROOT / "data" / "chroma"), settings=Settings(anonymized_telemetry=False))
    for c in cl.list_collections():
        name = c if isinstance(c, str) else c.name
        if PROJECT and name != f"agent_memory_{PROJECT.lower()}": continue
        col = cl.get_collection(name)
        print(f"  {name}: {col.count()} 条")
        sample = col.get(limit=3, include=["documents"])
        for d in (sample.get("documents") or []):
            print("     ·", d.replace("\n", " ")[:52])
except Exception as e:
    print("  chroma 读取失败:", e)
print()
