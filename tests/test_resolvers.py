from datetime import date

import pytest

from control_tower.resolvers import find_ids_in_text, resolve_date, resolve_entity


@pytest.mark.parametrize("mention,kind,expected", [
    ("the Texas plant", "plant", "P_TX"),
    ("Texas plant", "plant", "P_TX"),
    ("Huntsville", "plant", "P_AL"),
    ("Huntsville line", "plant", "P_AL"),
    ("Wacky Wheels Lexington (P_KY)", "plant", "P_KY"),
    ("Wacky Wheels Greensboro", "plant", "P_NC"),
    ("Volt", "supplier", "SUP-05"),
    ("Kestrel", "supplier", "SUP-06"),
    ("Quanta", "supplier", "SUP-12"),
    ("Lumen", "supplier", "SUP-18"),
    ("Orbit", "supplier", "SUP-11"),
    ("Orbit Optics", "supplier", "SUP-11"),
    ("heavy-duty wiring harness", "part", "HARN-B"),
    ("60 kWh battery packs", "part", "BATT-60"),
    ("60 kWh battery pack", "part", "BATT-60"),
    ("surround-view cameras", "part", "CAM-360"),
    ("surround-view camera kit", "part", "CAM-360"),
    ("infotainment chip", "part", "CHIP-IVI"),
    ("CAM-360 (surround-view camera kit)", "part", "CAM-360"),
    ("leather seat sets", "part", "SEAT-LEA"),
])
def test_resolve_entity(mention, kind, expected):
    got, method, conf = resolve_entity(mention, kind)
    assert got == expected, (mention, method)
    assert method in {"exact_id", "alias", "name", "name_partial"}
    assert conf >= 0.85


def test_unresolvable_and_fuzzy_are_flagged():
    assert resolve_entity("seat material", "part")[0] is None
    assert resolve_entity("something electronic", "part")[0] is None
    assert resolve_entity(None, "plant")[1] == "missing"
    got, method, _ = resolve_entity("infotanment chip", "part")
    assert got == "CHIP-IVI" and method == "fuzzy"


@pytest.mark.parametrize("phrase,expected", [
    ("next Monday", date(2027, 3, 15)),
    ("next Friday", date(2027, 3, 19)),
    ("next Tuesday", date(2027, 3, 16)),
    ("next Thursday", date(2027, 3, 18)),
    ("last Monday", date(2027, 3, 1)),
    ("Thursday Feb 25", date(2027, 2, 25)),
    ("Monday Mar 29", date(2027, 3, 29)),
    ("Monday Mar 22", date(2027, 3, 22)),
    ("Thursday Apr 1", date(2027, 4, 1)),
    ("Friday Mar 26", date(2027, 3, 26)),
    ("March 22", date(2027, 3, 22)),
    ("2027-03-24", date(2027, 3, 24)),
    ("due 2027-03-15", date(2027, 3, 15)),
    ("Wednesday", date(2027, 3, 10)),
    ("today", date(2027, 3, 8)),
    ("tomorrow", date(2027, 3, 9)),
    ("yesterday", date(2027, 3, 5)),
])
def test_resolve_date(phrase, expected):
    got, rule = resolve_date(phrase)
    assert got == expected, (phrase, rule)


def test_weekday_mismatch_flagged():
    got, rule = resolve_date("Tuesday Mar 29")
    assert got is None and rule == "weekday_mismatch"


def test_next_weekday_sanity_new_eta_after_original():
    orig, _ = resolve_date("next Monday")
    new, _ = resolve_date("next Friday")
    assert orig < new


def test_find_ids_in_text():
    text = "Shipment SH-0182 of CAM-360 for P_IN from SUP-11, lot LOT-0191 and PO-0001; CHIP-IVI too."
    ids = find_ids_in_text(text)
    assert ids["shipment"] == ["SH-0182"]
    assert ids["part"] == ["CAM-360", "CHIP-IVI"]
    assert ids["plant"] == ["P_IN"] and ids["supplier"] == ["SUP-11"]
    assert ids["lot"] == ["LOT-0191"] and ids["production_order"] == ["PO-0001"]
