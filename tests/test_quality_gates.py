"""Regression tests for the quality work (batch B).

The key contract: traceability is graded, missing coverage is reported rather
than fabricated, and the review gate is computed from a fixed rubric instead of
a free-form model total.
"""

from __future__ import annotations

from app.agents.reviewer_agent import _apply_rule_based_adjustment, _weighted_overall
from app.tools import coverage_metrics
from app.tools.coverage_metrics import coverage_report, report_coverage_gaps
from app.tools.design_patch import merge_patch
from app.tools.prd_patch import audit_prd, with_feature_ids


def _prd(*features: dict) -> dict:
    return {"feature_modules": list(features)}


def _feature(name: str = "订单退款", feature_id: str = "order_refund") -> dict:
    return {
        "feature_id": feature_id,
        "name": name,
        "description": "用户对已支付订单发起退款",
        "priority": "P0",
        "sub_features": ["退款申请", "退款审核"],
        "acceptance_criteria": ["提交退款后 24 小时内给出审核结果"],
    }


def test_coverage_uses_feature_id_when_present():
    design = {
        "api_endpoints": [
            {"method": "POST", "path": "/orders/refund", "related_feature_ids": ["order_refund"]}
        ]
    }
    assert coverage_report(_prd(_feature()), design)["api"]["score"] == 1.0


def test_coverage_falls_back_to_name_then_text():
    by_name = {"api_endpoints": [{"method": "POST", "path": "/orders/refund", "related_features": ["订单退款"]}]}
    assert coverage_report(_prd(_feature()), by_name)["api"]["score"] == 0.8

    by_text = {"api_endpoints": [{"method": "POST", "path": "/orders/refund", "description": "订单退款接口"}]}
    assert coverage_report(_prd(_feature()), by_text)["api"]["score"] == 0.5


def test_coverage_missing_feature_is_reported_not_filled():
    prd = _prd(_feature())
    design = {"api_endpoints": [], "db_schema": {"tables": []}}

    gaps = report_coverage_gaps(prd, design)

    assert gaps["api"] == ["订单退款"]
    assert gaps["db"] == ["订单退款"]
    assert design["api_endpoints"] == []
    assert design["db_schema"]["tables"] == []
    assert not hasattr(coverage_metrics, "repair_feature_mappings")


def test_merge_patch_skips_duplicate_paths_and_tables():
    design = {
        "api_endpoints": [{"method": "POST", "path": "/orders/refund"}],
        "db_schema": {"tables": [{"table_name": "refund_records"}], "relationships": []},
    }
    patch = {
        "api_endpoints": [
            {"method": "POST", "path": "/orders/refund"},
            {"method": "GET", "path": "/orders/refund/status"},
        ],
        "db_tables": [
            {"table_name": "refund_records"},
            {"table_name": "refund_audit_logs"},
        ],
    }

    merged, stats = merge_patch(design, patch)

    assert stats == {"api": 1, "db": 1}
    assert len(merged["api_endpoints"]) == 2
    assert len(merged["db_schema"]["tables"]) == 2


def test_with_feature_ids_is_stable_and_unique():
    prd = {
        "feature_modules": [
            {"name": "Order Refund"},
            {"name": "Order Refund"},
            {"name": "库存", "feature_id": "inventory"},
        ]
    }
    normalized = with_feature_ids(prd)
    ids = [item["feature_id"] for item in normalized["feature_modules"]]
    assert ids[0] == "order_refund"
    assert ids[1] != ids[0]
    assert ids[2] == "inventory"


def test_audit_prd_flags_missing_sections():
    gaps = audit_prd({"feature_modules": [{"name": "A", "acceptance_criteria": []}]})
    joined = " ".join(gaps)
    assert "验收标准" in joined
    assert "用户流程" in joined
    assert "非功能性需求" in joined


def test_rubric_weighted_score_matches_weights():
    review = {
        "completeness_score": 10,
        "consistency_score": 8,
        "feasibility_score": 6,
        "testability_score": 4,
        "security_score": 2,
    }
    assert _weighted_overall(review) == 7.0
    assert _weighted_overall({"completeness_score": 0}) is None


def test_review_gate_blocks_severe_coverage_gap():
    review = {
        "overall_score": 9.0,
        "prd_score": 9.0,
        "tech_score": 9.0,
        "completeness_score": 9.0,
        "consistency_score": 9.0,
        "feasibility_score": 9.0,
        "testability_score": 9.0,
        "security_score": 9.0,
        "issues": [],
        "suggestions": [],
        "passed": True,
    }
    result = _apply_rule_based_adjustment(review, _prd(_feature()), {"api_endpoints": [], "db_schema": {}})

    assert result["passed"] is False
    assert str(result["reflow_target"]) in {"engineer", "ReviewTargetType.ENGINEER"}
    assert result["overall_score"] <= 6.5
    assert result["llm_overall_score"] == 9.0


