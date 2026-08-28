// Live draft board. No build step and no framework on purpose: during a draft
// the only requirement that matters is that this never fails to render.

let S = null, posFilter = "ALL", results = [], sel = 0, showGrid = false;
let sortState = { key: "vor", dir: -1 };
let lastHeroKey = null;
const flashSeen = new Map();  // player key -> last-rendered value, for change flashes

// Sensible default direction per column: numbers where more is better sort
// high-to-low; numbers where earlier/lower is better (or plain alpha) sort
// low-to-high.
const SORT_DEFAULT_DESC = new Set(["vor", "proj", "survival"]);

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const POS = ["RB", "WR", "QB", "TE", "DEF", "K"];
const SCARCITY_POS = ["RB", "WR", "TE", "QB"];   // DEF/K have no real tiers
const pct = (v) => Math.round(v * 100);
const signed = (v) => (v > 0 ? "+" : v < 0 ? "\u2212" : "") + Math.abs(v);

// Sequential ramp for magnitude. Survival is a quantity, not a status, so it
// steps through one hue rather than borrowing the reserved good/warning colors.
const SEQ = ["--seq-1", "--seq-2", "--seq-3", "--seq-4", "--seq-5"];
const seqFor = (t) => `var(${SEQ[Math.min(SEQ.length - 1, Math.max(0, Math.floor(t * SEQ.length)))]})`;

// Donut: part-to-whole at a glance, <=6 segments. Used only for roster shape --
// the one question here that is genuinely "what is this made of" rather than
// "how much". Survival stays a meter and value stays a bar, because a single
// ratio and a magnitude are not part-to-whole questions.
function donut(segments, size = 26, thickness = 5) {
  const total = segments.reduce((a, s) => a + s.n, 0);
  if (!total) {
    return `<svg class="donut" width="${size}" height="${size}" viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="15.5" fill="none" stroke="var(--s3)" stroke-width="${thickness}"/></svg>`;
  }
  const R = 15.5, C = 2 * Math.PI * R;
  const gap = segments.length > 1 ? 1.6 : 0;   // surface gap between fills
  let offset = 0;
  const arcs = segments.map((seg) => {
    const len = (seg.n / total) * C;
    const dash = `${Math.max(len - gap, 0.6)} ${C - Math.max(len - gap, 0.6)}`;
    const el = `<circle cx="20" cy="20" r="${R}" fill="none"
      stroke="var(--${seg.pos.toLowerCase()})" stroke-width="${thickness}"
      stroke-dasharray="${dash}" stroke-dashoffset="${-offset}"/>`;
    offset += len;
    return el;
  }).join("");
  const label = segments.map((s) => `${s.n} ${s.pos}`).join(", ");
  return `<svg class="donut" width="${size}" height="${size}" viewBox="0 0 40 40" role="img"
     aria-label="Roster shape: ${esc(label)}"><title>${esc(label)}</title>
     <circle cx="20" cy="20" r="${R}" fill="none" stroke="var(--s3)" stroke-width="${thickness}"/>
     ${arcs}</svg>`;
}

