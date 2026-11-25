/* waterwhen — client logic. No framework, no build step. */

const ACTION_LABELS = {
  water_now: "Water now",
  hold_for_rain: "Hold for rain",
  check: "Check tomorrow",
  wait: "No water needed",
};

const state = { catalog: null, beds: [], currentId: null, plan: null };

const $ = (selector) => document.querySelector(selector);
const stage = $("#stage");
const dialog = $("#bed-dialog");
const bedForm = $("#bed-form");

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function num(value, digits = 0) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "n/a";
  return n.toLocaleString("en-AU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function shortDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-AU", { day: "numeric", month: "short" });
}

function longDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short" });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    data = {};
  }
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

/* ---------- startup ---------- */

async function init() {
  try {
    const [catalog, beds] = await Promise.all([api("/api/catalog"), api("/api/beds?plans=1")]);
    state.catalog = catalog;
    state.beds = beds.beds;
    fillSelects();
    renderRail();
    if (state.beds.length) {
      await selectBed(state.beds[0].id);
    } else {
      renderEmpty();
    }
  } catch (error) {
    stage.innerHTML = `<div class="panel"><h2>Could not start</h2><p class="empty-note">${esc(error.message)}</p></div>`;
  }
}

function fillSelects() {
  const map = {
    soil: state.catalog.soils,
    crop: state.catalog.crops,
    stage: state.catalog.stages,
    mulch: state.catalog.mulches,
    method: state.catalog.methods,
  };
  Object.entries(map).forEach(([name, items]) => {
    const select = bedForm.querySelector(`select[name="${name}"]`);
    if (!select) return;
    select.innerHTML = items
      .map((item) => `<option value="${esc(item.key)}">${esc(item.label)}</option>`)
      .join("");
  });
}

function renderRail() {
  const list = $("#bed-list");
  list.innerHTML = state.beds
    .map((bed) => {
      const action = bed.today?.action || "unknown";
      const active = bed.id === state.currentId ? " active" : "";
      const detail = bed.today ? esc(bed.today.headline) : `${num(bed.area_m2, 1)} m²`;
      return `<li>
        <button class="bed-item${active}" data-bed="${esc(bed.id)}" type="button">
          <span class="row-1"><span class="dot ${action}"></span><span class="name">${esc(bed.name)}</span></span>
          <span class="meta">${esc(bed.crop_label)} · ${detail}</span>
        </button>
      </li>`;
    })
    .join("");
}

function renderEmpty() {
  stage.innerHTML = `<div class="empty">
    <h2>Start with one bed.</h2>
    <p>Give the app a size, a soil and a crop. It returns one dose in litres for today.</p>
    <button class="btn primary" data-act="new" type="button">Add your first bed</button>
  </div>`;
}

/* ---------- plan ---------- */

async function selectBed(id) {
  state.currentId = id;
  renderRail();
  stage.innerHTML = `<div class="panel"><p class="empty-note">Reading the weather for this bed…</p></div>`;
  try {
    const plan = await api(`/api/beds/${id}/plan`);
    state.plan = plan;
    renderPlan(plan);
  } catch (error) {
    stage.innerHTML = `<div class="panel"><h2>Could not load this bed</h2><p class="empty-note">${esc(error.message)}</p></div>`;
  }
}

function renderPlan(plan) {
  stage.innerHTML = [
    actionCard(plan),
    statsRow(plan),
    outlookPanel(plan),
    historyPanel(plan),
    detailPanel(plan),
    logsPanel(plan),
  ].join("");
}

