"""Daily water balance and irrigation dose for one veggie bed.

The model follows FAO-56 in a simplified daily form:

    TAW  = (theta_fc - theta_wp) * 1000 * root_depth_m
    RAW  = p * TAW
    ETc  = ET0 * Kc * mulch_factor
    Peff = max(0, rain - 2.0) * 0.90
    Dr_t = clamp(Dr_{t-1} + ETc - Peff - I_t, 0, TAW)

Dr is root-zone depletion in millimetres. Dr = 0 is field capacity.
Dr = TAW is the permanent wilting point.
One millimetre over one square metre is one litre.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from . import soils

# A single application is capped by texture. A large dose on sand leaches past
# the root zone. Values follow common extension guidance.
SPLIT_CAP_MM = {"sand": 25.0, "loamy_sand": 25.0}
SPLIT_CAP_DEFAULT_MM = 40.0

# Rain below this depth is intercepted and never reaches the root zone.
RAIN_ABSTENTION_MM = 2.0
RAIN_EFFICIENCY = 0.90

# The action band below the refill point that earns a "check" rather than a
# "wait". It keeps the gardener from being surprised.
CHECK_BAND = 0.75

# If this share of the deficit is forecast in the next 48 hours, hold.
HOLD_FOR_RAIN = 0.70


@dataclass
class Bed:
    name: str
    length_m: float
    width_m: float
    soil: str = soils.DEFAULT_SOIL
    mulch: str = soils.DEFAULT_MULCH
    crop: str = soils.DEFAULT_CROP
    stage: str = soils.DEFAULT_STAGE
    depth_m: float = soils.DEFAULT_DEPTH_M
    kc_override: float | None = None
    method: str = soils.DEFAULT_METHOD
    can_litres: float = soils.DEFAULT_CAN_LITRES
    flow_lpm: float = soils.DEFAULT_FLOW_LPM
    lat: float = -33.8688
    lon: float = 151.2093

    @property
    def area_m2(self) -> float:
        return self.length_m * self.width_m

    def soil_row(self) -> dict:
        return soils.SOILS.get(self.soil, soils.SOILS[soils.DEFAULT_SOIL])

    def crop_row(self) -> dict:
        return soils.CROPS.get(self.crop, soils.CROPS[soils.DEFAULT_CROP])

    def stage_row(self) -> dict:
        return soils.STAGES.get(self.stage, soils.STAGES[soils.DEFAULT_STAGE])

    def mulch_row(self) -> dict:
        return soils.MULCHES.get(self.mulch, soils.MULCHES[soils.DEFAULT_MULCH])

    def method_row(self) -> dict:
        return soils.METHODS.get(self.method, soils.METHODS[soils.DEFAULT_METHOD])

    def root_depth_m(self) -> float:
        mature = float(self.crop_row()["root_m"])
        fraction = float(self.stage_row()["root_fraction"])
        return max(0.10, min(self.depth_m, mature * fraction))

    def kc(self) -> float:
        if self.kc_override is not None:
            return max(0.15, min(1.60, float(self.kc_override)))
        ini, mid, late = self.crop_row()["kc"]
        slot = self.stage_row()["kc_slot"]
        if slot == "ini":
            return float(ini)
        if slot == "dev":
            return float((ini + mid) / 2.0)
        if slot == "mid":
            return float(mid)
        return float(late)

    def taw_mm(self) -> float:
        row = self.soil_row()
        return (float(row["fc"]) - float(row["wp"])) * 1000.0 * self.root_depth_m()

    def raw_mm(self) -> float:
        return float(self.crop_row()["p"]) * self.taw_mm()

    def efficiency(self) -> float:
        return float(self.method_row()["efficiency"])

    def split_cap_mm(self) -> float:
        return SPLIT_CAP_MM.get(self.soil, SPLIT_CAP_DEFAULT_MM)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "length_m": self.length_m,
            "width_m": self.width_m,
            "area_m2": round(self.area_m2, 3),
            "soil": self.soil,
            "mulch": self.mulch,
            "crop": self.crop,
            "stage": self.stage,
            "depth_m": self.depth_m,
            "kc_override": self.kc_override,
            "method": self.method,
            "can_litres": self.can_litres,
            "flow_lpm": self.flow_lpm,
            "lat": self.lat,
            "lon": self.lon,
        }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def effective_rain(rain_mm: float | None) -> float:
    if not rain_mm or rain_mm <= RAIN_ABSTENTION_MM:
        return 0.0
    return (float(rain_mm) - RAIN_ABSTENTION_MM) * RAIN_EFFICIENCY


def crop_et(et0_mm: float | None, kc: float, mulch_factor: float) -> float:
    if not et0_mm or et0_mm < 0:
        return 0.0
    return float(et0_mm) * kc * mulch_factor


def dose_for(bed: Bed, deficit_mm: float) -> dict:
    """Turn a root-zone deficit into an applied depth, litres and a split."""
    if deficit_mm <= 0:
        return {
            "deficit_mm": 0.0,
            "applied_mm": 0.0,
            "litres": 0.0,
            "cans": 0.0,
            "run_minutes": None,
            "split_count": 1,
            "split_note": "",
        }

    efficiency = bed.efficiency()
    cap = bed.split_cap_mm()
    needed_mm = deficit_mm / efficiency
    # Only split when the excess is large. A 42 mm dose against a 40 mm cap is
    # not worth a second trip with the watering can.
    if needed_mm > cap * 1.25:
        split_count = max(1, math.ceil(needed_mm / cap - 1e-9))
        applied_mm = cap
    else:
        split_count = 1
        applied_mm = needed_mm
    litres = applied_mm * bed.area_m2
    cans = litres / bed.can_litres if bed.can_litres else 0.0

    split_note = ""
    if split_count > 1:
        remainder = needed_mm - applied_mm
        split_note = (
            f"Split into {split_count} applications of about {applied_mm:.0f} mm. "
            f"The next {remainder:.0f} mm goes on tomorrow."
        )

    run_minutes = None
    if bed.method_row().get("run_time") and bed.flow_lpm:
        run_minutes = round(litres / bed.flow_lpm)

    return {
        "deficit_mm": round(deficit_mm, 2),
        "applied_mm": round(applied_mm, 2),
        "litres": round(litres, 1),
        "cans": round(cans, 1),
        "run_minutes": run_minutes,
        "split_count": split_count,
        "split_note": split_note,
    }


def _index_of(days: list[dict], today: date) -> int:
    stamp = today.isoformat()
    for index, day in enumerate(days):
        if day["date"] == stamp:
            return index
    # Fall back to the first day on or after today.
    for index, day in enumerate(days):
        if day["date"] > stamp:
            return max(0, index - 1)
    return max(0, len(days) - 1)


def _watering_depths(bed: Bed, waterings: list[dict]) -> dict[str, float]:
    depths: dict[str, float] = {}
    for item in waterings:
        litres = float(item.get("litres") or 0.0)
        if litres <= 0 or bed.area_m2 <= 0:
            continue
        depth = litres / bed.area_m2
        depths[item["date"]] = depths.get(item["date"], 0.0) + depth
    return depths


def _reading_depletion(bed: Bed, reading: dict | None) -> tuple[float | None, str | None]:
    if not reading:
        return None, None
    taw = bed.taw_mm()
    if reading.get("value") is not None:
        theta = float(reading["value"]) / 100.0
        fc = float(bed.soil_row()["fc"])
        depth_mm = 1000.0 * bed.root_depth_m()
        return clamp((fc - theta) * depth_mm, 0.0, taw), "sensor"
    feel = reading.get("feel")
    fraction = {"dry": 0.85, "moist": 0.45, "wet": 0.15}.get(feel)
    if fraction is None:
        return None, None
    return fraction * taw, "finger test"


def initial_depletion(bed: Bed, weather: dict, reading: dict | None) -> dict:
    """Pick the starting depletion for today and say where it came from."""
    value, source = _reading_depletion(bed, reading)
    if value is not None:
        return {
            "mm": value,
            "source": source,
            "label": f"Set from the latest {source} reading.",
        }

    soil = weather.get("soil") or {}
    surface = soil.get("moisture_0_7")
    deeper = soil.get("moisture_7_28")
    taw = bed.taw_mm()
    if surface is not None and deeper is not None:
        theta = 0.4 * float(surface) + 0.6 * float(deeper)
        depth_mm = 1000.0 * bed.root_depth_m()
        fc = float(bed.soil_row()["fc"])
        return {
            "mm": clamp((fc - theta) * depth_mm, 0.0, taw),
            "source": "modelled soil moisture",
            "label": "Seeded from the Open-Meteo soil moisture grid.",
        }
    if surface is not None:
        theta = float(surface)
        depth_mm = 1000.0 * bed.root_depth_m()
        fc = float(bed.soil_row()["fc"])
        return {
            "mm": clamp((fc - theta) * depth_mm, 0.0, taw),
            "source": "modelled soil moisture",
            "label": "Seeded from the Open-Meteo surface soil moisture.",
        }
    return {
        "mm": 0.5 * bed.raw_mm(),
        "source": "assumed",
        "label": "No reading and no soil moisture. Start at half the refill point.",
    }


def build_plan(bed: Bed, weather: dict, waterings: list[dict], reading: dict | None, today: date | None = None) -> dict:
    """Run the balance and return today's action, the outlook and the history."""
    days = weather.get("days") or []
    if not days:
        raise ValueError("weather has no days")
    today = today or date.today()
    index = _index_of(days, today)

    taw = bed.taw_mm()
    raw = bed.raw_mm()
    kc = bed.kc()
    mulch = float(bed.mulch_row()["factor"])
    efficiency = bed.efficiency()
    depths = _watering_depths(bed, waterings)
    start = initial_depletion(bed, weather, reading)
    dr = clamp(start["mm"], 0.0, taw)

    # Water already logged for today is in the soil now. Take it off the start
    # state so the advice reflects what the gardener has done.
    irrigation_today = depths.get(today.isoformat(), 0.0)
    if irrigation_today:
        dr = clamp(dr - irrigation_today, 0.0, taw)

    # Walk backwards from today to reconstruct the past 14 days.
    history: list[dict] = []
    cursor = dr
    for position in range(index - 1, -1, -1):
        day = days[position]
        etc = crop_et(day.get("et0"), kc, mulch)
        rain = effective_rain(day.get("rain"))
        irrigation = depths.get(day["date"], 0.0)
        cursor = clamp(cursor - etc + rain + irrigation, 0.0, taw)
        history.append(
            {
                "date": day["date"],
                "et0": round(float(day.get("et0") or 0.0), 2),
                "etc": round(etc, 2),
                "rain": round(float(day.get("rain") or 0.0), 2),
                "effective_rain": round(rain, 2),
                "irrigation_mm": round(irrigation, 2),
                "depletion_mm": round(cursor, 2),
                "refill_mm": round(raw, 2),
                "taw_mm": round(taw, 2),
            }
        )
    history.reverse()

    # Walk forward from today. The first row is the action for today.
    outlook: list[dict] = []
    cursor = dr
    today_row: dict | None = None
    for position in range(index, len(days)):
        day = days[position]
        etc = crop_et(day.get("et0"), kc, mulch)
        rain = effective_rain(day.get("rain"))
        rain_next48 = sum(max(0.0, float(item.get("rain") or 0.0)) for item in days[position:position + 2])
        irrigation = 0.0
        logged_mm = irrigation_today if position == index else 0.0

        deficit = max(0.0, cursor - 0.25)
        action = "wait"
        dose = dose_for(bed, 0.0)
        if deficit >= raw and position == index:
            if rain_next48 >= HOLD_FOR_RAIN * deficit:
                action = "hold_for_rain"
            else:
                action = "water_now"
                dose = dose_for(bed, deficit)
        elif deficit >= raw:
            action = "water_now"
            dose = dose_for(bed, deficit)
        elif deficit >= CHECK_BAND * raw:
            action = "check"

        applied = dose["applied_mm"] if action == "water_now" else 0.0
        net = min(applied * efficiency, deficit) if applied else 0.0
        # A logged watering on any day is applied water, not a dose.
        applied_total = net + irrigation
        end = clamp(cursor + etc - rain - applied_total, 0.0, taw)
        percolation = max(0.0, cursor + etc - rain - applied_total - taw)

        row = {
            "date": day["date"],
            "weekday": datetime.fromisoformat(day["date"]).strftime("%a"),
            "et0": round(float(day.get("et0") or 0.0), 2),
            "kc": round(kc, 2),
            "etc": round(etc, 2),
            "rain": round(float(day.get("rain") or 0.0), 2),
            "effective_rain": round(rain, 2),
            "rain_next48": round(rain_next48, 1),
            "depletion_start_mm": round(cursor, 2),
            "depletion_end_mm": round(end, 2),
            "refill_mm": round(raw, 2),
            "taw_mm": round(taw, 2),
            "action": action,
            "dose": dose,
            "applied_mm": round(applied, 2),
            "irrigation_mm": round(logged_mm, 2),
            "percolation_mm": round(percolation, 2),
            "logged": position == index and logged_mm > 0,
        }
        outlook.append(row)
        if position == index:
            today_row = row
        cursor = end

    today_row = today_row or outlook[0]

    # Next check: the first future day that reaches the refill point.
    next_check = None
    for row in outlook[1:]:
        if row["depletion_start_mm"] >= raw:
            next_check = row["date"]
            break
    if next_check is None:
        fallback = today + timedelta(days=3)
        last_date = datetime.fromisoformat(outlook[-1]["date"]).date()
        next_check = min(fallback, last_date).isoformat()

    season_litres = 0.0
    for item in waterings:
        try:
            if datetime.fromisoformat(item["date"]).year == today.year:
                season_litres += float(item.get("litres") or 0.0)
        except ValueError:
            continue

    total_rain = sum(row["rain"] for row in outlook)
    total_et = sum(row["etc"] for row in outlook)
    irrigation_week = sum(row["applied_mm"] for row in outlook) * bed.area_m2
    percolation = sum(row["percolation_mm"] for row in outlook)

    action = today_row["action"]
    dose = today_row["dose"]
    plan = {
        "bed": bed.to_dict(),
        "today": today.isoformat(),
        "action": action,
        "headline": headline(action, bed, dose, today_row),
        "dose": dose,
        "reason": reason(action, bed, today_row, dose, raw, taw),
        "next_check": next_check,
        "confidence": start,
        "model": {
            "area_m2": round(bed.area_m2, 3),
            "root_depth_m": round(bed.root_depth_m(), 3),
            "kc": round(kc, 2),
            "mulch_factor": mulch,
            "efficiency": round(efficiency, 2),
            "taw_mm": round(taw, 1),
            "refill_mm": round(raw, 1),
            "soil_fc": float(bed.soil_row()["fc"]),
            "soil_wp": float(bed.soil_row()["wp"]),
            "depletion_mm": round(dr, 1),
            "split_cap_mm": bed.split_cap_mm(),
        },
        "summary": {
            "rain_7d_mm": round(total_rain, 1),
            "etc_7d_mm": round(total_et, 1),
            "irrigation_7d_litres": round(irrigation_week, 1),
            "percolation_7d_mm": round(percolation, 1),
            "season_litres": round(season_litres, 1),
        },
        "outlook": outlook,
        "history": history,
        "assumptions": assumptions(bed, weather, start),
        "weather": {
            "source": weather.get("source", "unknown"),
            "stale": weather.get("stale", False),
            "cell": weather.get("cell"),
            "fetched_at": weather.get("fetched_at"),
            "timezone": weather.get("timezone"),
            "period": [days[0]["date"], days[-1]["date"]],
        },
    }
    return plan