// Rank sparkline: positional finish across seasons, inverted so up means better.
// Rank is drawn on a log scale because RB1 to RB3 is a small move at the elite
// end while RB30 to RB10 is a large one; a linear axis would flatten the second.
function rankSpark(seasons, pos, w = 260, h = 68) {
  const pts = seasons.filter((s) => s.rank);
  if (pts.length < 2) return `<div class="nodata">Not enough seasons to chart.</div>`;
  const L = (r) => Math.log(Math.max(r, 1));
  const maxL = Math.max(L(48), ...pts.map((s) => L(s.rank)));
  const x = (i) => 6 + (i * (w - 12)) / (pts.length - 1);
  const y = (r) => 8 + (L(r) / maxL) * (h - 30);
  const line = pts.map((s, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(s.rank).toFixed(1)}`).join("");
  const area = `M${x(0).toFixed(1)},${(h - 16).toFixed(1)} L` +
    pts.map((s, i) => `${x(i).toFixed(1)},${y(s.rank).toFixed(1)}`).join(" L") +
    ` L${x(pts.length - 1).toFixed(1)},${(h - 16).toFixed(1)} Z`;

  // Color follows the entity (position) for the line, same as everywhere
  // else on the board. Dot fill is a SECOND, deliberate encoding -- season
  // quality -- so a great year and a rough one are visually distinct even
  // before reading the number.
  const dots = pts.map((s, i) => {
    const tier = rankTier(pos, s.rank);
    const cx = x(i).toFixed(1), cy = y(s.rank).toFixed(1);
    // Rookie season gets a visible ring around the dot -- a real, sourced
    // marker (the official roster's rookie_year), not a guess from experience.
    const rookieRing = s.rookie
      ? `<circle cx="${cx}" cy="${cy}" r="6.5" fill="none" stroke="var(--accent)"
           stroke-width="1.3" stroke-dasharray="2 1.6" pointer-events="none"></circle>` : "";
    return `
    <circle class="sparkhit" cx="${cx}" cy="${cy}" r="9" fill="transparent"
      data-season="${s.season}" data-rank="${s.rank}" data-pred="${s.predicted_rank ?? ""}"
      data-points="${s.points}" data-games="${s.games}" data-age="${s.age ?? ""}"
      data-rookie="${s.rookie ? "1" : ""}" data-pos="${pos}" tabindex="0"
      aria-label="${s.season}${s.rookie ? " (rookie season)" : ""}: ${pos}${s.rank}, ${s.points} points in ${s.games} games"></circle>
    ${rookieRing}
    <circle class="sparkdot" cx="${cx}" cy="${cy}" r="3.5"
      fill="${TIER_COLOR[tier]}" stroke="var(--s1)" stroke-width="1.5" pointer-events="none"></circle>`;
  }).join("");
  const labels = pts.map((s, i) =>
    `<text x="${x(i).toFixed(1)}" y="${h - 3}" text-anchor="middle" class="sl">${
      String(s.season).slice(2)}</text>`).join("");
  const best = pts.map((s, i) => (i === 0 || i === pts.length - 1)
    ? `<text x="${x(i).toFixed(1)}" y="${(y(s.rank) - 9).toFixed(1)}" text-anchor="middle" class="sr">${pos}${s.rank}</text>` : "").join("");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="100%" height="${h}" role="img"
    aria-label="Positional finish by season, hover a point for detail">
    <path d="${area}" fill="var(--${pos.toLowerCase()})" opacity=".10" stroke="none"/>
    <path d="${line}" fill="none" stroke="var(--${pos.toLowerCase()})" stroke-width="2"
      stroke-linejoin="round" stroke-linecap="round" opacity=".85"/>
    ${dots}${labels}${best}</svg>`;
}

// One tooltip element, reused across every sparkline via delegation -- the
// SVG itself is rebuilt on every profile open, so listeners live on a stable
// ancestor rather than being re-attached per dot.
function ensureSparkTip() {
  let el = document.getElementById("sparktip");
  if (!el) {
    el = document.createElement("div");
    el.id = "sparktip";
    el.className = "sparktip";
    el.hidden = true;
    document.body.appendChild(el);
  }
  return el;
}

function sparkTipContent(d) {
  const pos = d.dataset.pos, rank = +d.dataset.rank, pred = d.dataset.pred ? +d.dataset.pred : null;
  const pts = d.dataset.points, games = +d.dataset.games, age = d.dataset.age;
  const missed = games <= 12;
  let deltaLine = "";
  if (pred != null) {
    const delta = pred - rank;   // positive = finished better than drafted
    const word = delta > 1 ? "beat" : delta < -1 ? "missed" : "matched";
    const cls = delta > 1 ? "up" : delta < -1 ? "down" : "";
    deltaLine = `<div class="stiprow"><span>Drafted around</span><b>${pos}${pred}</b></div>
      <div class="stiprow ${cls}"><span>Vs. that ADP</span><b>${
        word === "matched" ? "Right on schedule" : `${word} it by ${Math.abs(delta)}`}</b></div>`;
  }
  const rookieBadge = d.dataset.rookie ? `<span class="rookiebadge">Rookie</span>` : "";
  return `
    <div class="stiphead">${d.dataset.season} <span class="pos ${pos}">${pos}${rank}</span>${rookieBadge}</div>
    ${deltaLine}
    <div class="stiprow"><span>Points</span><b>${pts}</b></div>
    <div class="stiprow"><span>Games</span><b>${games}${missed ? " — missed significant time" : ""}</b></div>
    ${age ? `<div class="stiprow"><span>Age that season</span><b>${age}</b></div>` : ""}`;
}

// One tooltip trigger, two kinds of hoverable targets: a season dot (rich
// season detail) and a scarcity-ladder block (which player occupies that
// square). Both share the same floating tip element and positioning logic.
function tipTargetOf(e) {
  return e.target.closest(".sparkhit") || e.target.closest(".ladderblk");
}
function tipContentFor(d) {
  return d.classList.contains("ladderblk")
    ? `<div class="stiphead">${esc(d.dataset.name)}</div>
       <div class="stiprow"><span>Position</span><b>${d.dataset.pos}</b></div>
       <div class="stiprow"><span>Tier</span><b>${d.dataset.tier}</b></div>`
    : sparkTipContent(d);
}
document.addEventListener("pointerover", (e) => {
  const d = tipTargetOf(e);
  if (!d) return;
  const tip = ensureSparkTip();
  tip.innerHTML = tipContentFor(d);
  tip.hidden = false;
  positionSparkTip(tip, d);
});
document.addEventListener("pointermove", (e) => {
  const d = tipTargetOf(e);
  const tip = document.getElementById("sparktip");
  if (d && tip && !tip.hidden) positionSparkTip(tip, d);
});
document.addEventListener("pointerout", (e) => {
  if (!tipTargetOf(e)) return;
  const tip = document.getElementById("sparktip");
  if (tip) tip.hidden = true;
});
// Delegated rather than wired per-block: the ladder is rebuilt on every
// render, so binding here once covers every square without re-attaching.
// Quick draft: a small always-there-on-hover control so a real, fast-moving
// draft (autopick counting down, ten people ahead of you) never requires the
// profile-panel detour. One delegated handler covers every surface that
// renders one, so no per-render wiring is needed.
function quickDraftBtn(key, cls = "qdraft") {
  return `<button type="button" class="${cls}" data-qdraft="${esc(key)}"
    title="Draft instantly" aria-label="Draft instantly">✓</button>`;
}
// Capture phase, deliberately: a quick-draft button sits INSIDE a row that
// has its own bubble-phase click handler (open the profile). Bubble-phase
// stopPropagation() here would run too late -- the row's handler, attached
// directly on the row, fires on the way up before a same-phase document
// listener ever sees the event. Capture fires top-down, ahead of it.
document.addEventListener("click", (e) => {
  const q = e.target.closest("[data-qdraft]");
  if (!q) return;
  e.preventDefault();
  e.stopPropagation();
  draft(q.dataset.qdraft);
}, true);
document.addEventListener("click", (e) => {
  const blk = e.target.closest(".ladderblk");
  if (blk && blk.dataset.key) openProfile(blk.dataset.key);
});
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" && e.key !== " ") return;
  const blk = e.target.closest(".ladderblk");
  if (blk && blk.dataset.key) { e.preventDefault(); openProfile(blk.dataset.key); }
});
document.addEventListener("focusin", (e) => {
  const d = tipTargetOf(e);
  if (!d) return;
  const tip = ensureSparkTip();
  tip.innerHTML = tipContentFor(d);
  tip.hidden = false;
  positionSparkTip(tip, d);
});
document.addEventListener("focusout", (e) => {
  if (!tipTargetOf(e)) return;
  const tip = document.getElementById("sparktip");
  if (tip) tip.hidden = true;
});