function actionCard(plan) {
  const action = plan.action;
  const dose = plan.dose;
  const waters = action === "water_now" && dose.litres > 0;
  const bigValue = waters ? num(dose.litres, dose.litres >= 100 ? 0 : 1) : num(plan.model.depletion_mm, 0);
  const bigUnit = waters ? "L" : "mm";

  const meta = [];
  if (waters) {
    meta.push(`<div><strong>${num(dose.applied_mm, 0)} mm</strong> over ${num(plan.model.area_m2, 2)} m²</div>`);
    if (dose.cans > 0) {
      meta.push(`<div><strong>${num(dose.cans, 1)}</strong> cans of ${num(plan.bed.can_litres, 0)} L</div>`);
    }
    if (dose.run_minutes) {
      meta.push(`<div><strong>${num(dose.run_minutes, 0)} min</strong> at ${num(plan.bed.flow_lpm, 1)} L/min</div>`);
    }
  } else {
    meta.push(`<div><strong>${num(plan.model.depletion_mm, 0)} mm</strong> of ${num(plan.model.taw_mm, 0)} mm used</div>`);
    meta.push(`<div>Refill point at <strong>${num(plan.model.refill_mm, 0)} mm</strong></div>`);
  }

  const chips = [
    `<span class="chip">Next check ${esc(plan.next_check)}</span>`,
    `<span class="chip">${esc(plan.confidence.source)}</span>`,
    `<span class="chip">${esc(plan.weather.source === "open-meteo" ? "Open-Meteo forecast" : "Modelled weather")}</span>`,
  ];
  if (plan.weather.stale) chips.push(`<span class="chip warn">Stale weather cache</span>`);

  return `<article class="action-card ${action}">
    <div class="kicker">Today · ${esc(longDate(plan.today))}</div>
    <h1 class="action-title">${esc(plan.headline)}</h1>
    <div class="dose-row">
      <div class="dose-big">${bigValue}<span>${bigUnit}</span></div>
      <div class="dose-meta">${meta.join("")}</div>
    </div>
    <p class="reason">${esc(plan.reason)}</p>
    <div class="chips">${chips.join("")}</div>
  </article>`;
}

function statsRow(plan) {
  const today = plan.outlook[0] || {};
  return `<div class="stats">
    <div class="stat"><div class="k">ET0 today</div><div class="v">${num(today.et0, 1)}</div><div class="u">mm reference</div></div>
    <div class="stat"><div class="k">Rain 48 h</div><div class="v">${num(today.rain_next48, 0)}</div><div class="u">mm forecast</div></div>
    <div class="stat"><div class="k">Depletion</div><div class="v">${num(plan.model.depletion_mm, 0)}</div><div class="u">of ${num(plan.model.refill_mm, 0)} mm refill</div></div>
    <div class="stat"><div class="k">Holding</div><div class="v">${num(plan.model.taw_mm, 0)}</div><div class="u">mm total</div></div>
  </div>`;
}

function outlookPanel(plan) {
  const days = plan.outlook.slice(0, 7);
  const peak = Math.max(5, ...days.map((day) => Math.max(day.etc, day.rain)));
  const cells = days
    .map((day, index) => {
      const etHeight = Math.max(2, (day.etc / peak) * 44);
      const rainHeight = Math.max(2, (day.rain / peak) * 44);
      const label = ACTION_LABELS[day.action] || day.action;
      const todayClass = index === 0 ? " today" : "";
      return `<div class="day${todayClass}">
        <div class="dw">${esc(day.weekday)}</div>
        <div class="dd">${esc(shortDate(day.date).split(" ")[0])}</div>
        <div class="bars" title="Rain ${num(day.rain, 1)} mm, crop use ${num(day.etc, 1)} mm">
          <span class="b rain" style="height:${rainHeight.toFixed(1)}px"></span>
          <span class="b et" style="height:${etHeight.toFixed(1)}px"></span>
        </div>
        <div class="nums">ET ${num(day.etc, 1)}<br />Rain ${num(day.rain, 1)}</div>
        <div class="act ${day.action}">${esc(label)}</div>
      </div>`;
    })
    .join("");

  return `<section class="panel">
    <div class="panel-head"><h2>Next seven days</h2><span class="empty-note">Dose planned where the bed runs dry</span></div>
    <div class="outlook">${cells}</div>
    <div class="legend">
      <span><i class="swatch rain"></i>Rain</span>
      <span><i class="swatch et"></i>Crop use (ETc)</span>
    </div>
  </section>`;
}

function historyPanel(plan) {
  const rows = plan.history;
  if (!rows.length) {
    return `<section class="panel"><div class="panel-head"><h2>Last 14 days</h2></div><p class="empty-note">No history yet.</p></section>`;
  }
  return `<section class="panel">
    <div class="panel-head"><h2>Last 14 days</h2><span class="empty-note">Rebuilt backwards from today's start state</span></div>
    <div class="chart-wrap">${historyChart(rows, plan.model.taw_mm, plan.model.refill_mm)}</div>
  </section>`;
}

