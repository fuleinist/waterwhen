"""Tests through the HTTP seam, from a client's point of view."""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from waterwhen import server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp.name, "test.db")
        os.environ["WATERWHEN_QUIET"] = "1"
        cls.httpd = server.create_server("127.0.0.1", 0, cls.db_path, offline=True)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if server.STORE:
            server.STORE.close()
        cls.tmp.cleanup()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def request(self, method, path, payload=None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.url(path), data=data, method=method, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            if response.headers.get("Content-Type", "").startswith("application/json"):
                return response.status, json.loads(body)
            return response.status, body

    def create_bed(self, **overrides):
        payload = {
            "name": "North bed",
            "lat": -33.7683,
            "lon": 151.0878,
            "length_m": 2.5,
            "width_m": 1.2,
            "depth_m": 0.35,
            "soil": "sandy_loam",
            "mulch": "straw",
            "crop": "tomato",
            "stage": "vegetative",
            "method": "can",
            "can_litres": 9.0,
            "flow_lpm": 1.0,
        }
        payload.update(overrides)
        status, body = self.request("POST", "/api/beds", payload)
        self.assertEqual(status, 201)
        return body["bed"]

    def test_health(self):
        status, body = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_catalog_lists_the_tables(self):
        status, body = self.request("GET", "/api/catalog")
        self.assertEqual(status, 200)
        self.assertGreater(len(body["soils"]), 5)
        self.assertGreater(len(body["crops"]), 10)

    def test_create_and_list_a_bed(self):
        bed = self.create_bed(name="List bed")
        status, body = self.request("GET", "/api/beds")
        self.assertEqual(status, 200)
        self.assertIn(bed["id"], [item["id"] for item in body["beds"]])

    def test_bed_list_can_include_today(self):
        self.create_bed(name="Today bed")
        status, body = self.request("GET", "/api/beds?plans=1")
        self.assertEqual(status, 200)
        self.assertIn(body["beds"][-1]["today"]["action"], ("water_now", "hold_for_rain", "check", "wait"))

    def test_plan_returns_an_action_and_a_dose(self):
        bed = self.create_bed(name="Plan bed")
        status, plan = self.request("GET", f"/api/beds/{bed['id']}/plan")
        self.assertEqual(status, 200)
        self.assertIn(plan["action"], ("water_now", "hold_for_rain", "check", "wait"))
        self.assertIn("litres", plan["dose"])
        self.assertEqual(len(plan["outlook"]), 7)
        self.assertEqual(len(plan["history"]), 14)
        self.assertGreater(len(plan["assumptions"]), 4)

    def test_logged_water_changes_the_plan(self):
        bed = self.create_bed(name="Log bed")
        _, before = self.request("GET", f"/api/beds/{bed['id']}/plan")
        status, _ = self.request(
            "POST", f"/api/beds/{bed['id']}/waterings", {"litres": 40.0, "note": "Hose"}
        )
        self.assertEqual(status, 201)
        _, after = self.request("GET", f"/api/beds/{bed['id']}/plan")
        self.assertLessEqual(after["model"]["depletion_mm"], before["model"]["depletion_mm"])
        self.assertEqual(after["summary"]["season_litres"], 40.0)

    def test_reading_overrides_the_start_state(self):
        bed = self.create_bed(name="Reading bed")
        status, _ = self.request("POST", f"/api/beds/{bed['id']}/readings", {"feel": "dry"})
        self.assertEqual(status, 201)
        _, plan = self.request("GET", f"/api/beds/{bed['id']}/plan")
        self.assertEqual(plan["confidence"]["source"], "finger test")

    def test_patch_updates_a_bed(self):
        bed = self.create_bed(name="Patch bed")
        status, body = self.request("PATCH", f"/api/beds/{bed['id']}", {"crop": "lettuce", "stage": "harvest"})
        self.assertEqual(status, 200)
        self.assertEqual(body["bed"]["crop"], "lettuce")
        self.assertEqual(body["bed"]["name"], "Patch bed")

    def test_bad_soil_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("POST", "/api/beds", {"name": "Bad", "soil": "moon_dust"})
        self.assertEqual(caught.exception.code, 400)

    def test_short_name_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("POST", "/api/beds", {"name": ""})
        self.assertEqual(caught.exception.code, 400)

    def test_unknown_bed_is_a_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("GET", "/api/beds/nope/plan")
        self.assertEqual(caught.exception.code, 404)

    def test_card_has_the_number_from_the_plan(self):
        bed = self.create_bed(name="Card bed")
        _, plan = self.request("GET", f"/api/beds/{bed['id']}/plan")
        status, html = self.request("GET", f"/api/beds/{bed['id']}/card")
        self.assertEqual(status, 200)
        self.assertIn("Card bed", html)
        self.assertIn(f"{plan['dose']['litres']:.1f} L", html)
        self.assertIn("Next seven days", html)

    def test_delete_removes_a_bed(self):
        bed = self.create_bed(name="Delete bed")
        status, _ = self.request("DELETE", f"/api/beds/{bed['id']}")
        self.assertEqual(status, 200)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("GET", f"/api/beds/{bed['id']}")
        self.assertEqual(caught.exception.code, 404)

    def test_index_serves_the_app(self):
        status, html = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("waterwhen", html)


if __name__ == "__main__":
    unittest.main()