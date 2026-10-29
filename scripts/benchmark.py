"""End-to-end benchmark for the delivery workflow.

Runs three fixed requirements through the real graph, auto-resuming the
human steps, and prints one JSON summary per case. Use it to compare a run
before and after a change:

    python scripts/benchmark.py --case all

Requires a real OPENAI_API_KEY in .env. With no key the script exits early.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.graph.builder import build_graph  # noqa: E402
from app.tools.coverage_metrics import coverage_report  # noqa: E402

CASES: dict[str, str] = {
    "simple": (
        "做一个个人待办事项应用。用户可以创建、编辑、完成、删除待办，"
        "支持按截止日期排序和标签分类，数据本地持久化。"
    ),
    "medium": (
        "做一个面向中小餐饮门店的线上点单系统。顾客扫码进入菜单，"
        "选规格加购物车下单，支持在线支付；商家端可以接单、改菜品库存、"
        "查看当日营业额；需要订单状态流转（待支付/已支付/制作中/已完成/已退款）。"
    ),
    "complex": (
        "做一个跨境电商的履约中台。支持多仓库存同步、订单拆单合单、"
        "物流轨迹回传、退换货与逆向物流、关税与汇率计算、"
        "供应商结算对账。要求幂等、可审计、支持多租户数据隔离，"
        "高峰期每秒 2000 单，库存扣减不能超卖。"
    ),
}


def _interrupt_kind(result: dict) -> str:
    payload = result.get("__interrupt__")
    if not payload:
        return ""
    first = payload[0] if isinstance(payload, (list, tuple)) and payload else payload
    value = getattr(first, "value", None)
    if isinstance(value, dict):
        return str(value.get("type") or "")
    return ""


def run_case(graph, name: str, text: str) -> dict:
    task_id = f"bench_{name}_{int(time.time())}"
    config = {"configurable": {"thread_id": task_id}}
    initial = {
        "user_input": text,
        "task_id": task_id,
        "max_reflow_count": 2,
        "metadata": {"task_id": task_id, "metrics": {}},
    }

    started = time.perf_counter()
    result = graph.invoke(initial, config)
    rounds = 0
    while rounds < 4 and isinstance(result, dict) and result.get("__interrupt__"):
        kind = _interrupt_kind(result)
        resume = {"approved": True, "feedback": ""} if kind == "approval" else ""
        result = graph.invoke(Command(resume=resume), config)
        rounds += 1
    duration = round(time.perf_counter() - started, 2)

    if not isinstance(result, dict):
        return {"case": name, "status": "error", "error": "graph returned no state"}

    metrics = ((result.get("metadata") or {}).get("metrics") or {})
    review = result.get("review_result") or {}
    coverage = coverage_report(result.get("prd_doc") or {}, result.get("technical_design") or {})
    design = result.get("technical_design") or {}

    return {
        "case": name,
        "task_id": task_id,
        "status": "interrupted" if result.get("__interrupt__") else "completed",
        "duration_seconds": duration,
        "latency_sum_of_nodes": sum(
            float(item.get("duration_seconds") or 0)
            for item in (metrics.get("node_latencies") or [])
        ),
        "llm_calls": int(metrics.get("llm_call_count") or 0),
        "review_passed": review.get("passed"),
        "overall_score": review.get("overall_score"),
        "rubric": {
            key: review.get(key)
            for key in (
                "completeness_score",
                "consistency_score",
                "feasibility_score",
                "testability_score",
                "security_score",
            )
        },
        "api_coverage": coverage["api"]["score"],
        "db_coverage": coverage["db"]["score"],
        "missing_api": coverage["api"]["missing"],
        "missing_db": coverage["db"]["missing"],
        "api_count": len(design.get("api_endpoints") or []),
        "table_count": len(((design.get("db_schema") or {}).get("tables") or [])),
        "reflow_count": result.get("reflow_count", 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="all", choices=[*CASES, "all"])
    args = parser.parse_args()

    settings = get_settings()
    if not settings.openai_api_key:
        print("OPENAI_API_KEY is empty; set it in .env before running the benchmark.")
        return 2

    names = list(CASES) if args.case == "all" else [args.case]
    graph = build_graph(MemorySaver())
    summaries = [run_case(graph, name, CASES[name]) for name in names]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = settings.output_dir / "benchmark"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"benchmark_{stamp}.json"
    out_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")

    for item in summaries:
        print(json.dumps(item, ensure_ascii=False))
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
