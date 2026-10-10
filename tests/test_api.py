from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)
BODY = {"datetime": "2026-10-10T18:10:00+08:00", "rain": False, "pickup": None,
        "quotes": [{"app": "grab", "price_rm": 38.0}, {"app": "indrive", "price_rm": 33.0}],
        "usual_price_rm": None}


def test_forecast_contract_shape():
    r = client.post("/api/forecast", json=BODY)
    assert r.status_code == 200
    d = r.json()
    assert [h["minutes"] for h in d["horizon"]] == [15, 30, 45, 60]
    assert d["decision"] in ("book_now", "wait")
    assert d["model_version"] == "lgbm_v1/no_level"
    assert set(d["horizon"][0]["expected_rm"]) == {"grab", "indrive"}
    assert set(d["apps_ranked_now"]) == {"grab", "indrive"}


def test_no_quotes_means_no_rm():
    d = client.post("/api/forecast", json={**BODY, "quotes": []}).json()
    assert all(h["expected_rm"] == {} for h in d["horizon"])
    assert d["expected_saving_rm"] == {} and d["apps_ranked_now"] == []


def test_unknown_app_rejected():
    r = client.post("/api/forecast", json={**BODY, "quotes": [{"app": "uber", "price_rm": 10}]})
    assert r.status_code == 422


def test_events_and_metrics():
    r = client.get("/api/events", params={"date": "2026-10-10"})
    assert r.status_code == 200 and isinstance(r.json(), list)
    assert client.get("/api/metrics").status_code == 200


def test_usual_price_uses_with_level_and_rm_only_from_quotes():
    d = client.post("/api/forecast", json={**BODY, "usual_price_rm": 25.0}).json()
    assert d["model_version"] == "lgbm_v1/with_level"
    for h in d["horizon"]:
        assert h["pct_low"] <= h["pct_change"] <= h["pct_high"]
        assert h["expected_rm"]["grab"] == round(38.0 * (1 + h["pct_change"]), 2)
    if d["decision"] == "wait":
        assert d["wait_minutes"] in (15, 30, 45, 60) and set(d["expected_saving_rm"]) == {"grab", "indrive"}


def test_events_have_no_learned_effect_unless_validated():
    d = client.post("/api/forecast", json=BODY).json()
    assert all(e["learned_effect"] is None for e in d["events"])