function historyChart(rows, taw, refill) {
  const W = 760;
  const H = 250;
  const padL = 46;
  const padR = 16;
  const padT = 18;
  const padB = 40;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const n = rows.length;
  const maxY = Math.max(taw, refill, ...rows.map((row) => row.depletion_mm)) * 1.08;
  const maxRain = Math.max(5, ...rows.map((row) => row.rain));

  const x = (index) => padL + (n <= 1 ? 0 : (index / (n - 1)) * innerW);
  const y = (value) => padT + innerH - (value / maxY) * innerH;

  const line = rows
    .map((row, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(row.depletion_mm).toFixed(1)}`)
    .join(" ");
  const area = `${line} L${x(n - 1).toFixed(1)},${(padT + innerH).toFixed(1)} L${x(0).toFixed(1)},${(padT + innerH).toFixed(1)} Z`;

  const rainBars = rows
    .map((row, index) => {
      const height = (row.rain / maxRain) * 26;
      if (height < 0.6) return "";
      return `<rect x="${(x(index) - 5).toFixed(1)}" y="${(padT + innerH - height).toFixed(1)}" width="10" height="${height.toFixed(1)}" fill="#3d6f8e" opacity="0.28" rx="1" />`;
    })
    .join("");

  const ticks = [0, refill, taw];
  const tickMarkup = ticks
    .map(
      (value) =>
        `<line x1="${padL}" y1="${y(value).toFixed(1)}" x2="${W - padR}" y2="${y(value).toFixed(1)}" stroke="#ded6c5" stroke-width="1" />
         <text x="${padL - 8}" y="${(y(value) + 4).toFixed(1)}" text-anchor="end" font-size="10.5" fill="#7c8a80">${num(value, 0)}</text>`
    )
    .join("");

  const labels = rows
    .map((row, index) => {
      if (index % 2 !== 0 && index !== n - 1) return "";
      return `<text x="${x(index).toFixed(1)}" y="${H - 14}" text-anchor="middle" font-size="10.5" fill="#7c8a80">${esc(shortDate(row.date))}</text>`;
    })
    .join("");

  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Root-zone depletion over the last 14 days">
    ${tickMarkup}
    <line x1="${padL}" y1="${y(refill).toFixed(1)}" x2="${W - padR}" y2="${y(refill).toFixed(1)}" stroke="#b8552f" stroke-width="1.2" stroke-dasharray="5 4" />
    ${rainBars}
    <path d="${area}" fill="#2f6b4f" opacity="0.10" />
    <path d="${line}" fill="none" stroke="#1f4733" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" />
    ${labels}
    <text x="${W - padR}" y="${(y(refill) - 6).toFixed(1)}" text-anchor="end" font-size="10.5" fill="#b8552f">Refill point ${num(refill, 0)} mm</text>
  </svg>`;
}

function detailPanel(plan) {
  const bed = plan.bed;
  const model = plan.model;
  return `<section class="panel">
    <div class="panel-head">
      <h2>Bed and model</h2>
      <span>
        <a class="btn small" href="/api/beds/${esc(bed.id)}/card" target="_blank" rel="noopener">Print bed card</a>
        <button class="btn small" data-act="edit" type="button">Edit bed</button>
      </span>
    </div>
    <div class="detail-grid">
      <div>
        <dl class="kv">
          <dt>Size</dt><dd>${num(bed.length_m, 1)} × ${num(bed.width_m, 1)} m · ${num(model.area_m2, 2)} m²</dd>
          <dt>Soil</dt><dd>${esc(labelFor("soils", bed.soil))}</dd>
          <dt>Mulch</dt><dd>${esc(labelFor("mulches", bed.mulch))}</dd>
          <dt>Crop</dt><dd>${esc(labelFor("crops", bed.crop))} · ${esc(labelFor("stages", bed.stage))}</dd>
          <dt>Method</dt><dd>${esc(labelFor("methods", bed.method))}</dd>
          <dt>Root depth</dt><dd>${num(model.root_depth_m, 2)} m</dd>
          <dt>Crop coefficient</dt><dd>${num(model.kc, 2)}</dd>
          <dt>Water holding</dt><dd>${num(model.taw_mm, 0)} mm</dd>
          <dt>Refill point</dt><dd>${num(model.refill_mm, 0)} mm</dd>
          <dt>Efficiency</dt><dd>${num(model.efficiency * 100, 0)}%</dd>
          <dt>Season to date</dt><dd>${num(plan.summary.season_litres, 0)} L</dd>
        </dl>
      </div>
      <div>
        <h3 style="font-family:var(--sans);font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--muted);margin-bottom:8px">Assumptions</h3>
        <ul class="assumptions">${plan.assumptions.map((item) => `<li>${esc(item)}</li>`).join("")}</ul>
      </div>
    </div>
  </section>`;
}

function labelFor(group, key) {
  const items = state.catalog?.[group] || [];
  return items.find((item) => item.key === key)?.label || key;
}

function logsPanel(plan) {
  const bed = plan.bed;
  const today = plan.today;
  const canDefault = Math.max(1, Math.round(plan.dose.litres || bed.can_litres || 9));

  const waterings = [...plan.waterings].reverse().slice(0, 8);
  const wateringList = waterings.length
    ? `<ul class="entry-list">${waterings
        .map(
          (item) => `<li class="entry">
            <span class="when">${esc(item.date)}</span>
            <span class="what">${num(item.litres, 1)} L${item.note ? ` · ${esc(item.note)}` : ""}</span>
            <button class="del" data-act="del-watering" data-id="${esc(item.id)}" title="Remove" type="button">×</button>
          </li>`
        )
        .join("")}</ul>`
    : `<p class="empty-note">No waterings logged yet.</p>`;

  return `<section class="panel">
    <div class="panel-head"><h2>Log</h2><span class="empty-note">A logged watering changes the balance</span></div>
    <div class="log-grid">
      <div>
        <form class="form-row" data-form="watering">
          <div class="inline-3">
            <label class="field"><span>Date</span><input type="date" name="date" value="${esc(today)}" max="${esc(today)}" required /></label>
            <label class="field"><span>Litres</span><input type="number" name="litres" step="0.5" min="0.1" max="5000" value="${canDefault}" required /></label>
            <label class="field wide"><span>Note</span><input type="text" name="note" maxlength="200" placeholder="Hose, 4 minutes" /></label>
          </div>
          <button class="btn primary" type="submit">Log water</button>
        </form>
        ${wateringList}
      </div>
      <div>
        <form class="form-row" data-form="reading">
          <div class="inline-2">
            <label class="field"><span>Date</span><input type="date" name="date" value="${esc(today)}" max="${esc(today)}" required /></label>
            <label class="field"><span>Finger test</span>
              <select name="feel">
                <option value="">Not sure</option>
                <option value="dry">Dry</option>
                <option value="moist">Moist</option>
                <option value="wet">Wet</option>
              </select>
            </label>
            <label class="field"><span>Moisture % (optional)</span><input type="number" name="value" step="0.1" min="3" max="60" placeholder="e.g. 18" /></label>
            <label class="field"><span>Note</span><input type="text" name="note" maxlength="200" placeholder="Sensor at 10 cm" /></label>
          </div>
          <button class="btn" type="submit">Log reading</button>
        </form>
        <p class="empty-note">A reading overrides the modelled start state for 14 days.</p>
        ${plan.reading ? `<p class="empty-note">Last reading: ${esc(plan.reading.date)} · ${esc(plan.reading.feel || `${num(plan.reading.value, 1)}%`)}</p>` : ""}
      </div>
    </div>
  </section>`;
}

/* ---------- events ---------- */

stage.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-act]");
  if (!target) return;
  const act = target.dataset.act;
  if (act === "new") return openBedForm(null);
  if (act === "edit") return openBedForm(state.plan?.bed || null);
  if (act === "del-watering") {
    const id = target.dataset.id;
    const bedId = state.plan?.bed?.id;
    if (!id || !bedId) return;
    target.disabled = true;
    try {
      await api(`/api/beds/${bedId}/waterings/${id}`, { method: "DELETE" });
      await refreshBeds();
      await selectBed(bedId);
    } catch (error) {
      alert(error.message);
    }
    return;
  }
});

