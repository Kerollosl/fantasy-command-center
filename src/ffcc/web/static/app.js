// Live draft board. No build step and no framework on purpose: during a draft
// the only requirement that matters is that this never fails to render.

let S = null, posFilter = "ALL", results = [], sel = 0, showGrid = false;

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
function rankSpark(seasons, pos, w = 232, h = 54) {
  const pts = seasons.filter((s) => s.rank);
  if (pts.length < 2) return `<div class="nodata">Not enough seasons to chart.</div>`;
  const L = (r) => Math.log(Math.max(r, 1));
  const maxL = Math.max(L(48), ...pts.map((s) => L(s.rank)));
  const x = (i) => 4 + (i * (w - 8)) / (pts.length - 1);
  const y = (r) => 6 + (L(r) / maxL) * (h - 24);
  const line = pts.map((s, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(s.rank).toFixed(1)}`).join("");
  const dots = pts.map((s, i) => `
    <circle cx="${x(i).toFixed(1)}" cy="${y(s.rank).toFixed(1)}" r="3.5"
      fill="var(--${pos.toLowerCase()})" stroke="var(--s1)" stroke-width="1.5"><title>${
      s.season}: ${pos}${s.rank}, ${s.points} pts in ${s.games} games</title></circle>`).join("");
  const labels = pts.map((s, i) =>
    `<text x="${x(i).toFixed(1)}" y="${h - 3}" text-anchor="middle" class="sl">${
      String(s.season).slice(2)}</text>`).join("");
  const best = pts.map((s, i) => (i === 0 || i === pts.length - 1)
    ? `<text x="${x(i).toFixed(1)}" y="${(y(s.rank) - 8).toFixed(1)}" text-anchor="middle" class="sr">${pos}${s.rank}</text>` : "").join("");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="100%" height="${h}" role="img"
    aria-label="Positional finish by season">
    <path d="${line}" fill="none" stroke="var(--${pos.toLowerCase()})" stroke-width="2"
      stroke-linejoin="round" stroke-linecap="round" opacity=".85"/>
    ${dots}${labels}${best}</svg>`;
}

function face(shot, name, size = 38) {
  const initials = String(name || "").split(/\s+/).slice(0, 2).map((w) => w[0] || "").join("");
  return shot
    ? `<img class="face" src="/headshots/${esc(shot)}" width="${size}" height="${size}" alt="" loading="lazy">`
    : `<span class="face blank" style="width:${size}px;height:${size}px">${esc(initials)}</span>`;
}

async function openProfile(key) {
  const d = await api("/api/player/" + encodeURIComponent(key));
  if (!d.ok) return;
  const panel = $("profile");
  const adj = d.adjustments.length
    ? d.adjustments.map((a) => `<li>${esc(a.note)}</li>`).join("")
    : `<li class="muted">No age or trajectory adjustment applied.</li>`;
  const rows = [...d.seasons].reverse().map((s) => `
    <tr><td>${s.season}</td><td><b>${d.pos}${s.rank}</b></td>
      <td class="num">${s.points}</td><td class="num">${s.games}</td>
      <td class="num">${s.ppg}</td></tr>`).join("");

  panel.innerHTML = `
    <div class="pf">
      <button class="pfclose" id="pfclose" aria-label="Close profile">×</button>
      <div class="pfhead">
        ${face(d.headshot, d.name, 64)}
        <div>
          <div class="pfname">${esc(d.name)}</div>
          <div class="pfmeta"><span class="pos ${d.pos}">${d.pos}</span>
            <span>${esc(d.team)}</span>
            ${d.age ? `<span>· Age ${d.age}</span>` : ""}
            ${d.bye ? `<span>· Bye ${d.bye}</span>` : ""}
            ${d.adp ? `<span>· ADP ${d.adp}</span>` : ""}</div>
        </div>
      </div>

      <h3>Positional finish by season</h3>
      ${rankSpark(d.seasons, d.pos)}
      ${d.seasons.length ? `<table class="pfseasons">
        <thead><tr><th>Season</th><th>Finish</th><th class="num">Points</th>
          <th class="num">Games</th><th class="num">Per&nbsp;game</th></tr></thead>
        <tbody>${rows}</tbody></table>` : ""}

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
  panel.hidden = false;
  $("pfclose").onclick = closeProfile;
  panel.querySelector(".pf").focus?.();
}

function closeProfile() { $("profile").hidden = true; }
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("profile").hidden) closeProfile();
});

function probRing(p, size = 56) {
  const R = 15.5, C = 2 * Math.PI * R, len = Math.max(p, 0) * C;
  return `<svg width="${size}" height="${size}" viewBox="0 0 40 40" role="img"
    aria-label="${Math.round(p * 100)} percent"><circle cx="20" cy="20" r="${R}" fill="none"
      stroke="var(--s3)" stroke-width="5"/>
    <circle cx="20" cy="20" r="${R}" fill="none" stroke="var(--good)" stroke-width="5"
      stroke-linecap="round" stroke-dasharray="${len} ${C - len}"
      transform="rotate(-90 20 20)"/>
    <text x="20" y="23.5" text-anchor="middle" class="ringtext">${Math.round(p * 100)}%</text></svg>`;
}

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
  const [top, ...rest] = S.recommendations;
  if (!top) {
    $("hero").innerHTML = `<div class="empty-state">No players left on the board.</div>`;
    $("recs").innerHTML = ""; return;
  }
  const hz = S.horizon_pick;
  const lead = S.is_my_turn ? "Take now" : "Top of your board";
  const prob = top.pick_prob;
  const tie = (top.tied_with || []).length
    ? `<div class="tie">Too close to call against ${esc(top.tied_with[0])}</div>` : "";
  $("hero").innerHTML = `
    <div class="hero" data-key="${esc(top.key)}">
      <div class="lead">${esc(lead)}</div>
      <div class="herotop">
        ${face(top.headshot, top.name, 52)}
        <div class="heroid">
          <div class="nm">${esc(top.name)}</div>
          <div class="sub"><span class="pos ${top.pos}">${top.pos}</span>
            <span>${esc(top.team)}</span>${top.age ? `<span>· ${top.age}y</span>` : ""}
            <span>· ADP ${top.adp ?? "—"}</span></div>
        </div>
        ${prob != null ? `<div class="probring">${probRing(prob)}
          <span class="problabel">chance this<br>is the pick</span></div>` : ""}
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
        ${top.value_share != null ? `<div class="drivers">
          <div class="drow"><span>Model preference</span>
            <i><b style="width:${pct(top.value_share)}%"></b></i>
            <em>${pct(top.value_share)}%</em></div>
          ${prob != null ? `<div class="drow"><span>Simulated best pick</span>
            <i><b style="width:${pct(prob)}%;background:var(--good)"></b></i>
            <em>${pct(prob)}%</em></div>` : ""}
        </div>` : ""}
        ${top.warnings.length ? `<ul class="reasons">
          ${top.warnings.map((w) => `<li class="w">${esc(w)}</li>`).join("")}</ul>` : ""}
      </div>
      <button class="pfbtn" data-profile="${esc(top.key)}">View full profile</button>
    </div>`;
  const h = $("hero").firstElementChild;
  h.querySelector(".pfbtn").onclick = (e) => { e.stopPropagation(); openProfile(top.key); };
  h.onclick = () => draft(top.key);

  const alts = rest;   // already ordered by the number each row displays
  $("recs").innerHTML = alts.map((r, i) => `
    <button class="rec" data-key="${esc(r.key)}">
      <span class="rk">${i + 2}</span>
      ${face(r.headshot, r.name, 26)}
      <span class="pos ${r.pos}">${r.pos}</span>
      <span class="nm">${esc(r.name)}</span>
      <span class="rt">${r.pick_prob != null
        ? `<b class="tnum prob">${pct(r.pick_prob)}%</b><span>best pick</span>`
        : `<b class="tnum">${signed(r.vona)}</b><span>vs next ${r.pos}</span>`}</span>
    </button>`).join("");
  [...$("recs").children].forEach((el) =>
    (el.onclick = (e) => (e.shiftKey ? draft(el.dataset.key) : openProfile(el.dataset.key))));
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
      const cells = Array.from({ length: n }, () =>
        `<i class="blk t${ti}" style="background:var(--${p.toLowerCase()})"></i>`).join("");
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
        <div class="lanefoot">${esc(d.tiers[0].names.join(" \u00b7 "))}</div>
      </div>`;
  }).join("");
}

