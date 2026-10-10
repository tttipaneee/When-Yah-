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


def test_malaysian_events_never_get_a_number():
    body = {**BODY, "datetime": "2026-10-11T21:00:00+08:00", "pickup": {"lat": 3.1394413, "lon": 101.7091281}}
    d = client.post("/api/forecast", json=body).json()
    assert d["events"] and all(e["learned_effect"] is None for e in d["events"])


def test_wait_odds_headline():
    d = client.post("/api/forecast", json={**BODY, "usual_price_rm": 25.0}).json()
    o = d["wait_odds"]
    h30 = next(h for h in d["horizon"] if h["minutes"] == 30)
    assert o["minutes"] == 30 and o["p_save10"] == h30["p_drop10"]
    assert 0 < o["typical_p_save10"] < 1 and set(o["rm_range"]) == {"grab", "indrive"}
    assert o["rm_range"]["grab"][0] <= o["rm_range"]["grab"][1]
    assert d["reasons"][0].startswith("Chance that waiting 30 min saves you 10% or more")
    d = client.post("/api/forecast", json={**BODY, "quotes": []}).json()
    assert d["wait_odds"]["rm_range"] == {}


def test_demo_scenarios_run_real_forecast():
    r = client.get("/api/demo")
    assert r.status_code == 200
    d = r.json()
    assert len(d) == 4 and all(s["label"].startswith("example") for s in d)
    for s in d:
        assert s["response"]["model_version"].startswith("lgbm_v1/")
        assert set(s["response"]["wait_odds"]["rm_range"]) == {q["app"] for q in s["request"]["quotes"]}
    near = {s["id"]: [e["name"] for e in s["response"]["events"]] for s in d}
    assert any("MAMAMOO" in n for n in near["mamamoo"]) and any("Eunji" in n for n in near["eunji_rain"])


def test_time_is_read_in_kl_whatever_timezone_was_sent():
    kl = client.post("/api/forecast", json={**BODY, "datetime": "2026-10-10T15:22:00+08:00", "usual_price_rm": 20}).json()
    utc = client.post("/api/forecast", json={**BODY, "datetime": "2026-10-10T07:22:00Z", "usual_price_rm": 20}).json()
    assert kl["wait_odds"] == utc["wait_odds"]
    assert utc["datetime"].endswith("+08:00")


def test_usual_price_estimate_only_when_fare_check_passed():
    from api.fare import check
    body = {**BODY, "pickup": {"lat": 3.158, "lon": 101.7117}, "dropoff": {"lat": 3.1177, "lon": 101.6774}}
    d = client.post("/api/forecast", json=body).json()
    if not check().get("passed"):
        assert d["usual_price_estimate"] is None and d["model_version"] == "lgbm_v1/no_level"


def test_metrics_structured_for_judges_screen():
    d = client.get("/api/metrics").json()
    assert d["structured"]["calibration_with_level_30"]
    assert all(v["validated"] in (True, False) for v in d["decision"]["variants"].values())
    assert "trend_experiment" in d["experiments"]


def test_tunggu_only_when_rule_validated_and_odds_high():
    from api.forecast import decision_rule
    jam = {**BODY, "datetime": "2026-10-16T18:10:00+08:00", "quotes": [{"app": "grab", "price_rm": 40.0}],
           "usual_price_rm": 20.0}
    d = client.post("/api/forecast", json=jam).json()
    gate = decision_rule().get("variants", {}).get("with_level", {})
    if d["decision"] == "wait":
        assert gate.get("validated") and d["wait_minutes"] in (15, 30, 45, 60)
        assert set(d["expected_saving_rm"]) == {"grab"} and any(r.startswith("Wait ") for r in d["reasons"])
    quiet = {**BODY, "datetime": "2026-10-13T14:00:00+08:00", "quotes": [{"app": "grab", "price_rm": 12.0}],
             "usual_price_rm": 15.0}
    assert client.post("/api/forecast", json=quiet).json()["decision"] == "book_now"


def test_traffic_jam_flips_tunggu_and_warns():
    jam = {**BODY, "datetime": "2026-10-16T18:10:00+08:00", "quotes": [{"app": "grab", "price_rm": 40.0}],
           "usual_price_rm": 20.0}
    base = client.post("/api/forecast", json=jam).json()
    if base["decision"] == "wait":
        h = base["wait_minutes"]
        d = client.post("/api/forecast", json={**jam, "traffic_min": {"0": 20, str(h): 32}}).json()
        assert d["decision"] == "book_now" and d["traffic"]["flipped_to_book_now"]
        assert any(r.startswith("Book now — jam coming") for r in d["reasons"])
        assert not any(r.startswith("Wait ") for r in d["reasons"])
        clear = client.post("/api/forecast", json={**jam, "traffic_min": {"0": 20, str(h): 18}}).json()
        assert clear["decision"] == "wait" and not clear["traffic"]["jam_ahead"]
    quiet = {**BODY, "datetime": "2026-10-12T17:00:00+08:00", "quotes": [{"app": "grab", "price_rm": 22.0}],
             "usual_price_rm": 20.0, "traffic_min": {"0": 18, "15": 20, "30": 26, "45": 30, "60": 34}}
    d = client.post("/api/forecast", json=quiet).json()
    assert d["traffic"]["jam_ahead"] and any(r.startswith("Traffic predicted to build") for r in d["reasons"])
    assert client.post("/api/forecast", json=BODY).json()["traffic"] is None