def headline(action: str, bed: Bed, dose: dict, row: dict) -> str:
    if action == "water_now":
        return f"Water {dose['litres']:.0f} L today"
    if action == "hold_for_rain":
        return "Hold for rain"
    if action == "check":
        return "Check tomorrow"
    return "No water needed"


def reason(action: str, bed: Bed, row: dict, dose: dict, raw: float, taw: float) -> str:
    """One short reason. Plain words, active voice, no filler."""
    depletion = row["depletion_start_mm"]
    etc = row["etc"]
    rain = row["rain"]
    rain48 = row["rain_next48"]

    if action == "water_now":
        text = (
            f"Root-zone depletion is {depletion:.0f} mm. "
            f"The refill point is {raw:.0f} mm. "
            f"Crop use today is {etc:.1f} mm and rain in the next 48 hours is {rain48:.0f} mm."
        )
        if dose.get("split_note"):
            text += " " + dose["split_note"]
        return text
    if action == "hold_for_rain":
        return (
            f"Depletion is {depletion:.0f} mm and rain of {rain48:.0f} mm is forecast within 48 hours. "
            f"Holding saves the dose. Check the bed after the rain."
        )
    if action == "check":
        return (
            f"Depletion is {depletion:.0f} mm against a refill point of {raw:.0f} mm. "
            f"Crop use today is {etc:.1f} mm. Check the bed tomorrow."
        )
    return (
        f"Depletion is {depletion:.0f} mm against a refill point of {raw:.0f} mm. "
        f"Water holding capacity is {taw:.0f} mm. No water is needed today."
    )


def assumptions(bed: Bed, weather: dict, start: dict) -> list[str]:
    soil = bed.soil_row()
    crop = bed.crop_row()
    method = bed.method_row()
    items = [
        f"Bed area {bed.area_m2:.2f} m2 and root depth {bed.root_depth_m():.2f} m.",
        f"Soil {soil['label']} at field capacity {soil['fc']:.2f} and wilting point {soil['wp']:.2f}.",
        f"Crop coefficient Kc {bed.kc():.2f} for {crop['label']} at the {bed.stage_row()['label'].lower()} stage.",
        f"Application efficiency {bed.efficiency() * 100:.0f} percent for a {method['label'].lower()}.",
        f"Rain below {RAIN_ABSTENTION_MM:.0f} mm is ignored. The rest is {RAIN_EFFICIENCY * 100:.0f} percent effective.",
        f"Mulch factor {bed.mulch_row()['factor']:.2f}. A mulch cuts soil evaporation, not crop use.",
        start["label"],
    ]
    if weather.get("source") != "open-meteo":
        items.append("Weather is modelled. Treat the dose as an estimate.")
    if weather.get("stale"):
        items.append("The weather cache is stale. The last good forecast is in use.")
    return items