// antilles-atlas map client.
//
// Reads only from the API:
//   GET /geometries?as_of=YEAR   polygons whose claim's when_range contains YEAR
//   GET /claims                  every claim, for the list
//   GET /claims/{key}            one claim with attachments, transmission, relations
//
// The client computes nothing about evidence. sourcing_status arrives from the
// server (app/sourcing.py) so Phase 5 can replace it without touching this file.

const STATUS = {
  sourced:  { color: "#24507a", label: "Sourced" },
  unproven: { color: "#a8661b", label: "Unproven" },
  pending:  { color: "#8b979b", label: "Pending" },
};

const yearInput = document.getElementById("year");
const body = document.getElementById("panel-body");
const emptyNote = document.getElementById("map-empty");

let allClaims = [];
let onMap = new Set();   // claim keys with a polygon at the current year

// ---------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------

// Everything from the database goes through esc() before it touches innerHTML.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
));

const words = (s) => (s ?? "").replaceAll("_", " ");

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} returned ${r.status}`);
  return r.json();
}

function statusTag(s) {
  return `<span class="status ${esc(s)}">${esc(STATUS[s]?.label ?? s)}</span>`;
}

// ---------------------------------------------------------------------------
// map
// ---------------------------------------------------------------------------

const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
        tileSize: 256,
        attribution: "© OpenStreetMap contributors",
      },
    },
    // Desaturated so the status colors are the only color that carries meaning.
    layers: [{ id: "osm", type: "raster", source: "osm",
               paint: { "raster-saturation": -1, "raster-opacity": 0.55 } }],
  },
  center: [-71.6, 18.9],   // Hispaniola
  zoom: 6.6,
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");

const byStatus = (s) => ["==", ["get", "sourcing_status"], s];

map.on("load", () => {
  map.addSource("boundaries", { type: "geojson", data: { type: "FeatureCollection", features: [] } });

  map.addLayer({
    id: "boundary-fill", type: "fill", source: "boundaries",
    paint: {
      "fill-color": ["match", ["get", "sourcing_status"],
        "sourced", STATUS.sourced.color, "unproven", STATUS.unproven.color, STATUS.pending.color],
      "fill-opacity": ["match", ["get", "sourcing_status"], "sourced", 0.16, 0.08],
    },
  });

  // One line layer per status. line-dasharray can't be data-driven in
  // MapLibre 4, so the dash pattern is chosen by filter instead of by expression.
  const lines = { sourced: [1, 0], unproven: [3, 2], pending: [0.6, 1.6] };
  for (const [s, dash] of Object.entries(lines)) {
    map.addLayer({
      id: `boundary-line-${s}`, type: "line", source: "boundaries", filter: byStatus(s),
      paint: { "line-color": STATUS[s].color, "line-width": 2, "line-dasharray": dash },
    });
  }

  // Click: competing interpretations overlap, so one click can hit several
  // polygons. One hit opens the claim; several list them all.
  map.on("click", "boundary-fill", (e) => {
    const keys = [...new Set(e.features.map((f) => f.properties.claim))];
    if (keys.length === 1) showClaim(keys[0]);
    else showList(keys, `${keys.length} boundary claims overlap here`);
  });
  map.on("mouseenter", "boundary-fill", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "boundary-fill", () => (map.getCanvas().style.cursor = ""));

  loadYear();
});

async function loadYear() {
  const year = Number(yearInput.value);
  if (!Number.isInteger(year)) return;
  let fc;
  try {
    fc = await getJSON(`/geometries?as_of=${year}`);
  } catch (err) {
    emptyNote.textContent = `Couldn't load boundaries: ${err.message}. Check that the API is running.`;
    emptyNote.hidden = false;
    return;
  }
  map.getSource("boundaries")?.setData(fc);
  onMap = new Set(fc.features.map((f) => f.properties.claim));

  if (fc.features.length === 0) {
    emptyNote.textContent =
      `No boundary claims cover ${year}. Polygons load from seed/geo/*.geojson with make load-seed.`;
    emptyNote.hidden = false;
  } else {
    emptyNote.hidden = true;
  }
  // Refresh the "on map" marks if the list is showing.
  if (body.dataset.view === "list") showList();
}

// ---------------------------------------------------------------------------
// year control
// ---------------------------------------------------------------------------

