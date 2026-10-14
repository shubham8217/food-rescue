from datetime import datetime, timedelta

import pytest

from app.services.cleaning import canonical_category, clean_records

NOW = datetime(2026, 10, 14, 12, 0, 0)


def row(**kw):
    base = {"org_name": "Vashi Bakery", "food_type": "Bread loaves", "category": "bakery", "quantity_kg": "12.5",
            "expiry_time": (NOW + timedelta(hours=5)).isoformat() + "Z", "lat": "19.07", "lng": "72.99",
            "area": "Vashi"}
    base.update(kw)
    return base


def reasons(rows, kind="donation"):
    res = clean_records(rows, kind, NOW)
    return res, [r["reason"] for r in res.rejected]


def test_valid_row_passes_and_is_typed():
    res, rej = reasons([row()])
    assert rej == []
    c = res.clean[0]
    assert c["category"] == "bakery" and c["quantity_kg"] == 12.5 and c["area"] == "Vashi"
    assert c["expiry_time"] == NOW + timedelta(hours=5)


@pytest.mark.parametrize("raw,expected", [
    ("Veg Meals", "cooked_meals"), ("BREAD", "bakery"), ("  fresh produce ", "produce"), ("Milk", "dairy"),
    ("Dry-Goods", "packaged"), ("Juice", "beverages"), ("xyz123", None), ("", None), (None, None)])
def test_category_standardisation(raw, expected):
    assert canonical_category(raw) == expected


def test_alias_category_is_standardised_in_output():
    res, _ = reasons([row(category="Baked Goods")])
    assert res.clean[0]["category"] == "bakery"


@pytest.mark.parametrize("field", ["org_name", "food_type", "category", "quantity_kg", "expiry_time", "area"])
def test_missing_required_field_rejected(field):
    res, rej = reasons([row(**{field: ""})])
    assert not res.clean
    assert rej == [f"missing required field: {field}"]


def test_unknown_category_rejected_with_value():
    _, rej = reasons([row(category="electronics")])
    assert rej == ["unknown category: 'electronics'"]


def test_expired_rejected():
    _, rej = reasons([row(expiry_time=(NOW - timedelta(hours=2)).isoformat())])
    assert rej == ["expired item"]


def test_short_shelf_life_is_unsafe():
    _, rej = reasons([row(expiry_time=(NOW + timedelta(minutes=30)).isoformat())])
    assert "unsafe" in rej[0]


@pytest.mark.parametrize("food", ["Spoiled rice", "stale bread", "Mouldy cheese", "rotten tomatoes"])
def test_unsafe_items_rejected(food):
    _, rej = reasons([row(food_type=food)])
    assert rej[0].startswith("unsafe item")


def test_bad_quantity_and_expiry():
    _, rej = reasons([row(quantity_kg="lots"), row(quantity_kg="-4"), row(quantity_kg="99999"),
                      row(expiry_time="tomorrow-ish")])
    assert rej[0].startswith("invalid quantity")
    assert rej[1].startswith("quantity_kg out of range") and rej[2].startswith("quantity_kg out of range")
    assert rej[3].startswith("invalid expiry_time")


def test_duplicates_in_batch_keep_first():
    res, rej = reasons([row(), row(), row(food_type="Different")])
    assert len(res.clean) == 2
    assert rej == ["duplicate row in batch"]
    assert res.rejected[0]["row_number"] == 2


def test_duplicate_of_bad_row_does_not_hide_good_row():
    res, rej = reasons([row(category="zzz"), row()])
    assert len(res.clean) == 1 and len(rej) == 1


def test_missing_coordinates_imputed_from_area():
    res, rej = reasons([row(lat="", lng="")])
    assert rej == [] and 19.0 < res.clean[0]["lat"] < 19.2


def test_unknown_area_without_coordinates_rejected():
    _, rej = reasons([row(lat="", lng="", area="Atlantis")])
    assert rej == ["missing location (no lat/lng and unknown area)"]


def test_outside_service_area_rejected():
    _, rej = reasons([row(lat="28.6", lng="77.2")])
    assert rej == ["location outside Navi Mumbai service area"]


def test_rejections_keep_raw_row_and_row_numbers():
    res, _ = reasons([row(), row(category="???")], )
    assert res.rejected[0]["raw"]["category"] == "???" and res.rejected[0]["row_number"] == 2


def test_request_rows_allow_empty_category_but_not_past_needed_by():
    r = row(category="", food_type="")
    res, rej = reasons([r], "request")
    assert rej == [] and res.clean[0]["category"] is None
    _, rej = reasons([row(category="", expiry_time=(NOW - timedelta(hours=1)).isoformat())], "request")
    assert rej == ["needed_by is in the past"]


def test_empty_input():
    res = clean_records([], "donation", NOW)
    assert res.clean == [] and res.rejected == []