stage.addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-form]");
  if (!form) return;
  event.preventDefault();
  const bedId = state.plan?.bed?.id;
  if (!bedId) return;
  const data = Object.fromEntries(new FormData(form).entries());
  const kind = form.dataset.form;
  try {
    if (kind === "watering") {
      await api(`/api/beds/${bedId}/waterings`, {
        method: "POST",
        body: JSON.stringify({ date: data.date, litres: Number(data.litres), note: data.note || "" }),
      });
    } else {
      await api(`/api/beds/${bedId}/readings`, {
        method: "POST",
        body: JSON.stringify({
          date: data.date,
          feel: data.feel || null,
          value: data.value === "" ? null : Number(data.value),
          note: data.note || "",
        }),
      });
    }
    await refreshBeds();
    await selectBed(bedId);
  } catch (error) {
    alert(error.message);
  }
});

$("#bed-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-bed]");
  if (!button) return;
  selectBed(button.dataset.bed);
});

$("#add-bed").addEventListener("click", () => openBedForm(null));

/* ---------- bed dialog ---------- */

function openBedForm(bed) {
  const isEdit = Boolean(bed?.id);
  $("#dialog-title").textContent = isEdit ? "Edit bed" : "Add a bed";
  $("#delete-bed").hidden = !isEdit;
  dialog.dataset.bedId = bed?.id || "";
  $("#form-error").textContent = "";
  $("#search-results").innerHTML = "";
  bedForm.reset();

  const defaults = state.catalog.defaults;
  const values = bed || {
    name: "",
    lat: -33.7683,
    lon: 151.0878,
    length_m: 2.4,
    width_m: 1.2,
    depth_m: defaults.depth_m,
    soil: defaults.soil,
    mulch: defaults.mulch,
    crop: defaults.crop,
    stage: defaults.stage,
    method: defaults.method,
    can_litres: defaults.can_litres,
    flow_lpm: defaults.flow_lpm,
    kc_override: "",
  };

  bedForm.name.value = values.name || "";
  bedForm.lat.value = values.lat;
  bedForm.lon.value = values.lon;
  bedForm.length_m.value = values.length_m;
  bedForm.width_m.value = values.width_m;
  bedForm.depth_m.value = values.depth_m;
  bedForm.soil.value = values.soil;
  bedForm.mulch.value = values.mulch;
  bedForm.crop.value = values.crop;
  bedForm.stage.value = values.stage;
  bedForm.method.value = values.method;
  bedForm.can_litres.value = values.can_litres;
  bedForm.flow_lpm.value = values.flow_lpm;
  bedForm.kc_override.value = values.kc_override ?? "";
  bedForm.place.value = "";

  dialog.showModal();
}

