"""HTTP server for waterwhen.

The stack is the Python standard library. FastAPI is not used because the
installed FastAPI and Starlette versions conflict on this machine.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import urllib.parse
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import db, model, soils, weather

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(ROOT, "static")
MAX_BODY = 128 * 1024

STORE: db.Store | None = None
OFFLINE = False

BED_PATH = re.compile(r"^/api/beds/([A-Za-z0-9_-]+)$")
BED_PLAN = re.compile(r"^/api/beds/([A-Za-z0-9_-]+)/plan$")
BED_CARD = re.compile(r"^/api/beds/([A-Za-z0-9_-]+)/card$")
BED_WATERINGS = re.compile(r"^/api/beds/([A-Za-z0-9_-]+)/waterings$")
BED_WATERING = re.compile(r"^/api/beds/([A-Za-z0-9_-]+)/waterings/([A-Za-z0-9_-]+)$")
BED_READINGS = re.compile(r"^/api/beds/([A-Za-z0-9_-]+)/readings$")

ACTION_LABELS = {
    "water_now": "Water now",
    "hold_for_rain": "Hold for rain",
    "check": "Check tomorrow",
    "wait": "No water needed",
}

BED_KEYS = (
    "name",
    "lat",
    "lon",
    "length_m",
    "width_m",
    "depth_m",
    "soil",
    "mulch",
    "crop",
    "stage",
    "kc_override",
    "method",
    "can_litres",
    "flow_lpm",
)


def _static_path(name: str) -> str | None:
    safe = os.path.normpath(name).replace("\\", "/")
    if safe.startswith("..") or os.path.isabs(safe):
        return None
    path = os.path.join(STATIC_DIR, safe)
    if not os.path.isfile(path):
        return None
    return path


def _iso_date(text, fallback: date | None = None) -> date:
    if not text:
        return fallback or date.today()
    return datetime.strptime(str(text), "%Y-%m-%d").date()


def _number(value, label: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number")
    if not (low <= number <= high):
        raise ValueError(f"{label} must be between {low:g} and {high:g}")
    return number


def bed_from_payload(payload: dict, existing: dict | None = None) -> dict:
    """Validate a create or patch request and return a complete bed record."""
    base = dict(existing or {})
    defaults = {
        "name": "Vege bed",
        "lat": -33.8688,
        "lon": 151.2093,
        "length_m": 2.4,
        "width_m": 1.2,
        "depth_m": soils.DEFAULT_DEPTH_M,
        "soil": soils.DEFAULT_SOIL,
        "mulch": soils.DEFAULT_MULCH,
        "crop": soils.DEFAULT_CROP,
        "stage": soils.DEFAULT_STAGE,
        "kc_override": None,
        "method": soils.DEFAULT_METHOD,
        "can_litres": soils.DEFAULT_CAN_LITRES,
        "flow_lpm": soils.DEFAULT_FLOW_LPM,
    }
    merged = {**defaults, **{key: base[key] for key in BED_KEYS if key in base}}
    for key in BED_KEYS:
        if key in payload:
            merged[key] = payload[key]

    name = str(merged.get("name") or "").strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("name must be 1 to 60 characters")
    merged["name"] = name
    merged["lat"] = _number(merged.get("lat"), "latitude", -90.0, 90.0)
    merged["lon"] = _number(merged.get("lon"), "longitude", -180.0, 180.0)
    merged["length_m"] = _number(merged.get("length_m"), "bed length", 0.3, 50.0)
    merged["width_m"] = _number(merged.get("width_m"), "bed width", 0.3, 50.0)
    merged["depth_m"] = _number(merged.get("depth_m"), "bed depth", 0.10, 1.0)
    merged["can_litres"] = _number(merged.get("can_litres"), "can size", 2.0, 30.0)
    merged["flow_lpm"] = _number(merged.get("flow_lpm"), "flow rate", 0.1, 20.0)

    if merged.get("soil") not in soils.SOILS:
        raise ValueError("unknown soil type")
    if merged.get("crop") not in soils.CROPS:
        raise ValueError("unknown crop")
    if merged.get("stage") not in soils.STAGES:
        raise ValueError("unknown growth stage")
    if merged.get("mulch") not in soils.MULCHES:
        raise ValueError("unknown mulch")
    if merged.get("method") not in soils.METHODS:
        raise ValueError("unknown watering method")

    override = merged.get("kc_override")
    if override in (None, "", "null"):
        merged["kc_override"] = None
    else:
        merged["kc_override"] = _number(override, "Kc override", 0.15, 1.60)
    return merged


def bed_model(row: dict) -> model.Bed:
    return model.Bed(
        name=row["name"],
        length_m=float(row["length_m"]),
        width_m=float(row["width_m"]),
        soil=row["soil"],
        mulch=row["mulch"],
        crop=row["crop"],
        stage=row["stage"],
        depth_m=float(row["depth_m"]),
        kc_override=row.get("kc_override"),
        method=row["method"],
        can_litres=float(row["can_litres"]),
        flow_lpm=float(row["flow_lpm"]),
        lat=float(row["lat"]),
        lon=float(row["lon"]),
    )


def plan_for(row: dict, today: date | None = None) -> dict:
    bed = bed_model(row)
    window = weather.load(bed.lat, bed.lon, STORE, offline=OFFLINE, today=today)
    waterings = STORE.list_waterings(row["id"], since=_window_start(window)) if STORE else []
    reading = STORE.latest_reading(row["id"]) if STORE else None
    plan = model.build_plan(bed, window, waterings, reading, today=today)
    plan["bed"]["id"] = row["id"]
    plan["bed"]["created_at"] = row.get("created_at")
    plan["bed"]["updated_at"] = row.get("updated_at")
    plan["waterings"] = waterings
    plan["reading"] = reading
    return plan


def _window_start(window: dict) -> str:
    days = window.get("days") or []
    return days[0]["date"] if days else "1970-01-01"


def _summary(row: dict) -> dict:
    bed = bed_model(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "area_m2": round(bed.area_m2, 2),
        "crop": row["crop"],
        "crop_label": bed.crop_row()["label"],
        "stage": row["stage"],
        "soil": row["soil"],
        "soil_label": bed.soil_row()["label"],
        "lat": row["lat"],
        "lon": row["lon"],
        "created_at": row.get("created_at"),
        "last_watering": None,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "waterwhen/1.0"

    # ---- helpers ---------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def log_message(self, fmt: str, *args) -> None:
        if os.environ.get("WATERWHEN_QUIET") != "1":
            super().log_message(fmt, *args)

    # ---- routes ----------------------------------------------------------
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        if path == "/api/health":
            return self._json(HTTPStatus.OK, {"ok": True, "service": "waterwhen", "version": "1.0"})
        if path == "/api/catalog":
            return self._json(HTTPStatus.OK, soils.catalog())
        if path == "/api/geocode":
            term = (query.get("q") or [""])[0]
            if not term.strip():
                return self._error(HTTPStatus.BAD_REQUEST, "query is empty")
            return self._json(HTTPStatus.OK, {"results": weather.geocode(term)})

        match = BED_PLAN.match(path)
        if match:
            return self._plan(match.group(1))
        match = BED_CARD.match(path)
        if match:
            return self._card(match.group(1))
        match = BED_PATH.match(path)
        if match:
            row = STORE.get_bed(match.group(1))
            if not row:
                return self._error(HTTPStatus.NOT_FOUND, "bed not found")
            return self._json(HTTPStatus.OK, {"bed": row})

        if path == "/api/beds":
            plans = (query.get("plans") or ["0"])[0] == "1"
            beds = []
            for row in STORE.list_beds():
                item = _summary(row)
                waterings = STORE.list_waterings(row["id"])
                if waterings:
                    item["last_watering"] = waterings[-1]
                if plans:
                    try:
                        plan = plan_for(row)
                        item["today"] = {
                            "action": plan["action"],
                            "headline": plan["headline"],
                            "litres": plan["dose"]["litres"],
                            "next_check": plan["next_check"],
                        }
                    except ValueError:
                        item["today"] = None
                beds.append(item)
            return self._json(HTTPStatus.OK, {"beds": beds})

        return self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            payload = self._body()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))

        if path == "/api/beds":
            try:
                data = bed_from_payload(payload)
            except ValueError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            row = STORE.create_bed(data)
            return self._json(HTTPStatus.CREATED, {"bed": row})

        match = BED_WATERINGS.match(path)
        if match:
            return self._add_watering(match.group(1), payload)
        match = BED_READINGS.match(path)
        if match:
            return self._add_reading(match.group(1), payload)

        return self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_PATCH(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        match = BED_PATH.match(parsed.path)
        if not match:
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        try:
            payload = self._body()
        except (ValueError, json.JSONDecodeError) as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        row = STORE.get_bed(match.group(1))
        if not row:
            return self._error(HTTPStatus.NOT_FOUND, "bed not found")
        try:
            data = bed_from_payload(payload, existing=row)
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        updated = STORE.update_bed(row["id"], data)
        return self._json(HTTPStatus.OK, {"bed": updated})

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        match = BED_WATERING.match(parsed.path)
        if match:
            if not STORE.get_bed(match.group(1)):
                return self._error(HTTPStatus.NOT_FOUND, "bed not found")
            if STORE.delete_watering(match.group(1), match.group(2)):
                return self._json(HTTPStatus.OK, {"deleted": match.group(2)})
            return self._error(HTTPStatus.NOT_FOUND, "watering not found")
        match = BED_PATH.match(parsed.path)
        if match:
            if STORE.delete_bed(match.group(1)):
                return self._json(HTTPStatus.OK, {"deleted": match.group(1)})
            return self._error(HTTPStatus.NOT_FOUND, "bed not found")
        return self._error(HTTPStatus.NOT_FOUND, "not found")

    # ---- handlers --------------------------------------------------------
    def _serve_static(self, name: str) -> None:
        path = _static_path(name)
        if not path:
            return self._error(HTTPStatus.NOT_FOUND, "file not found")
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as handle:
            body = handle.read()
        self._send(HTTPStatus.OK, body, content_type)

    def _plan(self, bed_id: str) -> None:
        row = STORE.get_bed(bed_id)
        if not row:
            return self._error(HTTPStatus.NOT_FOUND, "bed not found")
        try:
            plan = plan_for(row)
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        return self._json(HTTPStatus.OK, plan)

    def _card(self, bed_id: str) -> None:
        row = STORE.get_bed(bed_id)
        if not row:
            return self._error(HTTPStatus.NOT_FOUND, "bed not found")
        try:
            plan = plan_for(row)
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        html = render_card(plan)
        self._send(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

    def _add_watering(self, bed_id: str, payload: dict) -> None:
        if not STORE.get_bed(bed_id):
            return self._error(HTTPStatus.NOT_FOUND, "bed not found")
        try:
            day = _iso_date(payload.get("date"))
            if day > date.today():
                raise ValueError("date cannot be in the future")
            litres = _number(payload.get("litres"), "litres", 0.1, 5000.0)
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        item = STORE.add_watering(bed_id, day.isoformat(), litres, str(payload.get("note") or "")[:200])
        return self._json(HTTPStatus.CREATED, {"watering": item})

    def _add_reading(self, bed_id: str, payload: dict) -> None:
        if not STORE.get_bed(bed_id):
            return self._error(HTTPStatus.NOT_FOUND, "bed not found")
        try:
            day = _iso_date(payload.get("date"))
            if day > date.today():
                raise ValueError("date cannot be in the future")
            feel = payload.get("feel")
            value = payload.get("value")
        except ValueError as exc:
            return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        if feel not in ("dry", "moist", "wet"):
            feel = None
        if value in (None, "", "null"):
            value = None
        else:
            try:
                value = _number(value, "moisture percent", 3.0, 60.0)
            except ValueError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
        if feel is None and value is None:
            return self._error(HTTPStatus.BAD_REQUEST, "give a feel value or a moisture percent")
        item = STORE.add_reading(bed_id, day.isoformat(), feel, value, str(payload.get("note") or "")[:200])
        return self._json(HTTPStatus.CREATED, {"reading": item})


def _fmt(value, digits: int = 1) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):,.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


def _esc(text) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_card(plan: dict) -> str:
    """Render the printable A4 bed card."""
    bed = plan["bed"]
    dose = plan["dose"]
    action = plan["action"]
    outlook = plan["outlook"][:7]
    rows = []
    for day in outlook:
        label = ACTION_LABELS.get(day["action"], day["action"])
        rows.append(
            "<tr>"
            f"<td>{day['weekday']} {day['date'][5:]}</td>"
            f"<td class='num'>{day['etc']:.1f}</td>"
            f"<td class='num'>{day['rain']:.1f}</td>"
            f"<td class='num'>{day['depletion_start_mm']:.0f}</td>"
            f"<td>{label}</td>"
            "</tr>"
        )
    assumptions = "".join(f"<li>{_esc(item)}</li>" for item in plan["assumptions"])
    dose_line = f"{dose['litres']:.0f} L"
    if bed_row := plan["bed"]:
        method = soils.METHODS.get(bed_row["method"], soils.METHODS[soils.DEFAULT_METHOD])
        method_label = method["label"]
    else:
        method_label = ""

    cans = (
        f"<tr><th>Watering cans</th><td class='num'>{dose['cans']:.1f} of {bed['can_litres']:.0f} L</td></tr>"
        if method.get("cans")
        else ""
    )
    run_time = (
        f"<tr><th>Run time</th><td class='num'>{dose['run_minutes']} min at {bed['flow_lpm']:.1f} L/min</td></tr>"
        if dose.get("run_minutes")
        else ""
    )
    split = (
        f"<tr><th>Split</th><td>{_esc(dose['split_note'])}</td></tr>" if dose.get("split_note") else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Bed card — {_esc(bed['name'])}</title>
<style>
  @page {{ size: A4; margin: 15mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Segoe UI", Arial, sans-serif; color: #1d2a22; margin: 0; background: #fff; }}
  .sheet {{ max-width: 180mm; margin: 0 auto; padding: 6mm 0; }}
  header {{ display: flex; justify-content: space-between; align-items: baseline; border-bottom: 3px solid #1f4733; padding-bottom: 8px; }}
  .wordmark {{ font-size: 15px; letter-spacing: 0.16em; text-transform: uppercase; color: #1f4733; font-weight: 700; }}
  .meta {{ font-size: 11px; color: #6a756f; }}
  h1 {{ font-size: 28px; margin: 14px 0 2px; letter-spacing: -0.4px; }}
  .sub {{ color: #5b6660; font-size: 12.5px; margin: 0 0 14px; }}
  .action {{ border-left: 7px solid #b8552f; background: #f7f2e8; padding: 14px 16px; border-radius: 4px; }}
  .action.hold_for_rain {{ border-color: #3d6f8e; }}
  .action.check {{ border-color: #c08a2a; }}
  .action.wait {{ border-color: #2f6b4f; }}
  .action .label {{ font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.14em; color: #6a756f; }}
  .action .big {{ font-size: 27px; font-weight: 700; margin: 3px 0; }}
  .action .dose {{ font-size: 14px; color: #3c4a42; }}
  .reason {{ font-size: 12.5px; line-height: 1.55; color: #3c4a42; margin: 12px 0 0; }}
  h2 {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.11em; margin: 20px 0 8px; color: #1f4733; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
  th, td {{ text-align: left; padding: 6px 5px; border-bottom: 1px solid #e2e7e2; }}
  th {{ font-weight: 600; color: #4a554f; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
  .notes {{ font-size: 11.5px; color: #4a554f; line-height: 1.5; padding-left: 16px; }}
  .notes li {{ margin-bottom: 3px; }}
  footer {{ margin-top: 20px; border-top: 1px solid #d8ded9; padding-top: 7px; font-size: 10px; color: #7a857f; }}
</style>
</head>
<body>
<div class="sheet">
  <header>
    <div class="wordmark">waterwhen</div>
    <div class="meta">Bed card · {plan['today']}</div>
  </header>
  <h1>{_esc(bed['name'])}</h1>
  <p class="sub">{_esc(bed['length_m'])} x {_esc(bed['width_m'])} m · {bed['area_m2']:.2f} m2 · {_esc(method_label)}</p>

  <div class="action {action}">
    <div class="label">Today</div>
    <div class="big">{_esc(plan['headline'])}</div>
    <div class="dose">{dose_line} · {dose['applied_mm']:.0f} mm · {dose['cans']:.1f} cans</div>
  </div>
  <p class="reason">{_esc(plan['reason'])}</p>

  <h2>Dose</h2>
  <table>
    <tr><th>Applied depth</th><td class="num">{dose['applied_mm']:.1f} mm</td></tr>
    <tr><th>Litres</th><td class="num">{dose['litres']:.1f} L</td></tr>
    {cans}{run_time}{split}
    <tr><th>Next check</th><td class="num">{plan['next_check']}</td></tr>
  </table>

  <h2>Next seven days</h2>
  <table>
    <tr><th>Day</th><th class="num">ETc mm</th><th class="num">Rain mm</th><th class="num">Depletion mm</th><th>Action</th></tr>
    {''.join(rows)}
  </table>

  <div class="grid">
    <div>
      <h2>Bed model</h2>
      <table>
        <tr><th>Soil</th><td>{_esc(soils.SOILS[bed['soil']]['label'])}</td></tr>
        <tr><th>Root depth</th><td class="num">{plan['model']['root_depth_m']:.2f} m</td></tr>
        <tr><th>Crop coefficient</th><td class="num">{plan['model']['kc']:.2f}</td></tr>
        <tr><th>Water holding</th><td class="num">{plan['model']['taw_mm']:.0f} mm</td></tr>
        <tr><th>Refill point</th><td class="num">{plan['model']['refill_mm']:.0f} mm</td></tr>
        <tr><th>Depletion now</th><td class="num">{plan['model']['depletion_mm']:.0f} mm</td></tr>
      </table>
    </div>
    <div>
      <h2>Water this week</h2>
      <table>
        <tr><th>Rain</th><td class="num">{plan['summary']['rain_7d_mm']:.1f} mm</td></tr>
        <tr><th>Crop use</th><td class="num">{plan['summary']['etc_7d_mm']:.1f} mm</td></tr>
        <tr><th>Planned water</th><td class="num">{plan['summary']['irrigation_7d_litres']:.0f} L</td></tr>
        <tr><th>Season to date</th><td class="num">{plan['summary']['season_litres']:.0f} L</td></tr>
      </table>
    </div>
  </div>

  <h2>Assumptions</h2>
  <ul class="notes">{assumptions}</ul>

  <footer>
    Weather: {_esc(plan['weather']['source'])} · cell {_esc((plan['weather'].get('cell') or {}).get('lat'))}, {_esc((plan['weather'].get('cell') or {}).get('lon'))} ·
    {_esc(plan['weather']['period'][0])} to {_esc(plan['weather']['period'][1])}.
    Model: FAO-56 daily water balance. The dose is an estimate, not a promise of yield.
  </footer>
</div>
</body>
</html>"""


def create_server(host: str = "127.0.0.1", port: int = 8772, db_path: str = "data/waterwhen.db", offline: bool = False) -> ThreadingHTTPServer:
    global STORE, OFFLINE
    STORE = db.Store(db_path)
    OFFLINE = offline
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="waterwhen server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8772)
    parser.add_argument("--db", default="data/waterwhen.db")
    parser.add_argument("--offline", action="store_true", help="use modelled weather only")
    args = parser.parse_args(argv)

    server = create_server(args.host, args.port, args.db, offline=args.offline)
    print(f"waterwhen running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if STORE:
            STORE.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())