def test_design_patch_failure_keeps_original_design(monkeypatch):
    from app.tools import design_patch

    def _boom(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(design_patch, "get_structured_llm", _boom)
    design = {"api_endpoints": [], "db_schema": {"tables": []}}

    patched, stats = design_patch.patch_design_gaps(
        _prd(_feature()), design, {"api": ["订单退款"], "db": []}
    )

    assert patched == design
    assert stats["error"]


def test_prd_patch_failure_keeps_original_prd(monkeypatch):
    from app.tools import prd_patch

    def _boom(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(prd_patch, "get_structured_llm", _boom)
    prd = {
        "feature_modules": [{"name": "Order Refund"}],
        "user_stories": [],
        "user_flows": [],
        "non_functional_requirements": [],
    }

    merged, audit = prd_patch.ensure_prd_quality(prd, {})

    assert audit["patched"] is False
    assert merged["feature_modules"][0]["feature_id"] == "order_refund"
    assert merged["user_flows"] == []


def test_traceability_matrix_reports_matches_and_gaps():
    from app.tools.traceability import build_traceability

    design = {
        "services": [{"name": "OrderService", "responsibility": "处理订单退款"}],
        "api_endpoints": [
            {
                "method": "post",
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
                    "columns": [{"name": "id", "type": "uuid"}],
                    "related_feature_ids": ["order_refund"],
                }
            ]
        },
    }

    result = build_traceability(_prd(_feature()), design)
    row = result["features"][0]

    assert row["api"]["weight"] == 1.0
    assert row["api"]["items"][0]["method"] == "POST"
    assert row["db"]["weight"] == 1.0
    assert row["db"]["items"][0]["column_count"] == 1
    assert row["service"]["items"][0]["name"] == "OrderService"
    assert row["acceptance_criteria"]
    assert result["summary"]["api_score"] == 1.0


def test_traceability_marks_missing_feature():
    from app.tools.traceability import build_traceability

    result = build_traceability(_prd(_feature()), {"api_endpoints": [], "db_schema": {"tables": []}})
    row = result["features"][0]

    assert row["api"]["weight"] == 0.0
    assert row["api"]["items"] == []
    assert row["db"]["weight"] == 0.0
    assert result["summary"]["missing_api"] == ["订单退款"]
    assert result["summary"]["missing_db"] == ["订单退款"]


def _clarified(**overrides):
    from app.schemas.requirement import ClarifiedRequirement

    payload = {
        "goal": "为门店提供点单能力",
        "core_features": ["扫码点单", "在线支付", "接单", "改库存"],
        "open_questions": ["问题1", "问题2", "问题3", "问题4"],
        "assumptions": [],
    }
    payload.update(overrides)
    return ClarifiedRequirement(**payload)


def test_clarification_skipped_for_detailed_brief():
    from app.agents.planner_agent import _resolve_clarification_need

    result = _clarified()
    assert result.needs_clarification is True
    assert _resolve_clarification_need(result, "结构化需求" * 20, already_confirmed=False) is False


def test_clarification_kept_for_short_brief():
    from app.agents.planner_agent import _resolve_clarification_need

    assert _resolve_clarification_need(_clarified(), "做个点单", already_confirmed=False) is True


def test_clarification_kept_when_goal_or_features_missing():
    from app.agents.planner_agent import _resolve_clarification_need

    long_text = "结构化需求" * 20
    assert _resolve_clarification_need(_clarified(goal=""), long_text, already_confirmed=False) is True
    assert (
        _resolve_clarification_need(_clarified(core_features=["扫码点单"]), long_text, already_confirmed=False)
        is True
    )


def test_clarification_never_repeats_after_confirmation():
    from app.agents.planner_agent import _resolve_clarification_need

    assert _resolve_clarification_need(_clarified(), "短", already_confirmed=True) is False


def test_design_schema_coerces_model_deviations():
    from app.schemas.design import TechnicalDesign

    design = TechnicalDesign.model_validate(
        {
            "architecture_overview": "单体应用",
            "services": [{"name": "api", "responsibility": "提供接口", "tech_stack": "fastapi"}],
            "db_schema": {
                "relationships": "用户一对多账目",
                "tables": [
                    {
                        "table_name": "expenses",
                        "description": "支出记录",
                        "columns": ["id", "amount"],
                        "indexes": "idx_expenses_created_at",
                        "related_features": "支出记录",
                        "related_feature_ids": "expense_record",
                    }
                ],
            },
            "api_endpoints": [
                {
                    "method": "POST",
                    "path": "/expenses",
                    "description": "新增支出",
                    "related_features": "支出记录",
                    "related_feature_ids": "expense_record",
                }
            ],
            "code_scaffold": {
                "dependencies": [{"name": "react", "version": "18"}],
                "key_files": ["src/App.tsx"],
            },
        }
    )

    assert design.services[0].tech_stack == ["fastapi"]
    assert design.db_schema.relationships == ["用户一对多账目"]
    assert design.db_schema.tables[0].columns[0]["name"] == "id"
    assert design.db_schema.tables[0].indexes == ["idx_expenses_created_at"]
    assert design.api_endpoints[0].related_feature_ids == ["expense_record"]
    assert design.code_scaffold.dependencies == ["react 18"]
    assert design.code_scaffold.key_files[0]["path"] == "src/App.tsx"
