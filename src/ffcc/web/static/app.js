// Live draft board. Kept deliberately plain: no build step, no framework.
// During a draft the only thing that matters is that this never fails to render.

let S = null;            // latest snapshot
let posFilter = "ALL";
let results = [];        // current search results
let sel = 0;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts) {
  const r = await fetch(path, opts);
  return r.json();
}

async function refresh() {
  try {
    S = await api("/api/state");
    render();
    $("status").textContent = "";
  } catch (e) {
    $("status").textContent = "connection lost — data shown may be stale";
  }
}

// ---- pick entry -------------------------------------------------------
async function search(q) {
  if (!q.trim()) { results = []; drawDrop(); return; }
  results = await api("/api/search?q=" + encodeURIComponent(q));
  sel = 0;
  drawDrop();
}

function drawDrop() {
  const d = $("drop");
  if (!results.length) { d.hidden = true; d.innerHTML = ""; return; }
  d.hidden = false;
  d.innerHTML = results.map((p, i) => `
    <div class="${i === sel ? "sel" : ""}" data-key="${esc(p.key)}">
      <span class="pos ${p.pos}">${p.pos}</span>
      <b>${esc(p.name)}</b>
      <span class="mut">${esc(p.team)}</span>
      <span class="mut" style="margin-left:auto">ADP ${p.adp ?? "—"} · VOR ${p.vor}</span>
    </div>`).join("");
  [...d.children].forEach(el =>
    el.onclick = () => draft(el.dataset.key));
}

async function draft(key) {
  const r = await api("/api/pick", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key })
  });
  if (!r.ok) { $("status").textContent = r.error; return; }
  $("q").value = ""; results = []; drawDrop();
  await refresh();
}