function positionSparkTip(tip, dotEl) {
  const r = dotEl.getBoundingClientRect();
  const tw = tip.offsetWidth || 180, th = tip.offsetHeight || 90;
  let left = r.left + r.width / 2 - tw / 2;
  let top = r.top - th - 10;
  left = Math.max(8, Math.min(left, window.innerWidth - tw - 8));
  if (top < 8) top = r.bottom + 10;
  tip.style.left = left + "px";
  tip.style.top = top + "px";
}

function face(shot, name, size = 38, prefix = "/headshots/") {
  const initials = String(name || "").split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("");
  return shot
    ? `<img class="face" src="${prefix}${esc(shot)}" width="${size}" height="${size}" alt="" loading="lazy">`
    : `<span class="face blank" style="width:${size}px;height:${size}px">${esc(initials)}</span>`;
}

// A defense has no player photo -- its team logo IS its identity, so it takes
// the same circular avatar slot a headshot would use everywhere else.
function avatar(p, size = 38) {
  return p.pos === "DEF"
    ? face(p.team_logo, p.team, size, "/logos/")
    : face(p.headshot, p.name, size);
}

async function openProfile(key) {
  const d = await api("/api/player/" + encodeURIComponent(key));
  if (!d.ok) return;
  const panel = $("profile");
  const adj = d.adjustments.length
    ? d.adjustments.map((a) => `<li>${esc(a.note)}</li>`).join("")
    : `<li class="muted">No age or trajectory adjustment applied.</li>`;
  const rows = [...d.seasons].reverse().map((s) => {
    const tier = rankTier(d.pos, s.rank);
    const delta = s.predicted_rank != null ? s.predicted_rank - s.rank : null;
    const deltaTxt = delta == null ? "—"
      : delta > 1 ? `<span class="up">beat by ${delta}</span>`
      : delta < -1 ? `<span class="down">missed by ${-delta}</span>`
      : "on schedule";
    return `
    <tr><td>${s.season}${s.rookie ? ' <span class="rookiebadge sm">R</span>' : ""}</td>
      <td><b class="rankpill" style="color:${TIER_COLOR[tier]}">${d.pos}${s.rank}</b></td>
      <td class="mut">${s.predicted_rank != null ? d.pos + s.predicted_rank : "—"}</td>
      <td class="mut">${deltaTxt}</td>
      <td class="num tnum">${s.points}</td>
      <td class="num tnum">${s.games}${s.games <= 12 ? ' <span class="flag">Hurt</span>' : ""}</td>
      <td class="num tnum">${s.ppg}</td>
      <td class="num mut tnum">${s.age ?? "—"}</td></tr>`;
  }).join("");

  panel.innerHTML = `
    <div class="pf">
      <button class="pfclose" id="pfclose" aria-label="Close profile">×</button>
      <div class="pfhead">
        ${avatar(d, 64)}
        <div>
          <div class="pfname">${esc(d.name)}</div>
          <div class="pfmeta"><span class="pos ${d.pos}">${d.pos}</span>
            <span>${esc(d.team)}</span>
            ${d.age ? `<span>· Age ${d.age}</span>` : ""}
            ${d.bye ? `<span>· Bye ${d.bye}</span>` : ""}
            ${d.adp ? `<span>· ADP ${d.adp}</span>` : ""}</div>
        </div>
      </div>

      ${d.drafted
        ? `<div class="pfdrafted">Already drafted</div>`
        : `<button class="pfdraft" id="pfdraft">Draft ${esc(d.name)}</button>`}

      <h3>Positional finish by season</h3>
      ${rankSpark(d.seasons, d.pos)}
      ${d.seasons.length ? `<table class="pfseasons">
        <thead><tr><th>Season</th><th>Finish</th><th title="That season's ADP-implied positional rank -- the market's preseason prediction, not preseason-game stats">ADP</th><th>Vs. ADP</th>
          <th class="num">Points</th><th class="num">Games</th>
          <th class="num">Per&nbsp;game</th><th class="num">Age</th></tr></thead>
        <tbody>${rows}</tbody></table>
        <p class="tierlegend"><i style="background:var(--good)"></i>Elite finish
          <i style="background:var(--fg-3)"></i>Startable
          <i style="background:var(--critical)"></i>Below replacement
          <span class="rookiedot"></span>Rookie season</p>` : ""}

      <h3>What this projection is built from</h3>
      <div class="pfrow"><span>Projected points</span><b>${d.proj}</b></div>
      <div class="pfrow"><span>From his own production</span><b>${d.proj_baseline}</b></div>
      <div class="pfrow"><span>From the market (ADP)</span><b>${d.proj_market}</b></div>
      <div class="pfrow"><span>Weight on his own record</span><b>${Math.round(d.history_weight * 100)}%</b></div>
      <ul class="pfadj">${adj}</ul>

      <h3>What the board numbers mean for him</h3>
      <div class="pfrow"><span>Points above a freely available ${d.pos}</span><b>${d.vor}</b></div>
      <div class="pfrow"><span>That replacement ${d.pos} projects for</span><b>${d.replacement}</b></div>
      ${d.next_best ? `<div class="pfrow"><span>Next ${d.pos} on the board</span>
        <b>${esc(d.next_best.name)} (${d.next_best.proj})</b></div>` : ""}
      ${d.survival != null ? `<div class="pfrow"><span>Still there at pick ${d.horizon}</span>
        <b>${pct(d.survival)}%</b></div>` : ""}
    </div>`;
  // Open transition: unhide, then flip a class on the next frame so the
  // backdrop-fade + panel rise-and-scale actually has a starting state to
  // transition from (setting hidden and the class in the same tick would
  // let the browser collapse them into one paint with nothing to animate).
  panel.hidden = false;
  panel.classList.remove("closing");
  requestAnimationFrame(() => requestAnimationFrame(() => panel.classList.add("open")));
  $("pfclose").onclick = closeProfile;
  const draftBtn = document.getElementById("pfdraft");
  if (draftBtn) draftBtn.onclick = () => { closeProfile(); draft(d.key); };
  panel.querySelector(".pf")?.focus?.();
}

