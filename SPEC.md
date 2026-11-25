# SPEC — waterwhen

An irrigation scheduler for veggie beds. Open ET0, rain and soil moisture become
one water dose in millimetres and litres.

Status: phase 1 (spec). Owner: Repo Builder. Date: 2026-11-26.

## Problem

Watering advice is a fixed schedule that ignores the weather. A household waters
"every second morning" through a cool week and drowns the roots. Then a hot, dry
week arrives and the bed goes to wilt.

A veggie bed needs a water balance, not a timer. The inputs are public and free:
reference evapotranspiration (ET0), rainfall, and modelled soil moisture. The
output a gardener needs is one number in litres, and the date of the next check.

## Users

- A household with two to six raised veggie beds and a hand-held hose or a
  watering can. No soil sensor.
- A community garden coordinator who wants a printed weekly watering list.
- A gardener with a drip line who wants a run time in minutes, not litres.

## Solution

The user records each bed once: size, soil texture, mulch, crop, growth stage and
watering method. The app fetches a 21-day window from Open-Meteo. That window
holds 14 past days and a 7-day forecast. It runs a daily FAO-56 water balance per
bed and returns:

1. Today's action. One of `water_now`, `hold_for_rain`, `wait`, or `check`.
2. A dose in millimetres, litres and watering cans. For drip beds, a run time.
3. A reason. It names depletion, refill point, ET0 and the rain forecast.
4. The next check date.
5. A 7-day outlook. Each day shows ETc, rain, depletion and any planned dose.
6. A 14-day history. It is reconstructed backwards from the latest reading.
7. A seasonal water total from the logged waterings.

## Acceptance criteria

- A new bed returns a plan in under three seconds on a warm start, and under
  fifteen seconds on a cold start. The weather call is cached for three hours.
- The dose is zero when depletion is below the refill point (RAW).
- The dose refills to field capacity and never exceeds total available water.
- A dose above 25 mm on sandy soil is split into two applications.
- Effective rainfall is subtracted before the dose is chosen.
- When at least 70 percent of the dose is forecast within 48 hours, the action is
  `hold_for_rain`, not `water_now`.
- A finger-test reading (dry, moist or wet) overrides the modelled start state.
- The printable bed card shows the same numbers as the screen.
- All arithmetic is in SI units. 1 mm over 1 m2 is 1 litre.
- The app runs with the Python standard library only. No runtime dependencies.
- The app still returns a labelled estimate when the network is down.

## Data model

`beds` — id, name, lat, lon, length_m, width_m, soil, mulch, crop, stage,
planted_on, kc_override, method, can_litres, created_at, updated_at.

`waterings` — id, bed_id, date, litres, note, created_at.

`readings` — id, bed_id, date, feel (dry, moist, wet), value (volumetric percent,
nullable), note, created_at.

`weather_cache` — location_key, fetched_at, payload.

## Water balance

State: root-zone depletion `Dr` in millimetres. `Dr = 0` is field capacity.
`Dr = TAW` is the permanent wilting point.

```
TAW = (theta_fc - theta_wp) * 1000 * root_depth_m      [mm]
RAW = p * TAW
ETc = ET0 * Kc * mulch_factor
P_eff = max(0, P - 2.0) * 0.90                          [mm]
Dr_t = clamp(Dr_{t-1} + ETc - P_eff - I_t, 0, TAW)
```

Irrigation `I_t` is the applied depth, which is the dose divided by the
application efficiency. Rain and irrigation above field capacity are deep
percolation and are reported as a loss.

Dose:

```
deficit = Dr
applied_mm = deficit / efficiency
litres = applied_mm * area_m2
```

Split rule: a single application is capped at 25 mm on sand and loamy sand, and
at 40 mm on other soils. The remainder is scheduled for the next day.

## Soil and crop tables

Soil texture values come from FAO-56 Table 19. Crop coefficients come from
FAO-56 Table 12, single crop coefficient. Root depth by stage is an
approximation that follows the same table's rooting depth ranges. The p values
come from FAO-56 Table 22. Mulch factors are a documented approximation, not a
published standard. Each table carries its source in code.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service name and version |
| GET | `/api/catalog` | Soils, crops, stages, methods, mulches |
| GET | `/api/beds` | Bed list with last watering |
| POST | `/api/beds` | Create a bed, validated |
| PATCH | `/api/beds/{id}` | Update a bed |
| DELETE | `/api/beds/{id}` | Remove a bed and its logs |
| GET | `/api/beds/{id}/plan` | Full plan for today |
| POST | `/api/beds/{id}/waterings` | Log a watering |
| DELETE | `/api/beds/{id}/waterings/{wid}` | Remove a watering |
| POST | `/api/beds/{id}/readings` | Log a finger test or sensor value |
| GET | `/api/beds/{id}/card` | Printable bed card |
| GET | `/api/geocode?q=` | Place search through Open-Meteo |

## Interface

One page. A bed rail on the left, an action card on the right.

- The action card is the first thing on the page. It states the action in plain
  words, the litres, the cans and the reason.
- Below it: dose detail, the 7-day outlook, the 14-day history chart, the bed
  settings, and the log forms.
- A print button opens the bed card in a new tab.
- No framework. Vanilla JS, hand-drawn SVG charts.
- The layout must work at 390 px and at 1440 px.

## Out of scope

- Accounts, login and multi-user sync.
- Weather stations and soil sensors. A reading is manual.
- Fertiliser, pest and crop rotation advice.
- Evapotranspiration of a whole garden. One bed at a time.
- Automation of a valve or a pump.

## Risks

- Open-Meteo soil moisture is a modelled 5 to 25 km grid, not a bed sensor. It
  seeds the balance and the user can correct it with a finger test.
- Rainfall is uneven. The app shows the grid cell and the forecast source.
- A crop coefficient table cannot know a cultivar. The user can override Kc.
- The model must never promise a harvest. It returns a water dose.

## Success metric

A household cuts outdoor water use by 20 percent with no crop loss. The check:
the dose stays within 15 percent of a soil-moisture sensor reading on the same
bed over four weeks.