$("q").addEventListener("input", e => search(e.target.value));
$("q").addEventListener("keydown", e => {
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
// Keep focus in the search box; entry speed is the whole point.
document.addEventListener("keydown", e => {
  if (e.key === "/" && document.activeElement !== $("q")) { e.preventDefault(); $("q").focus(); }
});

// ---- rendering --------------------------------------------------------
function survClass(s) { return s >= .7 ? "s-hi" : s >= .3 ? "s-md" : "s-lo"; }

function render() {
  if (!S) return;

  $("league").textContent = " · " + S.league;
  $("pickno").textContent = `${S.current_pick} / ${S.total_picks}`;
  $("clock").textContent = S.complete ? "done" : `Team ${S.on_clock}`;
  $("mynext").textContent = S.my_next_pick ?? "—";
  $("until").textContent = S.picks_until_mine;
  const t = $("turn");
  t.className = "turn " + (S.is_my_turn ? "me" : "them");
  t.textContent = S.complete ? "Draft complete"
    : S.is_my_turn ? "YOU ARE ON THE CLOCK" : `Team ${S.on_clock} picking`;

  // recommendations
  $("recs").innerHTML = S.recommendations.length ? S.recommendations.map((r, i) => `
    <div class="rec ${i === 0 ? "top" : ""}" data-key="${esc(r.key)}">
      <div class="hd">
        <span class="pos ${r.pos}">${r.pos}</span>
        <span class="nm">${esc(r.name)}</span>
        <span class="mut">${esc(r.team)}</span>
        <span class="sc">${r.score}</span>
      </div>
      <ul>
        ${r.reasons.map(x => `<li>${esc(x)}</li>`).join("")}
        ${r.warnings.map(x => `<li class="warn">${esc(x)}</li>`).join("")}
      </ul>
    </div>`).join("") : `<div class="empty">No players available.</div>`;
  [...$("recs").children].forEach(el => {
    if (el.dataset.key) el.onclick = () => draft(el.dataset.key);
  });

  // positional pace (hazards)
  const hz = Object.entries(S.hazards || {}).sort((a, b) => b[1] - a[1]);
  $("hazards").innerHTML = hz.length
    ? hz.map(([p, v]) =>
        `<span class="hz ${v > 1.35 ? "hot" : ""}">${p} ${v.toFixed(2)}×</span>`).join("")
    : `<span class="mut" style="font-size:11.5px">Learns your league's pace once picks are entered.</span>`;

  // recent picks
  $("recent").innerHTML = S.recent.length
    ? [...S.recent].reverse().map(p =>
        `<div><span class="mut">${p.overall}</span><span class="pos ${p.pos}">${p.pos}</span>
         ${esc(p.name)}<span class="mut" style="margin-left:auto">T${p.slot}</span></div>`).join("")
    : `<div class="empty">No picks entered yet.</div>`;

  // filters
  const positions = ["ALL", "RB", "WR", "TE", "QB", "DEF", "K"];
  $("filters").innerHTML = positions.map(p =>
    `<button class="${p === posFilter ? "on" : ""}" data-p="${p}">${p}</button>`).join("");
  [...$("filters").children].forEach(b =>
    b.onclick = () => { posFilter = b.dataset.p; render(); });

  // board
  const rows = S.players.filter(p => posFilter === "ALL" || p.pos === posFilter).slice(0, 90);
  let prevTier = null;
  $("board").innerHTML = rows.map(p => {
    const cliff = posFilter !== "ALL" && prevTier !== null && p.tier !== prevTier;
    prevTier = p.tier;
    const flag = p.injury ? `<span class="flag">${esc(p.injury)}</span>` : "";
    const s = p.survival;
    return `<tr class="${cliff ? "cliff" : ""}" data-key="${esc(p.key)}">
      <td>${esc(p.name)}${flag}</td>
      <td><span class="pos ${p.pos}">${p.pos}</span></td>
      <td class="mut">${esc(p.team)}</td>
      <td class="num mut">${p.tier}</td>
      <td class="num">${p.vor}</td>
      <td class="num mut">${p.proj}</td>
      <td class="num mut">${p.adp ?? "—"}</td>
      <td class="num mut">${p.bye ?? "—"}</td>
      <td class="num ${s == null ? "mut" : survClass(s)}">${s == null ? "—" : Math.round(s * 100) + "%"}</td>
    </tr>`;
  }).join("");
  [...$("board").children].forEach(tr => tr.onclick = () => draft(tr.dataset.key));

  // my roster
  const me = S.grades.find(g => g.is_me);
  $("roster").innerHTML = me && me.roster.length
    ? me.roster.map(p =>
        `<div class="slot"><span class="lb">${p.overall}</span>
         <span class="pos ${p.pos}">${p.pos}</span>${esc(p.name)}</div>`).join("")
    : `<div class="empty">Nothing drafted yet.</div>`;

  // needs
  const needs = Object.entries(S.needs || {}).filter(([, v]) => v > 0);
  $("needs").innerHTML = needs.length
    ? needs.map(([k, v]) => `<span class="need">${k} ×${v}</span>`).join("")
    : `<span class="need ok">All starting slots filled</span>`;

  // grades
  $("conf").textContent = `Confidence: ${S.grades[0]?.confidence ?? "low"}` +
    (S.grades[0]?.confidence === "low" ? " — early grades are noisy by nature." : "");
  $("grades").innerHTML = [...S.grades].sort((a, b) => b.score - a.score).map(g => `
    <div class="grade ${g.is_me ? "me" : ""}">
      <div class="g1">
        <span class="lt">${g.letter}</span>
        <span class="tm">Team ${g.slot}${g.is_me ? " (you)" : ""}</span>
        <span class="cmp">lineup ${g.slp} · value ${g.vas > 0 ? "+" : ""}${g.vas}</span>
      </div>
      ${g.notes.length ? `<div class="nt">${esc(g.notes.join(" · "))}</div>` : ""}
      <div class="rs">${g.roster.map(p => esc(p.name)).join(", ") || "—"}</div>
    </div>`).join("");

  $("resolution").textContent = S.resolution;
}

refresh();
setInterval(refresh, 15000);   // safety net; every action refreshes immediately