function closeProfile() {
  const panel = $("profile");
  if (panel.hidden) return;
  panel.classList.remove("open");
  panel.classList.add("closing");
  const done = () => { panel.hidden = true; panel.classList.remove("closing"); };
  // If motion is reduced the transition never fires, so hide immediately
  // rather than waiting on an event that will never arrive.
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) { done(); return; }
  panel.addEventListener("transitionend", done, { once: true });
  setTimeout(done, 260);   // safety net if transitionend does not fire
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("profile").hidden) closeProfile();
});
$("profile").addEventListener("click", (e) => {
  if (e.target.id === "profile") closeProfile();   // backdrop, not the card itself
});

// Season-finish quality, bucketed against position-aware fixed thresholds.
// Reuses the reserved status tokens (good/critical) rather than inventing a
// new hue -- this is a QUALITY read layered on top of the position-colored
// line, not a repeat of player identity.
const TIER_CUTOFFS = {
  RB: [12, 30], WR: [12, 30], TE: [6, 14], QB: [6, 14], DEF: [6, 20], K: [6, 20],
};
function rankTier(pos, rank) {
  const [elite, startable] = TIER_CUTOFFS[pos] || [12, 30];
  if (rank <= elite) return "elite";
  if (rank <= startable) return "startable";
  return "low";
}
const TIER_COLOR = { elite: "var(--good)", startable: "var(--fg-2)", low: "var(--critical)" };

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}

async function refresh() {
  try {
    S = await api("/api/state");
    render();
    $("status").textContent = "";
  } catch {
    $("status").textContent = "Lost contact with the server — showing the last good board.";
  }
}

// ── pick entry ────────────────────────────────────────────────
async function search(q) {
  if (!q.trim()) { results = []; drawDrop(); return; }
  try { results = await api("/api/search?q=" + encodeURIComponent(q)); sel = 0; drawDrop(); }
  catch { /* keep the last list rather than blanking mid-draft */ }
}

function drawDrop() {
  const d = $("drop");
  if (!results.length) { d.hidden = true; d.innerHTML = ""; return; }
  d.hidden = false;
  d.innerHTML = results.map((p, i) => `
    <button role="option" aria-selected="${i === sel}" class="${i === sel ? "sel" : ""}" data-key="${esc(p.key)}">
      <span class="pos ${p.pos}">${p.pos}</span>
      <b>${esc(p.name)}</b><span class="mut">${esc(p.team)}</span>
      <span class="mut">ADP ${p.adp ?? "—"} · VOR ${p.vor}</span>
    </button>`).join("");
  [...d.children].forEach((el) => (el.onclick = () => draft(el.dataset.key)));
}

async function draft(key) {
  try {
    const r = await api("/api/pick", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key }),
    });
    if (!r.ok) { $("status").textContent = r.error; return; }
    $("q").value = ""; results = []; drawDrop();
    await refresh();
  } catch { $("status").textContent = "Could not record that pick — check the server."; }
}

$("q").addEventListener("input", (e) => search(e.target.value));
$("q").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { sel = Math.min(sel + 1, results.length - 1); drawDrop(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); drawDrop(); e.preventDefault(); }
  else if (e.key === "Enter" && results[sel]) { draft(results[sel].key); e.preventDefault(); }
  else if (e.key === "Escape") { $("q").value = ""; results = []; drawDrop(); }
});
$("undo").onclick = async () => { await api("/api/undo", { method: "POST" }); refresh(); };
$("slot").onchange = async (e) => {
  const r = await api("/api/slot", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slot: Number(e.target.value) }),
  });
  if (!r.ok) { $("status").textContent = r.error; return; }
  refresh();
};
$("reset").onclick = async () => {
  if (confirm("Clear every pick and restart the draft?")) {
    await api("/api/reset", { method: "POST" }); refresh();
  }
};
$("gridbtn").onclick = () => {
  showGrid = !showGrid;
  $("gridbtn").classList.toggle("on", showGrid);
  $("gridbtn").setAttribute("aria-pressed", String(showGrid));
  $("mainview").hidden = showGrid;
  $("gridview").hidden = !showGrid;
  render();
};
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "/") { e.preventDefault(); $("q").focus(); }
  if (e.key === "u") $("undo").click();
});

