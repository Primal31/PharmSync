from datetime import date

from app.routes.analytics import _ai_insights, _deterministic_insights, _intent, _period


def test_controlled_question_intents_never_produce_sql():
    assert _intent("Which medicines are at highest expiry risk?") == "expiry_risk"
    assert _intent("Which pharmacies need restocking?") == "restock"
    assert _intent("How many units were redistributed this month?") == "redistribution"
    assert _intent("show charity fallback inventory") == "charity"
    assert _intent("DROP TABLE medicine_batches") == "summary"


def test_time_filter_presets_and_custom_range():
    start, end = _period("7d", None, None)
    assert (end - start).days == 6
    assert _period("custom", date(2026, 1, 1), date(2026, 1, 3)) == (date(2026, 1, 1), date(2026, 1, 3))


def test_deterministic_insight_is_metric_grounded():
    data = {
        "summary": {"restock_alerts": 1, "redistribution_opportunities": 0},
        "restock": {"count": 1, "threshold_days": 15, "rows": [{"medicine_name": "Actual Batch Medicine", "pharmacy_name": "Actual Pharmacy", "estimated_days_of_stock": 8}]},
        "expiry_risk": {"rows": []},
    }
    insight = _deterministic_insights(data)[0]
    assert "Actual Batch Medicine" in insight["recommended_action"]
    assert "8.0 days" in insight["recommended_action"]


def test_unconfigured_ai_provider_uses_deterministic_fallback(monkeypatch):
    from app.routes import analytics
    monkeypatch.setattr(analytics.settings, "ai_provider", "none")
    fallback = [{"type": "NETWORK", "observation": "real metric", "why_it_matters": "reason", "recommended_action": "review"}]
    result = _ai_insights({"summary": {"real": 3}}, fallback)
    assert result["fallback"] is True
    assert result["insights"] == fallback