let yearTimer;
yearInput.addEventListener("input", () => {
  clearTimeout(yearTimer);
  yearTimer = setTimeout(loadYear, 250);
});
function stepYear(d) {
  const min = Number(yearInput.min), max = Number(yearInput.max);
  yearInput.value = Math.min(max, Math.max(min, Number(yearInput.value) + d));
  loadYear();
}
document.getElementById("year-prev").addEventListener("click", () => stepYear(-1));
document.getElementById("year-next").addEventListener("click", () => stepYear(1));

// ---------------------------------------------------------------------------
// panel: list
// ---------------------------------------------------------------------------

function showList(onlyKeys = null, heading = null) {
  body.dataset.view = onlyKeys ? "subset" : "list";
  const claims = onlyKeys ? allClaims.filter((c) => onlyKeys.includes(c.key)) : allClaims;
  const head = heading ?? `${allClaims.length} claims`;

  body.innerHTML = `
    ${onlyKeys ? `<button type="button" class="back" data-back>All claims</button>` : ""}
    <p class="list-head">${esc(head)}</p>
    <ul class="claim-list">
      ${claims.map((c) => `
        <li class="claim-item">
          <button type="button" data-claim="${esc(c.key)}">
            <span class="claim-meta">
              <span class="claim-key">${esc(c.key)}</span>
              ${statusTag(c.sourcing_status)}
              <span>${esc(words(c.kind))}</span>
              ${onMap.has(c.key) ? `<span class="on-map">on map</span>` : ""}
            </span>
            <span class="assertion-short">${esc(c.assertion)}</span>
          </button>
        </li>`).join("")}
    </ul>`;
}

// ---------------------------------------------------------------------------
// panel: claim detail
// ---------------------------------------------------------------------------

function dim(label, value, ifNull) {
  // What null MEANS differs by field. For access/proximity it's "not
  // applicable" (models.ClaimSource docstring); for locus it's just not entered.
  const v = value == null ? `<span class="na">${ifNull}</span>` : esc(words(value));
  return `<dt>${label}</dt><dd>${v}</dd>`;
}

function attachmentHTML(a) {
  const s = a.source;
  const chain = a.transmission.length
    ? `<ul class="chain" aria-label="Transmission">
         ${a.transmission.map((e) =>
           `<li>${esc(e.derived)} <span class="kind">${esc(words(e.kind))} of</span> ${esc(e.origin)}</li>`).join("")}
       </ul>`
    : "";
  return `
    <div class="attachment">
      <div><span class="who">${esc(s.author ?? s.key)}</span> <span class="role">${esc(words(a.role))}</span></div>
      <div class="title">${esc(s.title)}${s.composed_label ? `, ${esc(s.composed_label)}` : ""}${s.original_extant ? "" : " (original lost)"}</div>
      <dl class="dims">
        ${dim("Evidence", a.evidence_type, "not recorded")}
        ${dim("Access", a.access, "not applicable")}
        ${dim("Proximity", a.proximity, "not applicable")}
        ${dim("Locus", a.locus, "not recorded")}
      </dl>
      ${chain}
      ${a.notes ? `<p class="notes attachment-notes">${esc(a.notes.trim())}</p>` : ""}
    </div>`;
}

// ---------------------------------------------------------------------------
// panel: evidence profile (Phase 5). One meter per dimension, never a total.
// ---------------------------------------------------------------------------

// Best first, matching the enum order in models.py.
const PROXIMITY = ["contemporary", "generational", "distant", "modern"];
const ACCESS = ["direct", "informant", "secondhand"];

function meter(label, value, scale, explain) {
  // Filled segments = how strong this ONE dimension is. Unknown = empty, not weak.
  const filled = value == null ? 0 : scale.length - scale.indexOf(value);
  const segs = scale.map((_, i) => `<span class="seg${i < filled ? " on" : ""}"></span>`).join("");
  const text = value == null ? `<span class="na">unknown</span>` : esc(words(value));
  return `<div class="ev-row">
      <div class="ev-label">${label}<span class="ev-explain">${explain}</span></div>
      <div class="meter" role="img" aria-label="${label}: ${value ?? "unknown"}">${segs}</div>
      <div class="ev-value">${text}</div>
    </div>`;
}

