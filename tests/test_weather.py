"""Tests for the Open-Meteo parser and the offline fallback."""

import unittest
from datetime import date

from waterwhen import weather


def payload(days=3):
    dates = [f"2026-11-{24 + i:02d}" for i in range(days)]
    return {
        "latitude": -33.77,
        "longitude": 151.09,
        "elevation": 30.0,
        "timezone": "Australia/Sydney",
        "utc_offset_seconds": 39600,
        "daily": {
            "time": dates,
            "et0_fao_evapotranspiration": [4.2, 5.1, None][:days],
            "precipitation_sum": [0.0, 12.4, 1.0][:days],
            "temperature_2m_max": [25.0, 27.5, 23.0][:days],
            "temperature_2m_min": [14.0, 16.0, 13.0][:days],
        },
        "hourly": {
            "time": [f"{dates[0]}T{h:02d}:00" for h in range(24)],
            "soil_moisture_0_to_7cm": [0.15 + h * 0.001 for h in range(24)],
            "soil_moisture_7_to_28cm": [0.19 + h * 0.001 for h in range(24)],
            "soil_temperature_6cm": [18.0 + h * 0.1 for h in range(24)],
        },
    }


class ParseTests(unittest.TestCase):
    def test_parse_returns_one_row_per_day(self):
        result = weather.parse(payload())
        self.assertEqual(result["source"], "open-meteo")
        self.assertEqual(len(result["days"]), 3)
        self.assertEqual(result["days"][0]["date"], "2026-11-24")
        self.assertAlmostEqual(result["days"][1]["et0"], 5.1, places=2)
        self.assertAlmostEqual(result["days"][1]["rain"], 12.4, places=2)

    def test_parse_keeps_a_missing_value_as_none(self):
        result = weather.parse(payload())
        self.assertIsNone(result["days"][2]["et0"])

    def test_parse_reads_soil_moisture(self):
        result = weather.parse(payload())
        self.assertIsNotNone(result["soil"])
        self.assertGreater(result["soil"]["moisture_0_7"], 0.0)
        self.assertGreater(result["soil"]["moisture_7_28"], 0.0)

    def test_parse_rejects_an_empty_response(self):
        with self.assertRaises(ValueError):
            weather.parse({"daily": {"time": []}})

    def test_cell_is_recorded(self):
        result = weather.parse(payload())
        self.assertAlmostEqual(result["cell"]["lat"], -33.77, places=2)


class ModelledTests(unittest.TestCase):
    def test_modelled_has_a_full_window(self):
        result = weather.modelled(-33.77, 151.09, today=date(2026, 11, 26))
        self.assertEqual(result["source"], "modelled")
        self.assertEqual(len(result["days"]), weather.PAST_DAYS + weather.FORECAST_DAYS)
        self.assertEqual(result["days"][0]["date"], "2026-11-12")
        self.assertEqual(result["days"][-1]["date"], "2026-12-02")
        self.assertIsNone(result["soil"])

    def test_modelled_is_deterministic(self):
        first = weather.modelled(-33.77, 151.09, today=date(2026, 11, 26))
        second = weather.modelled(-33.77, 151.09, today=date(2026, 11, 26))
        self.assertEqual(first["days"], second["days"])

    def test_northern_latitude_flips_the_season(self):
        south = weather.modelled(-33.77, 151.09, today=date(2026, 1, 15))
        north = weather.modelled(51.5, -0.12, today=date(2026, 1, 15))
        self.assertGreater(south["days"][14]["et0"], north["days"][14]["et0"])

    def test_location_key_rounds_to_two_decimals(self):
        self.assertEqual(weather.location_key(-33.7683, 151.0878), "-33.77,151.09")


if __name__ == "__main__":
    unittest.main()