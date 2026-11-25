# PLAN — waterwhen

Spec-first build loop. Each cycle ends with a commit and a push.

## Cycle 1 — spec and scaffold

- [x] SPEC.md with acceptance criteria.
- [x] PLAN.md.
- [x] Package skeleton and SQLite store.
- [x] Soil, crop and method tables with sources.
- [x] Commit.

## Cycle 2 — model

- [x] `soils.py`: FAO-56 Table 19 texture values, Table 12 crop coefficients,
      Table 22 depletion fractions, mulch factors, application efficiencies.
- [x] `model.py`: TAW, RAW, ETc, effective rain, daily balance, dose, split rule,
      hold-for-rain rule, next check date.
- [x] Unit tests for the balance and the dose edges.
- [x] Commit.

## Cycle 3 — weather

- [x] `weather.py`: one Open-Meteo call with 14 past days and 7 forecast days.
- [x] Parse daily ET0, rain and temperature. Parse hourly soil moisture.
- [x] Three-hour SQLite cache per rounded location.
- [x] Offline fallback with a labelled synthetic climate.
- [x] Tests with recorded fixtures.
- [x] Commit.

## Cycle 4 — HTTP and storage

- [x] `db.py`: beds, waterings, readings, weather cache.
- [x] `server.py`: the API in SPEC.md, validation, static files, errors.
- [x] Tests through the HTTP seam.
- [x] Commit.

## Cycle 5 — interface

- [x] `index.html`, `styles.css`, `app.js`.
- [x] Action card, outlook table, history chart, bed form, log forms.
- [x] Responsive at 390 px.
- [x] Commit.

## Cycle 6 — printable card

- [x] A4 bed card with the action, the dose, the outlook and the assumptions.
- [x] Test that the card carries the same numbers as the plan.
- [x] Commit.

## Cycle 7 — verify against the spec

- [x] Run every acceptance criterion as a test or a manual check.
- [x] Cross-check one bed against a hand calculation.
- [x] Fix what fails.
- [x] Commit.

## Cycle 8 — assets and README

- [x] Logo through the local ComfyUI path, SVG fallback.
- [x] Real screenshots with Playwright.
- [x] README in the required structure.
- [x] Final commit and push.

## Budget

Ten cycles maximum. Stop and mark `paused` if a working prototype is not reached
by cycle 10.

## Build log

- 2026-11-26: shipped in one session, two cycles. 48 tests pass and 13 hand
  checks pass. `scripts/verify.py` compares the model against hand arithmetic.
  The local ComfyUI path produced `docs/logo.png` in 27 seconds. Playwright
  captured three real screenshots.
- Fixes during the session. A logged watering for today now reduces the start
  state, so the advice follows the action. The split rule now ignores a small
  excess over the cap, which removed a silly "next 2 mm tomorrow" note. The
  mobile layout had 178 px of horizontal overflow from the bed rail, and it is
  now zero.