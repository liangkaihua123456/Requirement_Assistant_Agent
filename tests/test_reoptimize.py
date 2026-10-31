"""Review gating, cost recalculation, and the reoptimize entry."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

BJ = timezone(timedelta(hours=8))


def _prd():
    return {
        "feature_modules": [
            {
                "feature_id": "order_refund",
                "name": "订单退款",
                "description": "用户对已支付订单发起退款",
                "priority": "P0",
                "acceptance_criteria": ["提交后 24 小时内给出结果"],
            }
        ]
    }


def _design():
    return {
        "api_endpoints": [
            {
                "method": "POST",
                "path": "/orders/refund",
                "description": "发起退款",
                "related_feature_ids": ["order_refund"],
            }
        ],
        "db_schema": {
            "tables": [
                {
                    "table_name": "refund_records",
                    "description": "退款流水",
                    "columns": [{"name": "id"}],
                    "related_feature_ids": ["order_refund"],
                }
            ]
        },
    }


def test_rubric_gate_passes_even_when_model_said_failed():
    from app.agents.reviewer_agent import _apply_rule_based_adjustment

    review = {
        "overall_score": 7.6,
        "prd_score": 8.0,
        "tech_score": 8.0,
        "completeness_score": 8.0,
        "consistency_score": 7.5,
        "feasibility_score": 7.5,
        "testability_score": 7.5,
        "security_score": 7.0,
        "issues": [],
        "suggestions": [],
        "passed": False,
    }

    result = _apply_rule_based_adjustment(review, _prd(), _design())

    assert result["passed"] is True
    assert result["llm_passed"] is False
    assert result["overall_score"] >= 7.0


def test_high_severity_issue_blocks_pass_and_routes_to_engineer():
    from app.agents.reviewer_agent import _apply_rule_based_adjustment

    review = {
        "overall_score": 7.6,
        "prd_score": 8.0,
        "tech_score": 7.0,
        "completeness_score": 8.0,
        "consistency_score": 7.5,
        "feasibility_score": 7.5,
        "testability_score": 7.5,
        "security_score": 7.0,
        "issues": [
            {
                "category": "completeness",
                "severity": "high",
                "description": "订单状态枚举不一致",
                "suggestion": "统一为 paid/pending",
                "target": "engineer",
            }
        ],
        "suggestions": [],
        "passed": True,
        "reflow_target": "none",
    }

    result = _apply_rule_based_adjustment(review, _prd(), _design())

    assert result["passed"] is False
    assert str(result["reflow_target"]).lower().endswith("engineer")


def test_rubric_gate_still_blocks_low_score():
    from app.agents.reviewer_agent import _apply_rule_based_adjustment

    review = {
        "overall_score": 5.0,
        "prd_score": 5.0,
        "tech_score": 5.0,
        "completeness_score": 5.0,
        "consistency_score": 5.0,
        "feasibility_score": 5.0,
        "testability_score": 5.0,
        "security_score": 5.0,
        "issues": [],
        "suggestions": [],
        "passed": False,
    }

    result = _apply_rule_based_adjustment(review, _prd(), _design())

    assert result["passed"] is False


def test_recalculate_usage_uses_current_prices(monkeypatch):
    from app.core.config import DEFAULT_MODEL_PRICING
    from app.tools.cost_recalc import recalculate_usage

    monkeypatch.setattr("app.core.usage.get_pricing", lambda: DEFAULT_MODEL_PRICING)

    usage = {
        "total": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cached_tokens": 20,
            "calls": 2,
        },
        "by_model": {
            "deepseek-flash": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "cached_tokens": 20,
                "calls": 2,
                "cost_cny": 999,
            }
        },
        "by_role": {
            "engineer": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "cached_tokens": 20,
                "calls": 2,
                "cost_cny": 999,
            }
        },
        "cost_cny": 999,
        "priced": True,
    }

    result = recalculate_usage(usage, at=datetime(2026, 10, 23, 10, 0, tzinfo=BJ))

    assert result is not None
    # 高峰价：(80*2 + 20*0.04 + 50*8) / 1e6
    assert result["cost_cny"] == 0.000561
    assert result["by_model"]["deepseek-flash"]["cost_cny"] == 0.000561
    assert result["by_role"]["engineer"]["cost_cny"] == 0.000561
    assert result["total"]["total_tokens"] == 150


def test_route_entry_sends_reoptimize_to_engineer():
    from app.graph.router import route_entry

    assert route_entry({"prd_doc": _prd(), "metadata": {"reoptimize": True}}) == "engineer"
    assert route_entry({"prd_doc": _prd(), "metadata": {}}) == "input_normalize"


def test_route_entry_without_prd_falls_back_to_normalize():
    from app.graph.router import route_entry

    assert route_entry({"metadata": {"reoptimize": True}}) == "input_normalize"


def test_route_entry_repairs_when_design_present():
    from app.graph.router import route_entry

    state = {
        "prd_doc": _prd(),
        "technical_design": _design(),
        "metadata": {"reoptimize": True, "reoptimize_mode": "repair"},
    }

    assert route_entry(state) == "repairer"


def test_route_entry_rebuild_mode_goes_to_engineer():
    from app.graph.router import route_entry

    state = {
        "prd_doc": _prd(),
        "technical_design": _design(),
        "metadata": {"reoptimize": True, "reoptimize_mode": "rebuild"},
    }

    assert route_entry(state) == "engineer"


def test_rejection_routes_to_repairer_when_design_exists():
    from app.graph.router import route_after_human_approval

    assert (
        route_after_human_approval({"human_approved": False, "technical_design": _design()})
        == "repairer"
    )
    assert route_after_human_approval({"human_approved": False}) == "solution"
    assert route_after_human_approval({"human_approved": True}) == "package_output"


def test_merge_carries_unresolved_history_issues():
    from app.agents.reviewer_agent import _merge_previous_issues

    previous = [
        {"description": "订单状态枚举不一致", "severity": "high", "target": "engineer"},
        {"description": "缺少退款接口", "severity": "high", "target": "engineer"},
    ]
    reviews = [
        {"description": "订单状态枚举不一致", "resolved": True},
        {"description": "缺少退款接口", "resolved": False},
    ]

    merged = _merge_previous_issues(previous, [], reviews)

    assert len(merged) == 1
    assert merged[0]["description"] == "缺少退款接口"


def test_merge_skips_when_model_did_not_review():
    from app.agents.reviewer_agent import _merge_previous_issues

    previous = [{"description": "旧问题", "severity": "high"}]

    assert _merge_previous_issues(previous, [], []) == []


def test_low_prd_tech_coverage_does_not_cap_score():
    from app.agents.reviewer_agent import _apply_rule_based_adjustment

    prd = {
        "feature_modules": [
            {
                "feature_id": "order_refund",
                "name": "订单退款",
                "description": "用户对已支付订单发起退款",
                "acceptance_criteria": ["提交后 24 小时内给出结果"],
            }
        ]
    }
    design = {
        "api_endpoints": [
            {
                "method": "POST",
                "path": "/orders/refund",
                "description": "endpoint",
                "related_feature_ids": ["order_refund"],
            }
        ],
        "db_schema": {
            "tables": [
                {
                    "table_name": "refund_records",
                    "description": "table",
                    "columns": [],
                    "related_feature_ids": ["order_refund"],
                }
            ]
        },
    }
    review = {
        "overall_score": 7.0,
        "prd_score": 8.5,
        "tech_score": 8.4,
        "completeness_score": 9.8,
        "consistency_score": 8.5,
        "feasibility_score": 8.0,
        "testability_score": 8.0,
        "security_score": 8.0,
        "issues": [
            {
                "category": "一致性",
                "severity": "medium",
                "description": "术语轻微不一致",
                "suggestion": "统一术语",
                "target": "engineer",
            }
        ],
        "suggestions": [],
        "passed": True,
    }

    result = _apply_rule_based_adjustment(review, prd, design)

    # Weighted rubric is 8.66; low PRD-Tech text coverage must not clamp it to 7.0.
    assert result["overall_score"] == 8.66
    assert result["passed"] is True


def test_merge_marks_carried_origin():
    from app.agents.reviewer_agent import _merge_previous_issues

    previous = [{"description": "旧问题A", "severity": "high"}]
    reviews = [{"description": "旧问题A", "resolved": False}]

    merged = _merge_previous_issues(previous, [{"description": "新问题B", "severity": "low"}], reviews)

    origins = {item["description"]: item.get("origin") for item in merged}
    assert origins["旧问题A"] == "carried"
    assert origins["新问题B"] == "new"


def test_should_repair_uses_count_budget(monkeypatch):
    from app.core.config import get_settings
    from app.graph import router

    monkeypatch.setattr(get_settings(), "repairer_enabled", True)

    assert router._should_repair({"repair_count": 0}) is True
    assert router._should_repair({"repair_count": 1}) is True
    assert router._should_repair({"repair_count": 2}) is False
    assert router._should_repair({"repair_attempted": True}) is True


def test_rejection_restores_reflow_budget(monkeypatch):
    from app.agents import orchestrator_agent

    monkeypatch.setattr(
        orchestrator_agent,
        "interrupt",
        lambda payload: {"approved": False, "feedback": "方案需要调整"},
    )

    result = orchestrator_agent.human_approval_node(
        {
            "reflow_count": 2,
            "repair_attempted": True,
            "review_result": {},
            "prd_doc": {},
            "technical_design": {},
        }
    )

    assert result["human_approved"] is False
    assert result["reflow_count"] == 0
    assert result["repair_attempted"] is False


def test_approval_keeps_reflow_budget(monkeypatch):
    from app.agents import orchestrator_agent

    monkeypatch.setattr(orchestrator_agent, "interrupt", lambda payload: {"approved": True, "feedback": ""})

    result = orchestrator_agent.human_approval_node(
        {"reflow_count": 2, "repair_attempted": True, "review_result": {}}
    )

    assert result["human_approved"] is True
    assert "reflow_count" not in result
