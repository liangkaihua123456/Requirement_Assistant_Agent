"""Round 1 P0 changes: engineer fallback, stats and paging endpoints."""

from __future__ import annotations


def _prd():
    return {
        "feature_modules": [
            {"feature_id": "order_refund", "name": "订单退款"},
            {"feature_id": "cart_order", "name": "购物车"},
        ]
    }


def test_fallback_design_matches_schema():
    from app.agents.engineer_agent import _fallback_design
    from app.schemas.design import TechnicalDesign

    design = _fallback_design(_prd())
    validated = TechnicalDesign.model_validate(design)

    assert len(validated.api_endpoints) == 2
    assert len(validated.db_schema.tables) == 2
    assert all(endpoint.related_feature_ids for endpoint in validated.api_endpoints)
    assert all(table.related_feature_ids for table in validated.db_schema.tables)


def test_fallback_design_handles_empty_prd():
    from app.agents.engineer_agent import _fallback_design
    from app.schemas.design import TechnicalDesign

    validated = TechnicalDesign.model_validate(_fallback_design({}))

    assert validated.api_endpoints
    assert validated.db_schema.tables
    assert validated.tech_risks


def test_stats_route_registered_before_task_id():
    from app.main import app

    paths = [route.path for route in app.routes]

    assert "/tasks/stats" in paths
    assert "/tasks/page" in paths
    assert paths.index("/tasks/stats") < paths.index("/tasks/{task_id}")
    assert paths.index("/tasks/page") < paths.index("/tasks/{task_id}")
