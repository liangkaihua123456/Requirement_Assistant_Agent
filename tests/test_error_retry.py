"""Error classification and retry routing."""

from __future__ import annotations


def _prd():
    return {"feature_modules": [{"name": "订单退款", "feature_id": "order_refund"}]}


def _design():
    return {"api_endpoints": [{"method": "POST", "path": "/refund"}], "db_schema": {"tables": []}}


def test_classify_billing_error():
    from app.core.errors import classify_error

    class BillingError(Exception):
        status_code = 402

    info = classify_error(BillingError("Error code: 402 - Insufficient Balance"))

    assert info.kind == "billing"
    assert "充值" in info.action


def test_classify_auth_error():
    from app.core.errors import classify_error

    class AuthError(Exception):
        status_code = 401

    assert classify_error(AuthError("Unauthorized")).kind == "auth"


def test_classify_rate_limit_and_timeout():
    from app.core.errors import classify_error

    class Limited(Exception):
        status_code = 429

    assert classify_error(Limited("rate limit")).kind == "rate_limit"
    assert classify_error(RuntimeError("Read timed out")).kind == "timeout"


def test_classify_unknown_falls_back():
    from app.core.errors import classify_error

    info = classify_error(RuntimeError("boom"))

    assert info.kind == "unknown"
    assert "重试" in info.action


def test_retry_reviewer_resumes_at_reviewer():
    from app.graph.router import route_entry

    state = {
        "prd_doc": _prd(),
        "technical_design": _design(),
        "metadata": {"retry": True, "failed_node": "reviewer"},
    }

    assert route_entry(state) == "reviewer"


def test_retry_engineer_without_design_starts_engineer():
    from app.graph.router import route_entry

    state = {"prd_doc": _prd(), "metadata": {"retry": True, "failed_node": "engineer"}}

    assert route_entry(state) == "engineer"


def test_retry_repairer_uses_existing_design():
    from app.graph.router import route_entry

    state = {
        "prd_doc": _prd(),
        "technical_design": _design(),
        "metadata": {"retry": True, "failed_node": "repairer"},
    }

    assert route_entry(state) == "repairer"


def test_retry_planner_restarts_from_normalize():
    from app.graph.router import route_entry

    state = {"metadata": {"retry": True, "failed_node": "planner"}}

    assert route_entry(state) == "input_normalize"
