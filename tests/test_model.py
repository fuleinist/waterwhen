"""Unit tests for the water balance and the dose rules."""

import unittest
from datetime import date, timedelta

from waterwhen import model, soils


def make_bed(**overrides):
    values = {
        "name": "Test bed",
        "length_m": 2.5,
        "width_m": 1.2,
        "soil": "sandy_loam",
        "mulch": "straw",
        "crop": "tomato",
        "stage": "vegetative",
        "depth_m": 0.35,
        "method": "can",
        "can_litres": 9.0,
        "flow_lpm": 1.0,
    }
    values.update(overrides)
    return model.Bed(**values)


def make_weather(today, et0=5.0, rain=0.0, days_before=14, days_after=6, rain_days=None):
    rain_days = rain_days or {}
    start = today - timedelta(days=days_before)
    days = []
    for offset in range(days_before + days_after + 1):
        current = start + timedelta(days=offset)
        days.append(
            {
                "date": current.isoformat(),
                "et0": et0,
                "rain": rain_days.get(current.isoformat(), rain),
                "tmax": 26.0,
                "tmin": 14.0,
            }
        )
    return {
        "source": "open-meteo",
        "stale": False,
        "fetched_at": None,
        "timezone": "Australia/Sydney",
        "cell": {"lat": -33.77, "lon": 151.09, "elevation": 30.0},
        "days": days,
        "soil": None,
    }


class SoilModelTests(unittest.TestCase):
    def test_root_depth_is_capped_by_stage_and_bed_depth(self):
        bed = make_bed()
        self.assertAlmostEqual(bed.root_depth_m(), 0.275, places=3)
        shallow = make_bed(depth_m=0.2)
        self.assertAlmostEqual(shallow.root_depth_m(), 0.2, places=3)

    def test_taw_and_raw_follow_fao56(self):
        bed = make_bed()
        self.assertAlmostEqual(bed.taw_mm(), 33.0, places=2)
        self.assertAlmostEqual(bed.raw_mm(), 13.2, places=2)

    def test_kc_by_stage(self):
        self.assertAlmostEqual(make_bed(stage="seedling").kc(), 0.60, places=2)
        self.assertAlmostEqual(make_bed(stage="vegetative").kc(), 0.875, places=2)
        self.assertAlmostEqual(make_bed(stage="flowering").kc(), 1.15, places=2)
        self.assertAlmostEqual(make_bed(stage="harvest").kc(), 0.80, places=2)

    def test_kc_override_wins_and_is_clamped(self):
        self.assertAlmostEqual(make_bed(kc_override=1.0).kc(), 1.0, places=2)
        self.assertAlmostEqual(make_bed(kc_override=9.0).kc(), 1.60, places=2)

    def test_effective_rain_ignores_a_trace(self):
        self.assertEqual(model.effective_rain(0.0), 0.0)
        self.assertEqual(model.effective_rain(1.9), 0.0)
        self.assertAlmostEqual(model.effective_rain(12.0), 9.0, places=3)

    def test_unknown_keys_fall_back(self):
        bed = make_bed(soil="moon_dust", crop="unknown", stage="unknown", mulch="unknown", method="unknown")
        self.assertGreater(bed.taw_mm(), 0)
        self.assertGreater(bed.kc(), 0)


class DoseTests(unittest.TestCase):
    def test_zero_deficit_gives_no_dose(self):
        dose = model.dose_for(make_bed(), 0.0)
        self.assertEqual(dose["litres"], 0.0)
        self.assertEqual(dose["applied_mm"], 0.0)
        self.assertEqual(dose["split_count"], 1)

    def test_dose_converts_mm_to_litres(self):
        dose = model.dose_for(make_bed(), 20.0)
        self.assertAlmostEqual(dose["applied_mm"], 23.53, places=2)
        self.assertAlmostEqual(dose["litres"], 70.59, places=1)
        self.assertAlmostEqual(dose["cans"], 7.84, places=1)
        self.assertEqual(dose["split_count"], 1)

    def test_sand_splits_a_large_dose(self):
        bed = make_bed(soil="sand")
        dose = model.dose_for(bed, 30.0)
        self.assertEqual(dose["split_count"], 2)
        self.assertAlmostEqual(dose["applied_mm"], 25.0, places=2)
        self.assertAlmostEqual(dose["litres"], 75.0, places=1)
        self.assertIn("Split into 2 applications", dose["split_note"])

    def test_drip_bed_reports_run_time(self):
        dose = model.dose_for(make_bed(method="drip", flow_lpm=2.0), 20.0)
        self.assertEqual(dose["run_minutes"], 33)

    def test_hand_bed_has_no_run_time(self):
        self.assertIsNone(model.dose_for(make_bed(method="can"), 20.0)["run_minutes"])


