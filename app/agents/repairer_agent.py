"""Repairer Agent —— 定向修复。

两种模式：

* 有评审问题或驳回意见时，基于现有设计逐条修订，不重写无关部分。
* 否则退回覆盖缺口修补，只补缺失的 API 与表。

与 Engineer 全量重生成不同，Repairer 始终在已有设计上工作，避免"修了 A 坏了 B"。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.logger import logger
from app.graph.state import AgentState
from app.memory.short_term import add_entry
from app.tools.coverage_metrics import missing_feature_mappings
from app.tools.design_patch import patch_design_gaps, refine_design


def repairer_node(state: AgentState) -> dict:
    """Repairer 节点：优先按评审问题定向修订，其次补覆盖缺口。"""
    logger.info("Repairer Agent 开始执行", extra={"node": "repairer"})

    prd_doc = state.get("prd_doc", {})
    design = state.get("technical_design", {})
    review = state.get("review_result") or {}
    human_feedback = state.get("human_feedback", "")

    issues = [item for item in (review.get("issues") or []) if item.get("target") == "engineer"]
    repair_count = int(state.get("repair_count") or 0)

    if issues or human_feedback.strip():
        refined, stats = refine_design(prd_doc, design, issues, human_feedback)
        api_delta = len(refined.get("api_endpoints") or []) - len(design.get("api_endpoints") or [])
        table_delta = len((refined.get("db_schema") or {}).get("tables") or []) - len(
            (design.get("db_schema") or {}).get("tables") or []
        )
        logger.info(
            "Repairer refined design",
            extra={"node": "repairer", "issues": len(issues), "api_delta": api_delta},
        )
        task_mem = add_entry(
            state,
            "repairer",
            summary=f"按 {len(issues)} 条评审问题定向修订设计",
            key_decisions=[
                f"驳回意见：{human_feedback[:80]}" if human_feedback else "",
                f"修复目标：{'；'.join(str(i.get('description', ''))[:40] for i in issues[:3])}",
            ],
            metrics={"issues": len(issues), "api_delta": api_delta, "table_delta": table_delta},
            warnings=[stats["error"]] if stats.get("error") else [],
        )
        return {
            "technical_design": refined,
            "repair_attempted": True,
            "repair_count": repair_count + 1,
            "current_node": "repairer",
            **task_mem,
            "execution_logs": [
                {
                    "node": "repairer",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": "refined",
                    "issues": len(issues),
                    "api_delta": api_delta,
                    "table_delta": table_delta,
                }
            ],
        }

    missing = missing_feature_mappings(prd_doc, design)
    if not missing["api"] and not missing["db"]:
        logger.info("Repairer: 无覆盖缺口与评审问题，跳过修复")
        return {
            "repair_attempted": True,
            "repair_count": repair_count + 1,
            "current_node": "repairer",
            "execution_logs": [
                {
                    "node": "repairer",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "action": "no_gaps_found",
                }
            ],
        }

    extra_hints = ""
    for issue in review.get("issues") or []:
        if issue.get("target") == "engineer":
            extra_hints += f"- [{issue.get('severity', '?')}] {issue.get('description', '')}: {issue.get('suggestion', '')}\n"

    patched, stats = patch_design_gaps(prd_doc, design, missing, extra_hints=extra_hints)
    new_api = int(stats.get("api") or 0)
    new_tables = int(stats.get("db") or 0)

    logger.info(
        "Repairer Agent 执行完成",
        extra={"node": "repairer", "new_api": new_api, "new_tables": new_tables},
    )

    task_mem = add_entry(
        state,
        "repairer",
        summary=f"精准修补：新增 {new_api} 个 API、{new_tables} 张 DB 表",
        key_decisions=[
            f"缺失 API: {', '.join(missing['api'][:5])}",
            f"缺失 DB: {', '.join(missing['db'][:5])}",
        ],
        metrics={"new_api": new_api, "new_tables": new_tables},
        warnings=[stats["error"]] if stats.get("error") else [],
    )

    return {
        "technical_design": patched,
        "repair_attempted": True,
        "repair_count": repair_count + 1,
        "current_node": "repairer",
        **task_mem,
        "execution_logs": [
            {
                "node": "repairer",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": "repaired" if new_api or new_tables else "patch_empty",
                "new_api_endpoints": new_api,
                "new_db_tables": new_tables,
            }
        ],
    }
