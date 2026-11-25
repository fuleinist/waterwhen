"""Soil, crop and application tables for the water balance.

Sources:
- FAO Irrigation and Drainage Paper 56 (Allen et al., 1998).
  Table 19: soil water characteristics (theta_fc, theta_wp).
  Table 12: single crop coefficients (Kc ini, Kc mid, Kc late).
  Table 22: depletion fraction for no stress (p).
  Table 20: maximum rooting depth ranges.
- Mulch factors and application efficiencies are documented approximations.
  They are not published FAO values. Each carries a note.
"""

from __future__ import annotations

# Volumetric water content at field capacity (fc) and wilting point (wp),
# in m3/m3. FAO-56 Table 19.
SOILS: dict[str, dict] = {
    "sand": {"label": "Sand", "fc": 0.07, "wp": 0.02, "infiltration_mm_h": 210.0},
    "loamy_sand": {"label": "Loamy sand", "fc": 0.12, "wp": 0.04, "infiltration_mm_h": 60.0},
    "sandy_loam": {"label": "Sandy loam", "fc": 0.18, "wp": 0.06, "infiltration_mm_h": 25.0},
    "loam": {"label": "Loam", "fc": 0.24, "wp": 0.11, "infiltration_mm_h": 13.0},
    "silt_loam": {"label": "Silt loam", "fc": 0.28, "wp": 0.13, "infiltration_mm_h": 13.0},
    "silt": {"label": "Silt", "fc": 0.30, "wp": 0.13, "infiltration_mm_h": 8.0},
    "sandy_clay_loam": {"label": "Sandy clay loam", "fc": 0.27, "wp": 0.17, "infiltration_mm_h": 8.0},
    "clay_loam": {"label": "Clay loam", "fc": 0.31, "wp": 0.19, "infiltration_mm_h": 5.0},
    "silty_clay_loam": {"label": "Silty clay loam", "fc": 0.32, "wp": 0.16, "infiltration_mm_h": 5.0},
    "sandy_clay": {"label": "Sandy clay", "fc": 0.33, "wp": 0.21, "infiltration_mm_h": 3.0},
    "silty_clay": {"label": "Silty clay", "fc": 0.36, "wp": 0.19, "infiltration_mm_h": 2.0},
    "clay": {"label": "Clay", "fc": 0.38, "wp": 0.24, "infiltration_mm_h": 1.0},
}

# Kc values are FAO-56 Table 12, single crop coefficient.
# root_m is a mature rooting depth, trimmed to a raised-bed range.
# p is the FAO-56 Table 22 depletion fraction for no stress.
CROPS: dict[str, dict] = {
    "tomato": {"label": "Tomato", "kc": (0.60, 1.15, 0.80), "root_m": 0.50, "p": 0.40, "group": "Fruiting"},
    "capsicum": {"label": "Capsicum", "kc": (0.60, 1.05, 0.90), "root_m": 0.40, "p": 0.25, "group": "Fruiting"},
    "chilli": {"label": "Chilli", "kc": (0.60, 1.05, 0.90), "root_m": 0.35, "p": 0.25, "group": "Fruiting"},
    "eggplant": {"label": "Eggplant", "kc": (0.60, 1.05, 0.90), "root_m": 0.45, "p": 0.45, "group": "Fruiting"},
    "cucumber": {"label": "Cucumber", "kc": (0.60, 1.00, 0.75), "root_m": 0.45, "p": 0.50, "group": "Fruiting"},
    "zucchini": {"label": "Zucchini", "kc": (0.50, 1.00, 0.75), "root_m": 0.45, "p": 0.50, "group": "Fruiting"},
    "pumpkin": {"label": "Pumpkin", "kc": (0.50, 1.00, 0.80), "root_m": 0.50, "p": 0.35, "group": "Fruiting"},
    "sweet_corn": {"label": "Sweet corn", "kc": (0.30, 1.15, 1.05), "root_m": 0.50, "p": 0.55, "group": "Fruiting"},
    "green_bean": {"label": "Green bean", "kc": (0.50, 1.05, 0.90), "root_m": 0.40, "p": 0.45, "group": "Legume"},
    "pea": {"label": "Pea", "kc": (0.50, 1.15, 1.10), "root_m": 0.35, "p": 0.35, "group": "Legume"},
    "lettuce": {"label": "Lettuce", "kc": (0.70, 1.05, 0.95), "root_m": 0.25, "p": 0.30, "group": "Leafy"},
    "spinach": {"label": "Spinach", "kc": (0.70, 1.00, 0.95), "root_m": 0.25, "p": 0.20, "group": "Leafy"},
    "silverbeet": {"label": "Silverbeet", "kc": (0.70, 1.05, 0.95), "root_m": 0.35, "p": 0.40, "group": "Leafy"},
    "kale": {"label": "Kale", "kc": (0.70, 1.05, 0.95), "root_m": 0.35, "p": 0.45, "group": "Leafy"},
    "cabbage": {"label": "Cabbage", "kc": (0.70, 1.05, 0.95), "root_m": 0.35, "p": 0.45, "group": "Brassica"},
    "broccoli": {"label": "Broccoli", "kc": (0.70, 1.05, 0.95), "root_m": 0.35, "p": 0.45, "group": "Brassica"},
    "carrot": {"label": "Carrot", "kc": (0.70, 1.05, 0.95), "root_m": 0.30, "p": 0.35, "group": "Root"},
    "beetroot": {"label": "Beetroot", "kc": (0.50, 1.05, 0.95), "root_m": 0.30, "p": 0.50, "group": "Root"},
    "onion": {"label": "Onion", "kc": (0.70, 1.05, 0.75), "root_m": 0.25, "p": 0.30, "group": "Allium"},
    "garlic": {"label": "Garlic", "kc": (0.70, 1.00, 0.70), "root_m": 0.25, "p": 0.30, "group": "Allium"},
    "potato": {"label": "Potato", "kc": (0.50, 1.15, 0.75), "root_m": 0.35, "p": 0.35, "group": "Root"},
    "strawberry": {"label": "Strawberry", "kc": (0.40, 1.05, 0.90), "root_m": 0.25, "p": 0.20, "group": "Fruiting"},
    "basil": {"label": "Basil", "kc": (0.60, 1.05, 0.90), "root_m": 0.25, "p": 0.40, "group": "Herb"},
}