def test_tomtom_traffic_used_when_pickup_and_dropoff(monkeypatch):
    import api.forecast as f
    monkeypatch.setattr(f, "predicted_minutes", lambda a, b, t: {0: 18.0, 15: 21.0, 30: 27.0, 45: 30.0, 60: 33.0})
    body = {**BODY, "datetime": "2026-10-12T17:00:00+08:00", "pickup": {"lat": 3.158, "lon": 101.7117},
            "dropoff": {"lat": 3.1177, "lon": 101.6774}, "quotes": [{"app": "grab", "price_rm": 22.0}],
            "usual_price_rm": 20.0}
    d = client.post("/api/forecast", json=body).json()
    assert d["traffic"]["source"] == "TomTom traffic prediction" and d["traffic"]["jam_ahead"]
    assert any("TomTom traffic prediction" in r for r in d["reasons"])


def test_no_tomtom_key_means_no_traffic(monkeypatch):
    import api.traffic as tr
    from api.traffic import predicted_minutes
    monkeypatch.delenv("TOMTOM_API_KEY", raising=False)
    monkeypatch.setattr(tr, "_ENV", "/nonexistent/.env")
    assert predicted_minutes((3.158, 101.7117), (3.1177, 101.6774), __import__("datetime").datetime.now()) is None


def test_event_levels_right_here_and_in_area():
    sat = {**BODY, "datetime": "2026-10-10T19:30:00+08:00"}
    here = client.post("/api/forecast", json={**sat, "pickup": {"lat": 3.0537311, "lon": 101.6934618}}).json()
    e = next(x for x in here["events"] if "MAMAMOO" in x["name"])
    assert e["level"] == "right_here" and e["km"] <= 1.0
    area = client.post("/api/forecast", json={**sat, "pickup": {"lat": 3.0763304, "lon": 101.7111343}}).json()
    e = next(x for x in area["events"] if "MAMAMOO" in x["name"])  # Bandar Tasik Selatan, ~3 km away
    assert e["level"] == "in_area" and 1.0 < e["km"] <= 5.0


def test_grab_per_minute_note_when_trip_gets_longer(monkeypatch):
    import api.forecast as f
    monkeypatch.setattr(f, "predicted_minutes", lambda a, b, t: {0: 20.0, 15: 21.0, 30: 23.0, 45: 24.0, 60: 24.0})
    body = {**BODY, "datetime": "2026-10-12T17:00:00+08:00", "pickup": {"lat": 3.158, "lon": 101.7117},
            "dropoff": {"lat": 3.1177, "lon": 101.6774}, "quotes": [{"app": "grab", "price_rm": 15.0}],
            "usual_price_rm": 15.0}
    d = client.post("/api/forecast", json=body).json()
    assert any("per-minute charge" in r for r in d["reasons"])
    no_grab = {**body, "quotes": [{"app": "indrive", "price_rm": 15.0}]}
    assert not any("per-minute" in r for r in client.post("/api/forecast", json=no_grab).json()["reasons"])


def test_wait_never_shown_while_expected_price_rises():
    # sweep a day of times and prices: whenever the answer is "Wait", the expected price there is below now
    for hh in range(6, 24, 2):
        for price in (15.0, 25.0, 40.0):
            body = {**BODY, "datetime": f"2026-10-16T{hh:02d}:10:00+08:00",
                    "quotes": [{"app": "grab", "price_rm": price}], "usual_price_rm": 20.0}
            d = client.post("/api/forecast", json=body).json()
            if d["decision"] == "wait":
                h = next(x for x in d["horizon"] if x["minutes"] == d["wait_minutes"])
                assert h["pct_change"] < 0


def test_route_km_and_minutes_now_for_the_map(monkeypatch):
    import api.forecast as f
    monkeypatch.setattr(f, "predicted_minutes", lambda a, b, t: {0: 18.0, 15: 19.0, 30: 20.0, 45: 20.0, 60: 20.0})
    monkeypatch.setattr(f, "route_km_now", lambda a, b, t: 7.4)
    body = {**BODY, "pickup": {"lat": 3.158, "lon": 101.7117}, "dropoff": {"lat": 3.1177, "lon": 101.6774}}
    d = client.post("/api/forecast", json=body).json()
    assert d["traffic"]["km"] == 7.4 and d["traffic"]["minutes"]["0"] == 18.0


def test_event_exit_hint_in_words_only_near_end():
    from api.forecast import event_effect
    zepp = {"lat": 3.1394413, "lon": 101.7091281}  # Eunji concert ends 23:00 on 11 Oct (published end)
    near_end = client.post("/api/forecast", json={**BODY, "datetime": "2026-10-11T22:40:00+08:00", "pickup": zepp}).json()
    early = client.post("/api/forecast", json={**BODY, "datetime": "2026-10-11T20:30:00+08:00", "pickup": zepp}).json()
    hint = [r for r in near_end["reasons"] if r.startswith("Event ending right here")]
    assert not any(r.startswith("Event ending right here") for r in early["reasons"])
    if event_effect():
        assert hint and "book before 23:00" in hint[0]
        assert "%" not in hint[0] and "NYC" not in hint[0] and "New York" not in hint[0]


def test_case_studies_match_report():
    d = client.get("/api/case_studies").json()
    md = open("reports/case_studies.md", encoding="utf-8").read()
    e = d["event_exit"]
    assert f"actual **{e['heldout_0_45']:+.0%}** vs learned {e['learned_0_45']:+.0%}" in md
    assert f"peak **{e['peak']:+.0%}**" in md
    for r in d["surge_fallback"]:
        assert f"| {r['band']} | {r['n']:,} | {r['actual']['30']:+.1%} / {r['actual']['60']:+.1%} |" in md