dialog.addEventListener("click", (event) => {
  if (event.target.closest("[data-close]")) dialog.close();
});

$("#search-place").addEventListener("click", async () => {
  const term = bedForm.place.value.trim();
  if (!term) return;
  const list = $("#search-results");
  list.innerHTML = `<li class="empty-note">Searching…</li>`;
  try {
    const result = await api(`/api/geocode?q=${encodeURIComponent(term)}`);
    if (!result.results.length) {
      list.innerHTML = `<li class="empty-note">No place found.</li>`;
      return;
    }
    list.innerHTML = result.results
      .map(
        (item, index) =>
          `<li><button type="button" data-place="${index}">${esc(item.name)}${item.admin ? `, ${esc(item.admin)}` : ""} · ${esc(item.country || "")}</button></li>`
      )
      .join("");
    list.querySelectorAll("[data-place]").forEach((button) => {
      button.addEventListener("click", () => {
        const item = result.results[Number(button.dataset.place)];
        bedForm.lat.value = Number(item.lat).toFixed(4);
        bedForm.lon.value = Number(item.lon).toFixed(4);
        list.innerHTML = `<li class="empty-note">Set to ${esc(item.name)}.</li>`;
      });
    });
  } catch (error) {
    list.innerHTML = `<li class="empty-note">${esc(error.message)}</li>`;
  }
});

bedForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const errorBox = $("#form-error");
  errorBox.textContent = "";
  const data = Object.fromEntries(new FormData(bedForm).entries());
  delete data.place;
  ["lat", "lon", "length_m", "width_m", "depth_m", "can_litres", "flow_lpm"].forEach((key) => {
    data[key] = Number(data[key]);
  });
  data.kc_override = data.kc_override === "" ? null : Number(data.kc_override);

  const bedId = dialog.dataset.bedId;
  try {
    if (bedId) {
      await api(`/api/beds/${bedId}`, { method: "PATCH", body: JSON.stringify(data) });
      dialog.close();
      await refreshBeds();
      await selectBed(bedId);
    } else {
      const created = await api("/api/beds", { method: "POST", body: JSON.stringify(data) });
      dialog.close();
      await refreshBeds();
      await selectBed(created.bed.id);
    }
  } catch (error) {
    errorBox.textContent = error.message;
  }
});

$("#delete-bed").addEventListener("click", async () => {
  const bedId = dialog.dataset.bedId;
  if (!bedId) return;
  if (!confirm("Delete this bed and its log?")) return;
  try {
    await api(`/api/beds/${bedId}`, { method: "DELETE" });
    dialog.close();
    state.currentId = null;
    await refreshBeds();
    if (state.beds.length) await selectBed(state.beds[0].id);
    else renderEmpty();
  } catch (error) {
    $("#form-error").textContent = error.message;
  }
});

/* ---------- refresh ---------- */

async function refreshBeds() {
  const result = await api("/api/beds?plans=1");
  state.beds = result.beds;
  if (state.currentId && !state.beds.some((bed) => bed.id === state.currentId)) {
    state.currentId = null;
  }
  renderRail();
}

init();