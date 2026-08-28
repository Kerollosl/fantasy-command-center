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
  const headline = top.reasons[1] || top.reasons[0] || "";
  $("hero").innerHTML = `
    <div class="hero" data-key="${esc(top.key)}" role="button" tabindex="0">
      <div class="lead">${esc(lead)}</div>
      <div class="nm">${esc(top.name)}</div>
      <div class="sub"><span class="pos ${top.pos}">${top.pos}</span>
        <span>${esc(top.team)}</span><span>·</span><span>ADP ${top.adp ?? "—"}</span>
        <span>·</span><span>Tier ${top.tier}</span></div>
      <div class="why">
        <div class="metric"><b class="tnum">${signed(top.vona)}</b>
          <span>points over the next ${top.pos} you'd realistically get</span></div>
        <div class="metric"><b class="tnum">${pct(top.survival)}%</b>
          <span>chance he is still there at pick ${hz ?? "—"}${
            hz && S.my_next_pick && hz !== S.my_next_pick
              ? ` <span style="color:var(--fg-4)">(you also pick at ${S.my_next_pick})</span>` : ""}</span></div>
        ${top.warnings.length ? `<ul class="reasons" style="margin-left:0">
          ${top.warnings.map((w) => `<li class="w">${esc(w)}</li>`).join("")}</ul>` : ""}
      </div>
    </div>`;
  const h = $("hero").firstElementChild;
  h.onclick = () => draft(top.key);
  h.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); draft(top.key); } };

  const alts = [...rest].sort((a, b) => b.vona - a.vona);
  $("recs").innerHTML = alts.map((r, i) => `
    <button class="rec" data-key="${esc(r.key)}">
      <span class="rk">${i + 2}</span>
      <span class="pos ${r.pos}">${r.pos}</span>
      <span class="nm">${esc(r.name)}</span>
      <span class="rt"><b class="tnum" style="${r.vona < 0 ? "color:var(--fg-3)" : ""}">${signed(r.vona)}</b><span>vs next ${r.pos}</span></span>
    </button>`).join("");
  [...$("recs").children].forEach((el) => (el.onclick = () => draft(el.dataset.key)));
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
      <td><span class="pname">${esc(p.name)}${flag}</span></td>
      <td><span class="pos ${p.pos}">${p.pos}</span></td>
      <td class="mut">${esc(p.team)}</td>
      <td class="num mut">${p.tier}</td>
      <td class="vbar"><i style="width:${w}%"></i><b>${p.vor}</b></td>
      <td class="num mut">${p.proj}</td>
      <td class="num mut">${p.adp ?? "—"}</td>
      <td class="num mut">${p.bye ?? "—"}</td>
      <td class="num">${s == null ? '<span class="mut">—</span>' : `
        <span class="meter"><i><b style="width:${pct(s)}%;background:${seqFor(s)}"></b></i>
        <span class="mut">${pct(s)}%</span></span>`}</td>
    </tr>`;
  }).join("");
  [...$("board").children].forEach((tr) => tr.dataset.key && (tr.onclick = () => draft(tr.dataset.key)));
}

function renderRoster() {
  const me = S.grades.find((g) => g.is_me);
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
      <div class="g1"><span class="lt">${g.letter}</span>
        <span class="tm">Team ${g.slot}${g.is_me ? " · you" : ""}</span>
        <span class="sp">${g.roster.length} pick${g.roster.length === 1 ? "" : "s"} · ${g.slp} pts</span></div>
      <div class="gbar"><i style="width:${Math.max(3, ((g.score - lo) / span) * 100)}%"></i></div>
      ${g.notes.length ? `<div class="nt">${esc(g.notes.join(" · "))}</div>` : ""}
      <div class="rs">${g.roster.length ? esc(g.roster.map((p) => p.name).join(", ")) : "No picks yet"}</div>
    </div>`).join("");
}

function renderGrid() {
  const head = `<thead><tr><th></th>${Array.from({ length: S.teams }, (_, i) =>
    `<th>T${i + 1}${i + 1 === S.my_slot ? " ★" : ""}</th>`).join("")}</tr></thead>`;
  const body = S.grid.map((row, ri) => `<tr><th>R${ri + 1}</th>${row.map((c) => `
    <td><div class="cell ${c.mine ? "mine" : ""} ${c.name ? "" : "empty"}">
      ${c.name ? `<span class="cp" style="color:var(--${c.pos.toLowerCase()}-t,var(--fg-3))">${c.pos}</span>
        <span class="cn">${esc(c.name)}</span>` : `<span class="cn mut">${c.overall}</span>`}
    </div></td>`).join("")}</tr>`).join("");
  $("dg").innerHTML = head + `<tbody>${body}</tbody>`;
}

refresh();
setInterval(refresh, 15000);   // safety net; every action refreshes immediately