# Rooting depth as a fraction of the mature depth. Growth stages follow the
# four FAO-56 crop development phases in a simplified form.
STAGES: dict[str, dict] = {
    "seedling": {"label": "Seedling", "root_fraction": 0.25, "kc_slot": "ini"},
    "vegetative": {"label": "Vegetative", "root_fraction": 0.55, "kc_slot": "dev"},
    "flowering": {"label": "Flowering", "root_fraction": 0.80, "kc_slot": "mid"},
    "harvest": {"label": "Harvest", "root_fraction": 1.00, "kc_slot": "late"},
}

# Reduction applied to ETc to account for mulch. This is an approximation: a
# mulch cuts soil evaporation, not crop transpiration.
MULCHES: dict[str, dict] = {
    "none": {"label": "No mulch", "factor": 1.00},
    "straw": {"label": "Straw", "factor": 0.85},
    "compost": {"label": "Compost", "factor": 0.90},
    "bark": {"label": "Bark chips", "factor": 0.85},
    "plastic": {"label": "Plastic film", "factor": 0.75},
    "living": {"label": "Living mulch", "factor": 0.95},
}

# Application efficiency is the share of applied water that reaches the root
# zone. These are common extension values, not FAO data.
METHODS: dict[str, dict] = {
    "can": {"label": "Watering can", "efficiency": 0.85, "cans": True, "run_time": False},
    "hose": {"label": "Hand-held hose", "efficiency": 0.85, "cans": False, "run_time": False},
    "drip": {"label": "Drip line", "efficiency": 0.90, "cans": False, "run_time": True},
    "soaker": {"label": "Soaker hose", "efficiency": 0.90, "cans": False, "run_time": True},
    "sprinkler": {"label": "Sprinkler", "efficiency": 0.75, "cans": False, "run_time": False},
}

DEFAULT_SOIL = "sandy_loam"
DEFAULT_CROP = "tomato"
DEFAULT_STAGE = "vegetative"
DEFAULT_MULCH = "straw"
DEFAULT_METHOD = "can"
DEFAULT_DEPTH_M = 0.35
DEFAULT_CAN_LITRES = 9.0
DEFAULT_FLOW_LPM = 1.0


def catalog() -> dict:
    """Return the tables the interface needs, with stable order."""
    return {
        "soils": [{"key": key, **value} for key, value in SOILS.items()],
        "crops": [
            {
                "key": key,
                "label": value["label"],
                "group": value["group"],
                "kc": list(value["kc"]),
                "root_m": value["root_m"],
                "p": value["p"],
            }
            for key, value in sorted(CROPS.items(), key=lambda item: (item[1]["group"], item[1]["label"]))
        ],
        "stages": [{"key": key, **value} for key, value in STAGES.items()],
        "mulches": [{"key": key, **value} for key, value in MULCHES.items()],
        "methods": [{"key": key, **value} for key, value in METHODS.items()],
        "defaults": {
            "soil": DEFAULT_SOIL,
            "crop": DEFAULT_CROP,
            "stage": DEFAULT_STAGE,
            "mulch": DEFAULT_MULCH,
            "method": DEFAULT_METHOD,
            "depth_m": DEFAULT_DEPTH_M,
            "can_litres": DEFAULT_CAN_LITRES,
            "flow_lpm": DEFAULT_FLOW_LPM,
        },
    }