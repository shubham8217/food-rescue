from datetime import datetime, timedelta

import pytest

from app.geo import AREAS, haversine_km
from app.services.matching import Candidate, rank_candidates, score_match

NOW = datetime(2026, 10, 14, 12, 0)


def test_haversine_known_distance():
    # Vashi -> Kharghar is roughly 8 km
    d = haversine_km(*AREAS["Vashi"], *AREAS["Kharghar"])
    assert 7 < d < 10
    assert haversine_km(19.0, 73.0, 19.0, 73.0) == 0


def test_score_formula_weights():
    s = score_match(distance_km=0, donation_hours_left=0, need_hours_left=0, donation_kg=10, need_kg=10)
    assert s["distance_score"] == 1 and s["urgency_score"] == 1 and s["fit_score"] == 1
    assert s["score"] == pytest.approx(0.4 + 0.35 + 0.25)


def test_score_components_individually():
    far = score_match(15, 12, 12, 10, 10)          # at radius edge, no urgency, perfect fit
    assert far["distance_score"] == 0 and far["urgency_score"] == 0
    assert far["score"] == pytest.approx(0.25)
    mid = score_match(7.5, 6, 6, 10, 40)           # half distance, half urgency, 1/4 fit
    assert mid["distance_score"] == pytest.approx(0.5)
    assert mid["urgency_score"] == pytest.approx(0.5)
    assert mid["fit_score"] == pytest.approx(0.25)
    assert mid["score"] == pytest.approx(0.4 * 0.5 + 0.35 * 0.5 + 0.25 * 0.25, abs=1e-4)


def donation(**kw):
    d = {"expiry_time": NOW + timedelta(hours=4), "category": "bakery", "lat": 19.033, "lng": 73.0297,
         "quantity_kg": 20}
    d.update(kw)
    return d


def cand(ngo_id, area="Nerul", need=20, category=None, hours=24, req_id=None):
    lat, lng = AREAS[area]
    return Candidate(ngo_id, req_id or ngo_id, lat, lng, need, NOW + timedelta(hours=hours), category)


def test_nearer_ngo_ranks_first_all_else_equal():
    ranked = rank_candidates(donation(), [cand(1, "Sanpada"), cand(2, "Nerul"), cand(3, "Belapur")], NOW)
    assert [r.ngo_id for r in ranked][0] == 2
    assert ranked[0].distance_km < ranked[1].distance_km


def test_radius_filter_excludes_far_ngos():
    # Seawoods -> Airoli is ~16 km, outside the 15 km radius
    don = donation(lat=AREAS["Seawoods"][0], lng=AREAS["Seawoods"][1])
    far = haversine_km(don["lat"], don["lng"], *AREAS["Airoli"])
    assert far > 15
    ranked = rank_candidates(don, [cand(1, "Airoli"), cand(2, "Seawoods")], NOW)
    assert [r.ngo_id for r in ranked] == [2]


def test_category_filter():
    ranked = rank_candidates(donation(), [cand(1, category="dairy"), cand(2, category="bakery"), cand(3)], NOW)
    assert {r.ngo_id for r in ranked} == {2, 3}


def test_expired_donation_has_no_matches():
    assert rank_candidates(donation(expiry_time=NOW - timedelta(minutes=1)), [cand(1)], NOW) == []


def test_need_deadline_in_past_excluded():
    assert rank_candidates(donation(), [cand(1, hours=-1)], NOW) == []


def test_cannot_travel_before_expiry():
    # 10 minutes of shelf life, 10+ km away at 25 km/h -> impossible
    don = donation(expiry_time=NOW + timedelta(minutes=10), lat=AREAS["Vashi"][0], lng=AREAS["Vashi"][1])
    ranked = rank_candidates(don, [cand(1, "Kharghar"), cand(2, "Vashi")], NOW)
    assert [r.ngo_id for r in ranked] == [2]


def test_top_five_only_and_best_request_per_ngo():
    cands = [cand(i, "Nerul") for i in range(1, 9)]
    cands.append(cand(1, "Nerul", need=20, req_id=99))  # same NGO, second request must not duplicate it
    ranked = rank_candidates(donation(), cands, NOW)
    assert len(ranked) == 5 and len({r.ngo_id for r in ranked}) == 5


def test_better_quantity_fit_wins_when_distance_equal():
    ranked = rank_candidates(donation(quantity_kg=20), [cand(1, need=200), cand(2, need=20)], NOW)
    assert ranked[0].ngo_id == 2


def test_urgent_need_wins_when_distance_equal():
    ranked = rank_candidates(donation(), [cand(1, hours=48), cand(2, hours=2)], NOW)
    assert ranked[0].ngo_id == 2
