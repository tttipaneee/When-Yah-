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
    assert d["model_version"].startswith("lgbm_v1/no_level")
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
    assert d["model_version"].startswith("lgbm_v1/with_level")
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


def test_rough_estimate_used_only_without_typed_usual_and_labelled(monkeypatch):
    import api.forecast as fc
    est = {"rm": 20.0, "km": 8.0, "min": 18, "source": "Grab published rates (Jan 2023) + OpenStreetMap route — rough",
           "validated": False, "median_abs_error": 0.371, "n_quotes": 9}
    monkeypatch.setattr(fc, "fare_estimate", lambda *a, **k: est)
    body = {**BODY, "pickup": {"lat": 3.158, "lon": 101.7117}, "dropoff": {"lat": 3.1177, "lon": 101.6774}}
    d = client.post("/api/forecast", json=body).json()
    assert d["model_version"].startswith("lgbm_v1/with_level") and d["usual_price_estimate"]["validated"] is False
    assert any(r.startswith("No usual price typed: using an estimated usual price of RM 20.00") and "37%" in r
               for r in d["reasons"])
    typed = client.post("/api/forecast", json={**body, "usual_price_rm": 30.0}).json()  # typed always wins
    assert not any(r.startswith("No usual price typed") for r in typed["reasons"])
    assert any("vs your usual price" in r for r in typed["reasons"])


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
        assert hint and "ends at 23:00" in hint[0] and "book before" not in hint[0]
        assert "%" not in hint[0] and "NYC" not in hint[0] and "New York" not in hint[0]


def test_case_studies_match_report():
    d = client.get("/api/case_studies").json()
    md = open("reports/case_studies.md", encoding="utf-8").read()
    e = d["event_exit"]
    assert f"actual **{e['heldout_0_45']:+.0%}** vs learned {e['learned_0_45']:+.0%}" in md
    assert f"peak **{e['peak']:+.0%}**" in md
    assert f"Training games: {e['train_games']}; held-out games: {e['heldout_games']}" in md
    assert "bin means: " + ", ".join(f"{int(b):+d}: {v:+.0%}" for b, v in e["learned_bins"].items()) + ")" in md
    assert f"learned curve **{e['error_learned']:.1%}** vs \"no event effect\" {e['error_no_effect']:.1%}" in md
    for r in d["surge_fallback"]:
        assert (f"| {r['band']} | {r['n']:,} | {r['actual']['30']:+.1%} / {r['actual']['60']:+.1%} | "
                f"{r['model']['30']:+.1%} / {r['model']['60']:+.1%} | {r['drop10_actual_30']:.0%} | "
                f"{r['drop10_model_30']:.0%} |") in md


def test_no_hundred_percent_drop_chance():
    # audit fix: a thin isotonic top step must not show "100% chance" (ml.train.drop_prob caps it)
    for s in client.get("/api/demo").json():
        assert all(h["p_drop10"] < 0.9 for h in s["response"]["horizon"])


def test_situation_and_urgency_follow_the_outputs():
    for hh in (8, 13, 18, 22):
        for usual in (None, 20.0):
            body = {**BODY, "datetime": f"2026-10-16T{hh:02d}:10:00+08:00",
                    "quotes": [{"app": "grab", "price_rm": 40.0}], "usual_price_rm": usual}
            d = client.post("/api/forecast", json=body).json()
            assert (d["urgency"] == "wait") == (d["decision"] == "wait")
            if usual is None:
                assert d["situation"] not in ("surge", "pricey")  # level unknown without a usual price
            elif d["situation"] != "event_exit" and d["situation"] != "jam_coming":
                assert d["situation"] == "surge"  # 40 / 20 = 2x usual
    jam = {**BODY, "quotes": [{"app": "grab", "price_rm": 15.0}], "usual_price_rm": 15.0,
           "traffic_min": {"0": 20, "15": 30, "30": 32}}
    d = client.post("/api/forecast", json=jam).json()
    assert d["situation"] == "jam_coming" and d["urgency"] in ("urgent",)
    zepp = {"lat": 3.1394413, "lon": 101.7091281}
    d = client.post("/api/forecast", json={**BODY, "datetime": "2026-10-11T22:40:00+08:00", "pickup": zepp}).json()
    from api.forecast import event_effect
    if event_effect():
        assert d["situation"] == "event_exit" and d["urgency"] in ("urgent", "wait")


def test_explain_rejects_invented_numbers_and_works_without_key(monkeypatch):
    import api.explain as ex
    from api.schemas import ForecastRequest
    req = ForecastRequest(**{**BODY, "quotes": [{"app": "grab", "price_rm": 30.0}], "usual_price_rm": 20.0})
    f = ex.facts(req)
    assert "Grab" in f["your_prices"] and f["your_prices"]["Grab"] == "RM30.00"
    lo_hi = f["likely_price_in_30_min"]["Grab"]
    assert ex.unsupported_numbers(f"Your Grab RM30.00 will likely be {lo_hi} in 30 min.", f) == []
    assert ex.unsupported_numbers("You could save RM7.77 if you wait.", f) == ["7.77"]
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(ex, "_ENV", "/nonexistent/.env")
    r = client.post("/api/explain", json={**BODY, "quotes": [{"app": "grab", "price_rm": 30.0}]}).json()
    assert r["ai"] is False and r["text"] is None