class PlanTests(unittest.TestCase):
    today = date(2026, 11, 26)

    def test_dry_bed_waters_now(self):
        weather = make_weather(self.today)
        reading = {"date": self.today.isoformat(), "feel": "dry", "value": None}
        plan = model.build_plan(make_bed(), weather, [], reading, today=self.today)
        self.assertEqual(plan["action"], "water_now")
        self.assertGreater(plan["dose"]["litres"], 90)
        self.assertIn("Root-zone depletion", plan["reason"])
        self.assertEqual(len(plan["history"]), 14)
        self.assertEqual(len(plan["outlook"]), 7)

    def test_wet_bed_waits(self):
        weather = make_weather(self.today)
        reading = {"date": self.today.isoformat(), "feel": "wet", "value": None}
        plan = model.build_plan(make_bed(), weather, [], reading, today=self.today)
        self.assertEqual(plan["action"], "wait")
        self.assertEqual(plan["dose"]["litres"], 0.0)

    def test_rain_in_48_hours_holds_the_dose(self):
        weather = make_weather(self.today, rain_days={self.today.isoformat(): 30.0})
        reading = {"date": self.today.isoformat(), "feel": "dry", "value": None}
        plan = model.build_plan(make_bed(), weather, [], reading, today=self.today)
        self.assertEqual(plan["action"], "hold_for_rain")
        self.assertEqual(plan["dose"]["litres"], 0.0)
        self.assertIn("Holding saves the dose", plan["reason"])

    def test_light_rain_does_not_hold(self):
        weather = make_weather(self.today, rain_days={self.today.isoformat(): 4.0})
        reading = {"date": self.today.isoformat(), "feel": "dry", "value": None}
        plan = model.build_plan(make_bed(), weather, [], reading, today=self.today)
        self.assertEqual(plan["action"], "water_now")

    def test_sensor_reading_sets_the_start_state(self):
        weather = make_weather(self.today)
        reading = {"date": self.today.isoformat(), "value": 14.2, "feel": None}
        plan = model.build_plan(make_bed(), weather, [], reading, today=self.today)
        self.assertEqual(plan["confidence"]["source"], "sensor")
        self.assertAlmostEqual(plan["model"]["depletion_mm"], 10.6, places=0)
        self.assertEqual(plan["action"], "check")

    def test_logged_watering_reduces_depletion(self):
        weather = make_weather(self.today)
        reading = {"date": self.today.isoformat(), "feel": "dry", "value": None}
        before = model.build_plan(make_bed(), weather, [], reading, today=self.today)
        waterings = [{"id": "w1", "date": self.today.isoformat(), "litres": 60.0, "note": ""}]
        after = model.build_plan(make_bed(), weather, waterings, reading, today=self.today)
        self.assertLess(after["model"]["depletion_mm"], before["model"]["depletion_mm"])
        self.assertAlmostEqual(after["summary"]["season_litres"], 60.0, places=1)

    def test_soil_moisture_seeds_the_balance(self):
        weather = make_weather(self.today)
        weather["soil"] = {"moisture_0_7": 0.12, "moisture_7_28": 0.14, "temperature_6cm": 18.0}
        plan = model.build_plan(make_bed(), weather, [], None, today=self.today)
        self.assertEqual(plan["confidence"]["source"], "modelled soil moisture")
        self.assertGreater(plan["model"]["depletion_mm"], 0)

    def test_history_grows_towards_today(self):
        weather = make_weather(self.today, et0=6.0)
        reading = {"date": self.today.isoformat(), "feel": "moist", "value": None}
        plan = model.build_plan(make_bed(), weather, [], reading, today=self.today)
        history = plan["history"]
        self.assertGreaterEqual(history[-1]["depletion_mm"], history[0]["depletion_mm"])
        self.assertTrue(all(row["depletion_mm"] <= row["taw_mm"] for row in history))

    def test_outlook_depletion_respects_holding_capacity(self):
        weather = make_weather(self.today, et0=12.0)
        reading = {"date": self.today.isoformat(), "feel": "wet", "value": None}
        plan = model.build_plan(make_bed(), weather, [], reading, today=self.today)
        for row in plan["outlook"]:
            self.assertLessEqual(row["depletion_end_mm"], row["taw_mm"] + 0.001)

    def test_next_check_is_in_the_future(self):
        weather = make_weather(self.today)
        reading = {"date": self.today.isoformat(), "feel": "dry", "value": None}
        plan = model.build_plan(make_bed(), weather, [], reading, today=self.today)
        self.assertGreater(plan["next_check"], plan["today"])

    def test_missing_weather_days_raises(self):
        with self.assertRaises(ValueError):
            model.build_plan(make_bed(), {"days": []}, [], None, today=self.today)


class CatalogTests(unittest.TestCase):
    def test_catalog_has_every_default_key(self):
        catalog = soils.catalog()
        for group, key in (
            ("soils", catalog["defaults"]["soil"]),
            ("crops", catalog["defaults"]["crop"]),
            ("stages", catalog["defaults"]["stage"]),
            ("mulches", catalog["defaults"]["mulch"]),
            ("methods", catalog["defaults"]["method"]),
        ):
            self.assertIn(key, [item["key"] for item in catalog[group]])

    def test_every_soil_is_physically_sane(self):
        for key, row in soils.SOILS.items():
            self.assertGreater(row["fc"], row["wp"], key)
            self.assertLess(row["fc"], 0.6, key)

    def test_every_crop_has_three_coefficients(self):
        for key, row in soils.CROPS.items():
            self.assertEqual(len(row["kc"]), 3, key)
            self.assertTrue(0.2 <= row["p"] <= 0.8, key)


if __name__ == "__main__":
    unittest.main()