function evidenceHTML(e) {
  if (e.independent_witnesses === 0) {
    return `<p class="empty-note">No supporting sources, so there is nothing to grade.</p>`;
  }
  const voices = e.independent_witnesses;
  const copies = e.shallowest_transmission;
  const extra = [
    e.qualifying_sources.length ? `Hedged by: ${e.qualifying_sources.map(esc).join(", ")}` : "",
    e.contradicting_sources.length ? `Contradicted by: ${e.contradicting_sources.map(esc).join(", ")}` : "",
  ].filter(Boolean).map((t) => `<p class="empty-note">${t}</p>`).join("");
  return `
    <div class="evidence">
      <div class="ev-row">
        <div class="ev-label">Independent voices<span class="ev-explain">sources that don't copy each other</span></div>
        <div class="ev-big">${voices}</div>
        <div class="ev-value">${voices === 1 ? "one voice" : `${voices} voices`}</div>
      </div>
      ${meter("Closeness in time", e.closest_proximity, PROXIMITY, "how near the events it was written")}
      ${meter("How the author knew", e.best_access, ACCESS, "saw it, was told, or read it")}
      <div class="ev-row">
        <div class="ev-label">Times copied<span class="ev-explain">steps from the original text</span></div>
        <div class="ev-big">${copies ?? "?"}</div>
        <div class="ev-value">${copies === 0 ? "original (or no known copy chain)" : `${copies} cop${copies === 1 ? "y" : "ies"} away`}</div>
      </div>
      ${extra}
    </div>`;
}

async function showClaim(key) {
  body.dataset.view = "detail";
  let c;
  try {
    c = await getJSON(`/claims/${encodeURIComponent(key)}`);
  } catch (err) {
    body.innerHTML = `<button type="button" class="back" data-back>All claims</button>
      <p class="empty-note">Couldn't load ${esc(key)}: ${esc(err.message)}</p>`;
    return;
  }

  const relations = c.relations.map((r) => {
    const other = `<button type="button" class="link" data-claim="${esc(r.claim)}">${esc(r.claim)}</button>`;
    return r.direction === "out"
      ? `<li>This claim ${esc(words(r.kind))} ${other}</li>`
      : `<li>${other} ${esc(words(r.kind))} this claim</li>`;
  }).join("");

  const boundaries = c.boundaries.map((b) => `
    <li><b>${esc(b.interpretation_label)}</b>
      ${b.source_figure ? `, traced from ${esc(b.source_figure)}` : ""}
      ${b.imprecision ? `<div class="empty-note">${esc(b.imprecision)}</div>` : ""}</li>`).join("");

  body.innerHTML = `
    <article class="detail">
      <button type="button" class="back" data-back>All claims</button>
      <div class="detail-meta">
        <span class="claim-key">${esc(c.key)}</span> ${statusTag(c.sourcing_status)}${
          c.subject ? ` about ${esc(c.subject.name)}` : ""}${
          c.when_label ? `, ${esc(c.when_label)}` : ""}
      </div>
      <p class="assertion">${esc(c.assertion)}</p>
      <div class="empty-note">${esc(words(c.kind))}; research ${esc(words(c.research_status))}</div>
      <h2> Strength of evidence</h2>
      ${evidenceHTML(c.evidence)}
      <h2>Sources</h2>
      ${c.attachments.length ? c.attachments.map(attachmentHTML).join("")
        : `<p class="empty-note">No sources attached.</p>`}

      ${relations ? `<h2>Related claims</h2><ul class="claim-list relations">${relations}</ul>` : ""}
      ${boundaries ? `<h2>Boundary geometry</h2><ul class="claim-list">${boundaries}</ul>` : ""}
      ${c.notes ? `<h2>Notes</h2><p class="notes">${esc(c.notes.trim())}</p>` : ""}
    </article>`;
  body.scrollTop = 0;
}

// One delegated handler for every claim link and back button in the panel.
body.addEventListener("click", (e) => {
  const claim = e.target.closest("[data-claim]");
  if (claim) return showClaim(claim.dataset.claim);
  if (e.target.closest("[data-back]")) showList();
});

// ---------------------------------------------------------------------------
// start
// ---------------------------------------------------------------------------

getJSON("/claims")
  .then((cs) => { allClaims = cs; showList(); })
  .catch((err) => {
    body.innerHTML = `<p class="empty-note">Couldn't load claims: ${esc(err.message)}. Check that the API is running (make dev).</p>`;
  });