// ── rendering ─────────────────────────────────────────────────
function render() {
  if (!S) return;
  $("league").textContent = "· " + S.league;

  const sel = $("slot");
  if (sel.options.length !== S.teams) {
    sel.innerHTML = Array.from({ length: S.teams }, (_, i) =>
      `<option value="${i + 1}">Pick ${i + 1}</option>`).join("");
  }
  sel.value = String(S.my_slot);
  const mp = S.my_picks || [];
  $("mypicks").textContent = mp.length
    ? mp.slice(0, 6).join(", ") + (mp.length > 6 ? "…" : "")
    : "";
  $("pickno").textContent = `${S.current_pick}/${S.total_picks}`;
  $("rnd").textContent = S.round;
  $("clock").textContent = S.complete ? "Done" : `Team ${S.on_clock}`;
  $("mynext").textContent = S.my_next_pick ?? "—";
  $("until").textContent = S.is_my_turn ? "Now" : S.picks_until_mine;

  const chip = $("turn");
  chip.className = "clockchip" + (S.is_my_turn ? " me" : "");
  $("turntext").textContent = S.complete ? "Draft complete"
    : S.is_my_turn ? "You are on the clock" : `Team ${S.on_clock} is picking`;

  if (showGrid) { renderGrid(); return; }
  const ri = S.round_insight;
  $("roundtip").innerHTML = ri
    ? `<span class="ritext">${esc(ri.text)}</span>
       <span class="rin">${ri.seasons} seasons · n=${ri.n}</span>`
    : `<span class="ritext dim">Not enough historical evidence for this round.</span>`;

  renderHero(); renderLadder(); renderBoard();
  renderRoster(); renderPace(); renderGrades();
  $("resolution").textContent = S.resolution;
}

function renderHero() {
  const top4 = S.recommendations.slice(0, 4);
  const [top, ...restTop] = top4;
  const slim = S.recommendations.slice(4);
  if (!top) {
    $("hero").innerHTML = `<div class="empty-state">No players left on the board.</div>`;
    $("compare").innerHTML = ""; $("recs").innerHTML = ""; return;
  }
  const hz = S.horizon_pick;
  const lead = S.is_my_turn ? "Take now" : "Top of your board";
  const isNew = top.key !== lastHeroKey;
  lastHeroKey = top.key;
  const tie = (top.tied_with || []).length
    ? `<div class="tie">Too close to call against ${esc(top.tied_with[0])}</div>` : "";
  $("hero").innerHTML = `
    <div class="hero ${isNew ? "enter" : ""}" data-key="${esc(top.key)}">
      <div class="lead">${esc(lead)}</div>
      <div class="herotop">
        ${avatar(top, 52)}
        <div class="heroid">
          <div class="nm">${esc(top.name)}</div>
          <div class="sub"><span class="pos ${top.pos}">${top.pos}</span>
            <span>${esc(top.team)}</span>${top.age ? `<span>· ${top.age}y</span>` : ""}
            <span>· ADP ${top.adp ?? "—"}</span></div>
        </div>
      </div>
      ${tie}
      ${S.disagreement ? `<div class="disagree">${esc(S.disagreement)}</div>` : ""}
      <div class="why">
        <div class="metric"><b class="tnum">${signed(top.vona)}</b>
          <span>points you'd lose by waiting — the next ${top.pos} you'd realistically
          get projects that much lower</span></div>
        <div class="metric"><b class="tnum">${pct(top.survival)}%</b>
          <span>chance he is still there at pick ${hz ?? "—"}${
            hz && S.my_next_pick && hz !== S.my_next_pick
              ? ` <span class="dim">(you also pick at ${S.my_next_pick})</span>` : ""}</span></div>
        ${top.warnings.length ? `<ul class="reasons">
          ${top.warnings.map((w) => `<li class="w">${esc(w)}</li>`).join("")}</ul>` : ""}
      </div>
      <div class="herobtns">
        <button class="pfbtn" data-profile="${esc(top.key)}">View full profile</button>
        ${quickDraftBtn(top.key, "qdraft qdraft-hero")}
      </div>
    </div>`;
  const h = $("hero").firstElementChild;
  h.querySelector(".pfbtn").onclick = (e) => { e.stopPropagation(); openProfile(top.key); };
  h.onclick = () => openProfile(top.key);   // consistent with every other row -- see profile, then draft from its button

  // Compare panel: the field the hero is being chosen from, not just the
  // winner in isolation. Both percentages are shown for every one of the top
  // players, as large colored numbers rather than thin bars, so a close call
  // between two or three real options is visible at a glance -- already
  // ordered by the number each row displays (the simulated probability).
  //
  // "Best" and "Model" are named to match vocabulary already used elsewhere
  // (the slim list below already says "best pick" for this exact number) and
  // to be readable without hovering, since a bare "sim"/"value" pairing was
  // reported confusing and a tooltip alone wasn't fixing that.
  $("compare").innerHTML = `
    <p class="cmplegend"><b>Best</b> = wins the simulated draft most often ·
      <b>Model</b> = this tool's raw value ranking, before simulating anything</p>
    ${top4.map((r, i) => {
      const sim = r.pick_prob, val = r.value_share;
      const simLeads = sim != null && val != null && sim >= val;
      const flashKey = "cmp:" + r.key;
      const justChanged = flashSeen.has(flashKey) && flashSeen.get(flashKey) !== sim;
      flashSeen.set(flashKey, sim);
      return `<div class="cmprow ${i === 0 ? "lead" : ""} ${justChanged ? "flash" : ""}"
          role="button" tabindex="0" data-key="${esc(r.key)}">
        <span class="cmprk">${i + 1}</span>
        ${avatar(r, 30)}
        <span class="cmpname"><b>${esc(r.name)}</b><span class="pos ${r.pos}">${r.pos}</span></span>
        <span class="cmpnum ${simLeads ? "big" : ""}" title="Share of simulated drafts where taking him now produced your best team">
          <b class="tnum" style="color:var(--good)">${sim != null ? pct(sim) + "%" : "—"}</b>
          <span>best</span></span>
        <span class="cmpnum ${!simLeads ? "big" : ""}" title="How strongly the value model favors him over these alternatives, before simulating anything">
          <b class="tnum" style="color:var(--accent)">${val != null ? pct(val) + "%" : "—"}</b>
          <span>model</span></span>
        ${quickDraftBtn(r.key, "qdraft qdraft-inline")}
      </div>`;
    }).join("")}`;
  [...$("compare").querySelectorAll(".cmprow")].forEach((el) => {
    el.onclick = () => openProfile(el.dataset.key);
    el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openProfile(el.dataset.key); } };
  });

  $("recs").innerHTML = slim.map((r, i) => `
    <div class="rec" role="button" tabindex="0" data-key="${esc(r.key)}">
      <span class="rk">${i + 5}</span>
      ${avatar(r, 26)}
      <span class="pos ${r.pos}">${r.pos}</span>
      <span class="nm">${esc(r.name)}</span>
      <span class="rt">${r.pick_prob != null
        ? `<b class="tnum prob">${pct(r.pick_prob)}%</b><span>best pick</span>`
        : `<b class="tnum">${signed(r.vona)}</b><span>vs next ${r.pos}</span>`}</span>
      ${quickDraftBtn(r.key, "qdraft qdraft-inline")}
    </div>`).join("");
  [...$("recs").children].forEach((el) => {
    el.onclick = () => openProfile(el.dataset.key);
    el.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openProfile(el.dataset.key); } };
  });
}

