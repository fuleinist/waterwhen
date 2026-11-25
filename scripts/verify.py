"""Verify the water balance against hand arithmetic, and print figures for the README."""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from waterwhen import model  # noqa: E402

TODAY = date(2026, 11, 26)


def bed(**overrides):
    values = {
        "name": "North bed",
        "length_m": 2.4,
        "width_m": 1.2,
        "soil": "sandy_loam",
        "mulch": "straw",
        "crop": "tomato",
        "stage": "flowering",
        "depth_m": 0.35,
        "method": "can",
        "can_litres": 9.0,
        "flow_lpm": 1.0,
    }
    values.update(overrides)
    return model.Bed(**values)


def weather(et0=5.0, rain=0.0, rain_today=True):
    start = TODAY - timedelta(days=14)
    days = []
    for offset in range(21):
        current = start + timedelta(days=offset)
        days.append(
            {
                "date": current.isoformat(),
                "et0": et0,
                "rain": rain if (offset == 14 and rain_today) else 0.0,
                "tmax": 27.0,
                "tmin": 15.0,
            }
        )
    return {
        "source": "open-meteo",
        "stale": False,
        "fetched_at": None,
        "timezone": "Australia/Sydney",
        "cell": {"lat": -33.78, "lon": 151.12, "elevation": 99.0},
        "days": days,
        "soil": None,
    }


def check(label, actual, expected, tolerance=0.05):
    ok = abs(actual - expected) <= tolerance
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {actual:.3f} (expected {expected:.3f})")
    return ok


def main():
    b = bed()
    results = []

    print("== Hand check 1: water holding and refill point ==")
    # TAW = (0.18 - 0.06) * 1000 * 0.35 = 42.0 mm
    results.append(check("TAW mm", b.taw_mm(), 42.0))
    # RAW = 0.40 * 42.0 = 16.8 mm
    results.append(check("RAW mm", b.raw_mm(), 16.8))

    print()
    print("== Hand check 2: crop use for one day ==")
    # ETc = 5.0 * 1.15 * 0.85 = 4.8875 mm
    etc = model.crop_et(5.0, b.kc(), b.mulch_row()["factor"])
    results.append(check("ETc mm", etc, 4.8875, tolerance=0.001))

    print()
    print("== Hand check 3: dose conversion ==")
    # A 30 mm deficit at 85 percent efficiency needs 35.29 mm applied.
    # 35.29 mm * 2.88 m2 = 101.6 L. Split cap is 40 mm for sandy loam, and
    # 35.29 is under the 1.25 x cap threshold, so one application.
    dose = model.dose_for(b, 30.0)
    results.append(check("applied mm", dose["applied_mm"], 35.29, tolerance=0.01))
    results.append(check("litres", dose["litres"], 101.6, tolerance=0.2))
    results.append(check("cans", dose["cans"], 11.3, tolerance=0.1))
    print(f"      split count {dose['split_count']} (expected 1)")

    print()
    print("== Hand check 4: effective rain ==")
    # (12 - 2) * 0.90 = 9.0 mm
    results.append(check("effective rain mm", model.effective_rain(12.0), 9.0, tolerance=0.001))
    results.append(check("trace rain mm", model.effective_rain(1.5), 0.0, tolerance=0.001))

    print()
    print("== Hand check 5: a dry spell from field capacity ==")
    start = {"date": TODAY.isoformat(), "feel": "wet", "value": None}
    plan = model.build_plan(b, weather(), [], start, today=TODAY)
    # A wet start is 0.15 * 42 = 6.3 mm depletion. Each day adds 4.8875 mm.
    # Day 0 start 6.30, day 1 start 11.19, day 2 start 16.08, day 3 start 20.96.
    # The refill point is 16.8 mm, so the first dose lands on day 3.
    starts = [round(row["depletion_start_mm"], 2) for row in plan["outlook"][:4]]
    print(f"      depletion starts: {starts} (hand: 6.3, 11.19, 16.08, 20.96)")
    results.append(check("day 1 start", starts[1], 11.19, tolerance=0.02))
    results.append(check("day 2 start", starts[2], 16.08, tolerance=0.02))
    results.append(check("day 3 start", starts[3], 20.96, tolerance=0.02))
    actions = [row["action"] for row in plan["outlook"][:4]]
    print(f"      actions: {actions} (expected wait, wait, wait, water_now)")
    results.append(actions[3] == "water_now")
    # The dose refills to field capacity: a 20.71 mm deficit at 85 percent
    # efficiency needs 24.36 mm applied, which is 70.2 L over 2.88 m2.
    results.append(check("day 3 litres", plan["outlook"][3]["dose"]["litres"], 70.2, tolerance=0.5))

    print()
    print("== Figures for the README ==")
    dry = model.build_plan(
        b, weather(), [], {"date": TODAY.isoformat(), "feel": "dry", "value": None}, today=TODAY
    )
    print(f"North bed, dry reading: action {dry['action']}, {dry['dose']['litres']:.0f} L")
    print(f"  depletion {dry['model']['depletion_mm']:.0f} mm of {dry['model']['taw_mm']:.0f} mm")
    print(f"  refill point {dry['model']['refill_mm']:.0f} mm")
    print(f"  applied {dry['dose']['applied_mm']:.0f} mm over {dry['model']['area_m2']:.2f} m2")
    print(f"  cans {dry['dose']['cans']:.1f} x {b.can_litres:.0f} L")
    print(f"  split {dry['dose']['split_count']}, note: {dry['dose']['split_note'] or 'none'}")
    print(f"  next check {dry['next_check']}")

    rainy = model.build_plan(
        b,
        weather(rain=34.0),
        [],
        {"date": TODAY.isoformat(), "feel": "dry", "value": None},
        today=TODAY,
    )
    print(f"Same bed, 34 mm of rain forecast: action {rainy['action']}, {rainy['dose']['litres']:.0f} L")

    drip = model.dose_for(bed(method="drip", flow_lpm=1.6), 30.0)
    print(f"Drip bed at 1.6 L/min: {drip['litres']:.0f} L, {drip['run_minutes']} min")

    print()
    failed = [line for line in results if not line]
    print(f"{len(results) - len(failed)}/{len(results)} hand checks pass")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())