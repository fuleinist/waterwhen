"""Open-Meteo weather and soil moisture for one location.

One request returns 14 past days and 7 forecast days. The parsed result holds
daily ET0, rain and temperature, plus the current modelled soil moisture.

The response is cached in SQLite for three hours per rounded location. When the
network is down, the last good forecast is used and marked stale. With no cache
at all, a labelled synthetic climate keeps the app usable.
"""

from __future__ import annotations

import bisect
import json
import math
import random
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

BASE_URL = "https://api.open-meteo.com/v1/forecast"
PAST_DAYS = 14
FORECAST_DAYS = 7
CACHE_HOURS = 3
TIMEOUT_SECONDS = 20
USER_AGENT = "waterwhen/1.0"

DAILY_FIELDS = [
    "et0_fao_evapotranspiration",
    "precipitation_sum",
    "temperature_2m_max",
    "temperature_2m_min",
]
HOURLY_FIELDS = [
    "soil_moisture_0_to_7cm",
    "soil_moisture_7_to_28cm",
    "soil_temperature_6cm",
]


def location_key(lat: float, lon: float) -> str:
    return f"{lat:.2f},{lon:.2f}"


def _request(lat: float, lon: float) -> dict:
    params = {
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "daily": ",".join(DAILY_FIELDS),
        "hourly": ",".join(HOURLY_FIELDS),
        "timezone": "auto",
        "past_days": PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
    }
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _number(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _soil_now(payload: dict) -> dict | None:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return None
    offset = int(payload.get("utc_offset_seconds") or 0)
    local_now = datetime.now(timezone.utc) + timedelta(seconds=offset)
    stamp = local_now.strftime("%Y-%m-%dT%H:00")
    index = bisect.bisect_right(times, stamp) - 1
    if index < 0:
        index = 0

    def at(name: str):
        values = hourly.get(name) or []
        return _number(values[index]) if index < len(values) else None

    soil = {
        "moisture_0_7": at("soil_moisture_0_to_7cm"),
        "moisture_7_28": at("soil_moisture_7_to_28cm"),
        "temperature_6cm": at("soil_temperature_6cm"),
        "time": times[index] if index < len(times) else None,
    }
    if soil["moisture_0_7"] is None and soil["moisture_7_28"] is None:
        return None
    return soil


def parse(payload: dict) -> dict:
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    series = {name: daily.get(name) or [] for name in DAILY_FIELDS}
    days = []
    for index, day in enumerate(times):
        days.append(
            {
                "date": day,
                "et0": _number(series["et0_fao_evapotranspiration"][index])
                if index < len(series["et0_fao_evapotranspiration"])
                else None,
                "rain": _number(series["precipitation_sum"][index])
                if index < len(series["precipitation_sum"])
                else None,
                "tmax": _number(series["temperature_2m_max"][index])
                if index < len(series["temperature_2m_max"])
                else None,
                "tmin": _number(series["temperature_2m_min"][index])
                if index < len(series["temperature_2m_min"])
                else None,
            }
        )
    if not days:
        raise ValueError("Open-Meteo returned no daily data")
    return {
        "source": "open-meteo",
        "stale": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timezone": payload.get("timezone"),
        "cell": {
            "lat": _number(payload.get("latitude")),
            "lon": _number(payload.get("longitude")),
            "elevation": _number(payload.get("elevation")),
        },
        "days": days,
        "soil": _soil_now(payload),
    }


def modelled(lat: float, lon: float, today: date | None = None) -> dict:
    """A labelled synthetic climate. It keeps the app usable with no network."""
    today = today or date.today()
    start = today - timedelta(days=PAST_DAYS)
    # Southern hemisphere peaks near 21 December. Northern hemisphere near 21 June.
    peak_day = 355.0 if lat < 0 else 172.0
    latitude_scale = max(0.45, min(1.25, math.cos(math.radians(abs(lat))) * 1.35))
    days = []
    for offset in range(PAST_DAYS + FORECAST_DAYS):
        current = start + timedelta(days=offset)
        doy = current.timetuple().tm_yday
        seasonal = math.cos(2.0 * math.pi * (doy - peak_day) / 365.25)
        et0 = max(0.4, (4.0 + 2.4 * seasonal) * latitude_scale)
        rng = random.Random(int(current.strftime("%Y%m%d")))
        wet = rng.random() < 0.30
        rain = round(rng.uniform(1.0, 16.0), 1) if wet else 0.0
        days.append(
            {
                "date": current.isoformat(),
                "et0": round(et0, 2),
                "rain": rain,
                "tmax": round(22.0 + 6.0 * seasonal, 1),
                "tmin": round(12.0 + 3.0 * seasonal, 1),
            }
        )
    return {
        "source": "modelled",
        "stale": False,
        "fetched_at": None,
        "timezone": None,
        "cell": {"lat": round(lat, 4), "lon": round(lon, 4), "elevation": None},
        "days": days,
        "soil": None,
    }


def load(lat: float, lon: float, store=None, offline: bool = False, today: date | None = None) -> dict:
    """Return a weather window, from cache, network or a modelled fallback."""
    key = location_key(lat, lon)
    cached = store.weather_get(key) if store else None

    if not offline and cached and cached.get("age_hours", 999) < CACHE_HOURS:
        try:
            parsed = parse(cached["payload"])
            parsed["fetched_at"] = cached["fetched_at"]
            parsed["cached"] = True
            return parsed
        except (ValueError, KeyError):
            pass

    if not offline:
        try:
            payload = _request(lat, lon)
            parsed = parse(payload)
            if store:
                store.weather_put(key, payload)
            return parsed
        except Exception:
            if cached:
                try:
                    parsed = parse(cached["payload"])
                    parsed["stale"] = True
                    parsed["fetched_at"] = cached["fetched_at"]
                    parsed["cached"] = True
                    return parsed
                except (ValueError, KeyError):
                    pass

    if cached:
        try:
            parsed = parse(cached["payload"])
            parsed["stale"] = True
            parsed["fetched_at"] = cached["fetched_at"]
            parsed["cached"] = True
            return parsed
        except (ValueError, KeyError):
            pass

    return modelled(lat, lon, today=today)


def geocode(term: str) -> list[dict]:
    """Search a place name through the Open-Meteo geocoder."""
    term = (term or "").strip()
    if not term:
        return []
    params = {"name": term, "count": "5", "language": "en", "format": "json"}
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    return [
        {
            "name": item.get("name"),
            "admin": item.get("admin1"),
            "country": item.get("country_code"),
            "lat": item.get("latitude"),
            "lon": item.get("longitude"),
        }
        for item in (payload.get("results") or [])
    ]