// Tier ladder — the scarcity read. Each block group is a tier of remaining
// players at that position; the visible gaps are the value cliffs. This answers
// "can I wait?" faster than any number can.
function renderLadder() {
  const sc = S.scarcity || {};
  $("ladder").innerHTML = SCARCITY_POS.filter((p) => (sc[p]?.tiers || []).length).map((p) => {
    const d = sc[p];
    const urgent = d.left_in_top_tier <= 2 && d.next_cliff >= 12;
    // Only the tiers you could plausibly still reach are drawn. Rendering a
    // 50-player tail as blocks says nothing and buries the tiers that matter.
    const shown = d.tiers.slice(0, 3);
    const blocks = shown.map((t, ti) => {
      const n = Math.min(t.count, 12);
      // Every visible square is hoverable to its actual player -- the whole
      // point of drawing them individually rather than as one solid bar.
      const cells = Array.from({ length: n }, (_, bi) => {
        const nm = t.names[bi];
        return `<i class="blk t${ti} ${nm ? "ladderblk" : ""}" style="background:var(--${p.toLowerCase()})"
          ${nm ? `data-name="${esc(nm.name)}" data-key="${esc(nm.key)}" data-tier="${t.tier}" data-pos="${p}" tabindex="0"` : ""}></i>`;
      }).join("");
      const more = t.count > n ? `<i class="more t${ti}">+${t.count - n}</i>` : "";
      return cells + more + (ti < shown.length - 1 ? `<i class="gap"></i>` : "");
    }).join("");
    return `
      <div class="lane ${urgent ? "urgent" : ""}">
        <div class="lh">
          <span class="pos ${p}">${p}</span>
          <span class="cnt"><b>${d.left_in_top_tier}</b> left at this value</span>
          <span class="cliff">${d.next_cliff > 0 ? `then \u2212${d.next_cliff} pts` : "flat from here"}</span>
        </div>
        <div class="blocks">${blocks}</div>
        <div class="lanefoot">${esc(d.tiers[0].names.slice(0, 3).map((x) => x.name).join(" \u00b7 "))}</div>
      </div>`;
  }).join("");
}

