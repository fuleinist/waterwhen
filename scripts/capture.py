"""Capture real screenshots of the running app with Playwright.

Starts the server as a child process, seeds three beds and one finger test,
captures the screenshots, checks the mobile layout, then stops the server.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screenshots")
PORT = 8781
BASE = f"http://127.0.0.1:{PORT}"
DB = os.path.join(ROOT, "data", "waterwhen.db")

BEDS = [
    {
        "name": "North bed",
        "lat": -33.7683,
        "lon": 151.0878,
        "length_m": 2.4,
        "width_m": 1.2,
        "depth_m": 0.35,
        "soil": "sandy_loam",
        "mulch": "straw",
        "crop": "tomato",
        "stage": "flowering",
        "method": "can",
        "can_litres": 9.0,
        "flow_lpm": 1.0,
    },
    {
        "name": "Herb bed",
        "lat": -33.7683,
        "lon": 151.0878,
        "length_m": 1.2,
        "width_m": 0.9,
        "depth_m": 0.30,
        "soil": "loam",
        "mulch": "compost",
        "crop": "basil",
        "stage": "vegetative",
        "method": "drip",
        "can_litres": 9.0,
        "flow_lpm": 1.6,
    },
    {
        "name": "Leafy bed",
        "lat": -33.7683,
        "lon": 151.0878,
        "length_m": 2.0,
        "width_m": 1.0,
        "depth_m": 0.30,
        "soil": "silt_loam",
        "mulch": "straw",
        "crop": "lettuce",
        "stage": "harvest",
        "method": "hose",
        "can_litres": 9.0,
        "flow_lpm": 1.0,
    },
]


def call(path, payload=None, method=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method or ("POST" if data else "GET"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_server(seconds=40):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            call("/api/health")
            return True
        except Exception:
            time.sleep(0.4)
    return False


def main():
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(DB):
        os.remove(DB)

    env = dict(os.environ, WATERWHEN_QUIET="1")
    server = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-m", "waterwhen", "--port", str(PORT), "--db", DB],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        if not wait_for_server():
            print("FATAL: server did not start")
            print(server.stderr.read().decode("utf-8", "replace")[:2000])
            return 1

        beds = [call("/api/beds", bed)["bed"] for bed in BEDS]
        for bed in beds:
            print("bed", bed["id"], bed["name"])

        north = next(item for item in beds if item["name"] == "North bed")
        call(f"/api/beds/{north['id']}/readings", {"feel": "dry", "note": "Finger test at 10 cm"})
        herb = next(item for item in beds if item["name"] == "Herb bed")
        call(f"/api/beds/{herb['id']}/readings", {"feel": "moist", "note": "Finger test at 10 cm"})

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()

            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("console", lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.goto(BASE + "/", wait_until="networkidle")
            page.wait_for_selector(".action-card", timeout=120000)
            time.sleep(1.5)
            page.screenshot(path=os.path.join(OUT, "app-desktop.png"), full_page=True)
            print("saved app-desktop.png")
            print("desktop title:", page.inner_text(".action-title"))
            print("desktop overflow:", page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth"))
            print("console errors:", errors or "none")

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile.goto(BASE + "/", wait_until="networkidle")
            mobile.wait_for_selector(".action-card", timeout=120000)
            time.sleep(1.0)
            overflow = mobile.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
            print("mobile overflow:", overflow)
            mobile.screenshot(path=os.path.join(OUT, "app-mobile.png"), full_page=True)
            print("saved app-mobile.png")

            summary = call("/api/beds?plans=1")["beds"]
            card_bed = next(
                (item for item in summary if item.get("today", {}).get("action") == "water_now"),
                summary[0],
            )
            card = browser.new_page(viewport={"width": 900, "height": 1200})
            card.goto(f"{BASE}/api/beds/{card_bed['id']}/card", wait_until="networkidle")
            time.sleep(0.6)
            card.screenshot(path=os.path.join(OUT, "bed-card.png"), full_page=True)
            print("saved bed-card.png for", card_bed["name"])

            browser.close()
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())