def test_walk_out_whenever_right_here_and_points_outside_the_circle():
    from api.events import haversine_km
    from api.forecast import WALK_OUT_KM
    zepp = {"lat": 3.1394413, "lon": 101.7091281}  # Eunji concert ends 23:00 on 11 Oct (published end)
    sentral = {"lat": 3.1325847, "lon": 101.6879963}
    near = {**BODY, "datetime": "2026-10-11T22:40:00+08:00", "pickup": zepp, "dropoff": sentral}
    early = client.post("/api/forecast", json={**near, "datetime": "2026-10-11T20:30:00+08:00"}).json()
    late = client.post("/api/forecast", json={**near, "datetime": "2026-10-11T23:50:00+08:00"}).json()
    assert early["walk_out"] and late["walk_out"]  # shown any time that day while the pickup is right here
    far = client.post("/api/forecast", json={**near, "pickup": sentral}).json()
    assert far["walk_out"] is None  # pickup outside the 1 km circle
    w = client.post("/api/forecast", json=near).json()["walk_out"]
    assert w and not w["ended"] and w["radius_km"] == 1.0
    t, c = w["target"], w["center"]
    assert abs(haversine_km(c["lat"], c["lon"], t["lat"], t["lon"]) - WALK_OUT_KM) < 0.01  # just past the circle
    # toward the drop-off: the walk-out point is closer to KL Sentral than the venue is
    assert haversine_km(t["lat"], t["lon"], sentral["lat"], sentral["lon"]) < haversine_km(c["lat"], c["lon"], sentral["lat"], sentral["lon"])
    assert w["walk_km"] == round(haversine_km(zepp["lat"], zepp["lon"], t["lat"], t["lon"]), 1)
    ended = client.post("/api/forecast", json={**near, "datetime": "2026-10-11T23:20:00+08:00"}).json()["walk_out"]
    assert ended and ended["ended"]
    no_dir = client.post("/api/forecast", json={**near, "dropoff": None}).json()["walk_out"]
    assert no_dir and no_dir["target"] is None and no_dir["walk_km"] is None  # pickup at the venue, no drop-off


def test_route_now_for_the_map(monkeypatch):
    import api.traffic as t
    import api.routes.forecast as rf
    rf._route_now.cache_clear()
    monkeypatch.setattr(t, "route_with_traffic", lambda a, b, d=None, timeout=8: (15.6, 18.6))
    q = "from_lat=3.0537&from_lon=101.6935&to_lat=3.1326&to_lon=101.688"
    d = client.get(f"/api/route?{q}").json()
    assert d == {"km": 15.6, "minutes": 18.6, "source": "TomTom traffic prediction"}
    rf._route_now.cache_clear()
    monkeypatch.setattr(t, "route_with_traffic", lambda a, b, d=None, timeout=8: None)  # no key / error
    assert client.get(f"/api/route?{q}").json() == {"km": None, "minutes": None, "source": None}
    rf._route_now.cache_clear()


def test_outlook_matches_horizon_and_follows_v2_verdict():
    import json
    from pathlib import Path
    d = client.post("/api/forecast", json={**BODY, "usual_price_rm": 25.0}).json()
    o, h30 = d["outlook"], next(h for h in d["horizon"] if h["minutes"] == 30)
    assert (o["pct_change"], o["pct_low"], o["pct_high"]) == (h30["pct_change"], h30["pct_low"], h30["pct_high"])
    p = Path(__file__).resolve().parent.parent / "reports" / "v2_verdict.json"
    served = p.exists() and json.loads(p.read_text(encoding="utf-8"))["verdict"].get("with_level")
    assert o["model"] == ("lgbm_v2" if served else "lgbm_v1")
    if o["because"]:  # words only, never "traffic" (reports/traffic_experiment.md)
        assert not any("traffic" in w for w in o["because"])
        assert d["reasons"][1].startswith("Price in 30 min")
    assert d["reasons"][0].startswith("Chance that waiting 30 min")  # contract: reasons[0] = the odds


def test_usual_endpoint_shape(monkeypatch):
    import api.routes.forecast as rf
    est = {"rm": 16.62, "km": 12.8, "min": 27, "source": "Grab published rates + TomTom route — rough", "validated": False,
           "median_abs_error": 0.176, "n_quotes": 9}
    monkeypatch.setattr(rf, "_usual", lambda *a: est)
    d = client.get("/api/usual", params=dict(from_lat=3.158, from_lon=101.7117, to_lat=3.1177, to_lon=101.6774,
                                             at="2026-10-09T17:30:00+08:00")).json()
    assert d["rm"] == 16.62 and d["validated"] is False
    if "time_factor" in d:  # model v2 served: usual price at this hour = formula x the model's hour/weekday factor
        assert abs(d["rm_at_this_time"] - 16.62 * d["time_factor"]) < 0.02  # factor shown rounded to 3 dp


def test_no_wait_when_expected_saving_is_under_rm_1():
    # RM 12 vs usual RM 8 (1.5x, the strongest wait signal): a wait needs an expected drop >= 8.3% to save RM 1.00
    for rm, usual in ((12.0, 8.0), (30.0, 20.0), (60.0, 40.0)):
        d = client.post("/api/forecast", json={**BODY, "datetime": "2026-10-09T17:30:00+08:00",
                                               "quotes": [{"app": "grab", "price_rm": rm}], "usual_price_rm": usual}).json()
        if d["decision"] == "wait":  # the saving shown is the one the rule checked
            assert d["expected_saving_rm"]["grab"] >= 1.00
        for r in d["reasons"]:
            if "RM 1.00 minimum" in r:  # "... save only about RM 0.28 on RM 28.00 ..."
                assert float(r.split("about RM ")[1].split()[0]) < 1.00