function sortRows(rows) {
  const { key, dir } = sortState;
  const singlePos = posFilter !== "ALL" && posFilter !== "FLEX";
  // These two columns display a different underlying field depending on the
  // filter (overall vs. positional) -- sorting must follow whichever number
  // is actually on screen, or the column header's arrow would lie.
  const OVERALL_SWAP = { predicted_rank: "predicted_rank_overall", last_year_rank: "last_year_rank_overall" };
  const val = (p) => {
    if (key === "name" || key === "pos" || key === "team") return (p[key] || "").toLowerCase();
    const field = !singlePos && OVERALL_SWAP[key] ? OVERALL_SWAP[key] : key;
    const v = p[field];
    return v == null ? (dir === 1 ? Infinity : -Infinity) : v;   // nulls sort last either way
  };
  return [...rows].sort((a, b) => {
    const av = val(a), bv = val(b);
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
}

function wireSortHeaders() {
  document.querySelectorAll("#boardhead th[data-key]").forEach((th) => {
    const k = th.dataset.key;
    th.classList.toggle("active", k === sortState.key);
    th.classList.toggle("desc", k === sortState.key && sortState.dir === -1);
    th.onclick = () => {
      if (sortState.key === k) {
        sortState.dir *= -1;
      } else {
        sortState = { key: k, dir: SORT_DEFAULT_DESC.has(k) ? -1 : 1 };
      }
      renderBoard();
    };
  });
}

function renderBoard() {
  const flexPos = S.flex_eligible || ["RB", "WR", "TE"];
  $("filters").innerHTML = ["ALL", "FLEX", ...POS].map((p) =>
    `<button class="${p === posFilter ? "on" : ""}" data-p="${p}">${p}</button>`).join("");
  [...$("filters").children].forEach((b) =>
    (b.onclick = () => { posFilter = b.dataset.p; renderBoard(); }));
  wireSortHeaders();

  const filtered = S.players.filter((p) =>
    posFilter === "ALL" ? true : posFilter === "FLEX" ? flexPos.includes(p.pos) : p.pos === posFilter
  ).slice(0, 90);
  if (!filtered.length) {
    $("board").innerHTML = `<tr><td colspan="13"><div class="empty-state">No ${posFilter} players left.</div></td></tr>`;
    return;
  }
  // Tier-cliff dividers mean something whenever row order tracks tier
  // grouping -- true for VOR order (either direction, since VOR and tier move
  // together) and for an explicit tier sort (either direction). Sorted by
  // anything else -- name, ADP, age -- adjacent rows aren't adjacent in value
  // any more, so the divider would draw a line between rows that aren't
  // actually a cliff.
  const singlePos = posFilter !== "ALL" && posFilter !== "FLEX";
  const showCliffs = singlePos && (sortState.key === "vor" || sortState.key === "tier");
  const rows = sortRows(filtered);
  const maxV = Math.max(S.max_vor, 1);
  let prev = null;
  $("board").innerHTML = rows.map((p) => {
    const cliff = showCliffs && prev !== null && p.tier !== prev;
    prev = p.tier;
    const w = Math.max(2, (Math.max(p.vor, 0) / maxV) * 100);
    const s = p.survival;
    const flag = p.injury
      ? `<span class="flag ${p.injury === "Questionable" ? "q" : ""}">${esc(p.injury.slice(0, 4))}</span>` : "";
    // One position signal, not three: the whole row carries the tint, so a
    // separate colored dot and a colored bar are no longer saying the same
    // thing twice. The bar's own fill goes neutral -- length still carries
    // magnitude, color no longer repeats identity.
    // A defense's team is already its whole identity -- shown as its avatar
    // and its name ("Seattle Defense") -- so repeating the team here again is
    // pure redundancy. Left blank rather than duplicated.
    const teamCell = p.pos === "DEF" ? "" : p.team_logo
      ? `<img class="tlogo" src="/logos/${esc(p.team_logo)}" width="18" height="18" alt="${esc(p.team)}" title="${esc(p.team)}" loading="lazy">`
      : `<span class="mut">${esc(p.team)}</span>`;
    return `<tr class="postint ${p.pos} ${cliff ? "cliff" : ""}" data-key="${esc(p.key)}" data-team="${esc(p.team)}">
      <td class="qcol">${quickDraftBtn(p.key)}</td>
      <td><span class="pname">${avatar(p, 22)}${esc(p.name)}${flag}</span></td>
      <td>${p.pos}</td>
      <td>${teamCell}</td>
      <td class="num mut tnum">${(singlePos ? p.predicted_rank : p.predicted_rank_overall) ?? "—"}</td>
      <td class="num mut tnum">${(singlePos ? p.last_year_rank : p.last_year_rank_overall) ?? "—"}</td>
      <td class="num mut tnum">${p.age ?? "—"}</td>
      <td class="num mut tnum">${p.tier}</td>
      <td class="vbar"><i style="width:${w}%"></i><b class="tnum">${p.vor}</b></td>
      <td class="num mut tnum">${p.proj}</td>
      <td class="num mut tnum">${p.adp ?? "—"}</td>
      <td class="num mut tnum">${p.bye ?? "—"}</td>
      <td class="num">${s == null ? '<span class="mut">—</span>' : `
        <span class="meter"><i><b style="width:${pct(s)}%;background:${seqFor(s)}"></b></i>
        <span class="mut tnum">${pct(s)}%</span></span>`}</td>
    </tr>`;
  }).join("");
  [...$("board").children].forEach((tr) => {
    if (!tr.dataset.key) return;
    tr.onclick = () => openProfile(tr.dataset.key);
  });
}

function renderRoster() {
  const me = S.grades.find((g) => g.is_me);
  $("shape").innerHTML = me && me.roster.length
    ? `${donut(me.shape, 46, 7)}<div class="shapekey">${me.shape.map((s2) =>
        `<span><i style="background:var(--${s2.pos.toLowerCase()})"></i>${s2.n} ${s2.pos}</span>`).join("")}</div>`
    : "";
  $("roster").innerHTML = me && me.roster.length
    ? me.roster.map((p) => `<div class="slot"><span class="n">${p.overall}</span>
        <span class="pos ${p.pos}">${p.pos}</span><span>${esc(p.name)}</span></div>`).join("")
    : `<div class="empty-state">Nothing drafted yet.<br>Your first pick is #${S.my_next_pick ?? "—"}.</div>`;

  const needs = Object.entries(S.needs || {}).filter(([, v]) => v > 0);
  $("needs").innerHTML = needs.length
    ? needs.map(([k, v]) => `<span class="chip">${k}${v > 1 ? ` ×${v}` : ""}</span>`).join("")
    : `<span class="chip ok">Every starting slot filled</span>`;
}

// Pace: how fast each position is leaving the board relative to market ADP.
// 1.0x is the market baseline, drawn as the centre line.
function renderPace() {
  const raw = S.hazards || {};
  const hz = POS.filter((p) => p in raw).map((p) => [p, raw[p]]).sort((a, b) => b[1] - a[1]);
  if (!hz.length) {
    $("pace").innerHTML = `<div class="empty-state">Learns how your league drafts once picks are entered.</div>`;
    return;
  }
  if (hz.every(([, v]) => Math.abs(v - 1) < 0.06)) {
    $("pace").innerHTML =
      `<div class="empty-state">Everyone is drafting at market pace so far.</div>`;
    return;
  }
  $("pace").innerHTML = hz.map(([p, v]) => {
    const d = Math.max(-1, Math.min(1, (v - 1) / 1.2));   // −1..1 around market
    const w = Math.abs(d) * 50;
    const left = d >= 0 ? 50 : 50 - w;
    const hot = v > 1.35;
    return `<div class="pl"><span class="pos ${p}">${p}</span>
      <span class="tr"><span class="mid"></span>
        <span class="fill" style="left:${left}%;width:${Math.max(w, 1)}%;
          background:${hot ? "var(--warning)" : `var(--${p.toLowerCase()})`}"></span></span>
      <span class="v tnum">${v.toFixed(2)}×</span></div>`;
  }).join("");
}

function renderGrades() {
  const g0 = S.grades[0];
  $("conf").textContent = g0?.confidence === "low"
    ? "Early grades are noisy — treat these as directional until the middle rounds."
    : `Confidence: ${g0?.confidence ?? "low"}.`;

  const sorted = [...S.grades].sort((a, b) => b.score - a.score);
  const myRank = sorted.findIndex((g) => g.is_me) + 1;
  const me = sorted.find((g) => g.is_me);
  $("myrank").innerHTML = me
    ? `<b>${me.letter}</b><span>${myRank}${["st","nd","rd"][myRank - 1] || "th"} of ${sorted.length}</span>`
    : "";
  const lo = Math.min(...sorted.map((g) => g.score)), hi = Math.max(...sorted.map((g) => g.score));
  const span = hi - lo || 1;
  $("grades").innerHTML = sorted.map((g) => `
    <div class="gr ${g.is_me ? "me" : ""}">
      <div class="g1">${donut(g.shape || [], 24, 5)}<span class="lt">${g.letter}</span>
        <span class="tm">Team ${g.slot}${g.is_me ? " · you" : ""}</span>
        <span class="sp">${g.roster.length} pick${g.roster.length === 1 ? "" : "s"} · ${g.slp} pts</span></div>
      <div class="gbar"><i style="width:${Math.max(3, ((g.score - lo) / span) * 100)}%"></i></div>
      ${g.notes.length ? `<div class="nt">${esc(g.notes.join(" · "))}</div>` : ""}
      <div class="rs">${g.roster.length ? esc(g.roster.map((p) => p.name).join(", ")) : "No picks yet"}</div>
    </div>`).join("");
}

function renderGrid() {
  const POSN = ["QB", "RB", "WR", "TE", "DEF", "K"];
  $("gridlegend").innerHTML = POSN.map((p) =>
    `<span><i style="background:var(--${p.toLowerCase()}-fill);box-shadow:inset 0 0 0 1px var(--${p.toLowerCase()})"></i>${p}</span>`
  ).join("") + `<span><i style="box-shadow:inset 0 0 0 1.5px rgba(74,192,108,.55)"></i>Your picks</span>`;

  const head = `<thead><tr><th></th>${Array.from({ length: S.teams }, (_, i) =>
    `<th class="${i + 1 === S.my_slot ? "mine" : ""}">${i + 1 === S.my_slot ? "You" : "T" + (i + 1)}</th>`
  ).join("")}</tr></thead>`;

  const body = S.grid.map((row, ri) => {
    // Snake direction, so the order picks actually fall in is visible.
    const arrow = ri % 2 === 0 ? "\u2192" : "\u2190";
    const cells = row.map((c) => {
      const mine = c.mine ? " mycol" : "";
      if (c.name) {
        return `<td class="${mine.trim()}"><span class="cell filled ${c.pos}">
          <span class="cp">${c.pos}</span><span class="cn">${esc(c.name)}</span></span></td>`;
      }
      const now = c.overall === S.current_pick;
      // Round.pick reads the way drafters actually talk about picks.
      const label = `${ri + 1}.${String(((c.overall - 1) % S.teams) + 1).padStart(2, "0")}`;
      return `<td class="${mine.trim()}"><span class="cell empty ${now ? "now" : ""}">
        <span class="pk">${now ? "On the clock" : label}</span>
        ${now ? "" : `<span class="ar">${arrow}</span>`}</span></td>`;
    }).join("");
    return `<tr><th>R${ri + 1}</th>${cells}</tr>`;
  }).join("");

  $("dg").innerHTML = head + `<tbody>${body}</tbody>`;
}

refresh();
setInterval(refresh, 15000);   // safety net; every action refreshes immediately