function renderBoard() {
  $("filters").innerHTML = ["ALL", ...POS].map((p) =>
    `<button class="${p === posFilter ? "on" : ""}" data-p="${p}">${p}</button>`).join("");
  [...$("filters").children].forEach((b) =>
    (b.onclick = () => { posFilter = b.dataset.p; render(); }));

  const rows = S.players.filter((p) => posFilter === "ALL" || p.pos === posFilter).slice(0, 90);
  if (!rows.length) {
    $("board").innerHTML = `<tr><td colspan="9"><div class="empty-state">No ${posFilter} players left.</div></td></tr>`;
    return;
  }
  const maxV = Math.max(S.max_vor, 1);
  let prev = null;
  $("board").innerHTML = rows.map((p) => {
    const cliff = posFilter !== "ALL" && prev !== null && p.tier !== prev;
    prev = p.tier;
    const w = Math.max(2, (Math.max(p.vor, 0) / maxV) * 100);
    const s = p.survival;
    const flag = p.injury
      ? `<span class="flag ${p.injury === "Questionable" ? "q" : ""}">${esc(p.injury.slice(0, 4))}</span>` : "";
    return `<tr class="${cliff ? "cliff" : ""}" data-key="${esc(p.key)}">
      <td><span class="pname">${face(p.headshot, p.name, 22)}${esc(p.name)}${flag}</span></td>
      <td><span class="posdot ${p.pos}">${p.pos}</span></td>
      <td class="mut">${esc(p.team)}</td>
      <td class="num mut">${p.age ?? "—"}</td>
      <td class="num mut">${p.tier}</td>
      <td class="vbar"><i style="width:${w}%;background:var(--${p.pos.toLowerCase()})"></i><b>${p.vor}</b></td>
      <td class="num mut">${p.proj}</td>
      <td class="num mut">${p.adp ?? "—"}</td>
      <td class="num mut">${p.bye ?? "—"}</td>
      <td class="num">${s == null ? '<span class="mut">—</span>' : `
        <span class="meter"><i><b style="width:${pct(s)}%;background:${seqFor(s)}"></b></i>
        <span class="mut">${pct(s)}%</span></span>`}</td>
    </tr>`;
  }).join("");
  [...$("board").children].forEach((tr) => {
    if (!tr.dataset.key) return;
    tr.onclick = (e) => (e.shiftKey ? draft(tr.dataset.key) : openProfile(tr.dataset.key));
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
