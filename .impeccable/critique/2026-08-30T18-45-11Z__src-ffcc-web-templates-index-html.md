---
target: the live draft board UI (src/ffcc/web/templates/index.html)
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
timestamp: 2026-08-30T18-45-11Z
slug: src-ffcc-web-templates-index-html
---
Method: dual-agent (A: design review · B: detector + browser evidence), run as two isolated parallel sub-agents.

Target: the live draft board — `src/ffcc/web/templates/index.html` + `static/style.css` + `static/app.js`, inspected running at `http://127.0.0.1:8009/` with ~28 picks entered. Mode: **Operate** (a draft instrument, not a marketing page).

---

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | "Server lost — last good board" fallback is excellent; but recording a pick gives no confirmation of *what* landed, and the grade shows "A+ · 1st of 12" at zero picks |
| 2 | Match System / Real World | 4 | Fluent draft vocabulary — round.pick labels, "on the clock", "reaches", handcuff, VONA rendered as plain English, snake arrows |
| 3 | User Control and Freedom | 2 | The only correction is a blind last-in-first-out Undo — no redo, no per-pick edit, no way to fix a room desync |
| 4 | Consistency and Standards | 3 | Strong internal system, but the primary click target (a row) opens info, not the primary action (draft); sub-11px sizing is at least applied consistently |
| 5 | Error Prevention | 2 | An unconfirmed quick-draft ✓ on every row / card / hero is one stray click from permanently burning a real pick |
| 6 | Recognition Rather Than Recall | 3 | The headline output (survival %) and ADP are off the right edge at rest — you must remember they exist and horizontal-scroll for them mid-clock |
| 7 | Flexibility and Efficiency | 3 | `/`, type-ahead + Enter, `d`, `u`, click-any-surface are genuinely fast — but everything past the command bar and hero is mouse-only |
| 8 | Aesthetic and Minimalist Design | 2 | Three collinear value-rank columns (Predicted, Tier, VOR bar) on screen while ADP + survival are hidden; `recent[]` sent by the API and never drawn; 200+ elements below the 11px text floor |
| 9 | Help Users Recover from Errors | 2 | Pick errors surface only as a thin 10.5px red string in a footer nobody is watching; Undo names nothing |
| 10 | Help and Documentation | 1 | Every bespoke metric (tier, VOR, VONA, Model/Best, survival horizon) is explained only in hover-only `title` tooltips or an un-linked README — no `?` layer, no first-run read guide |
| **Total** | | **25 / 40** | **Acceptable — significant improvements needed before users are happy** |

Applicable maximum: 40 (all ten heuristics scored; none n/a — this is a power-user tool, so 7 and 10 apply).

---

## Design Specificity Verdict

**Start here.** Does it feel authored for *this* product, or category-interchangeable?

**LLM assessment:** ~65% authored for this product, ~35% generic dark-dashboard chrome. The *information model* is genuinely bespoke; the *visual identity* is off-the-shelf.

*Authored:* the tier-ladder block primitive ("1 left at this value, then −22.5 pts" with hoverable per-player squares + an urgent border) encodes the hardest mid-draft judgment into one glanceable object; a deliberate visual-form taxonomy (donut = part-to-whole for roster shape only, bar = magnitude for VOR, meter = probability for survival, sequential teal ramp for "how much / how likely" that never borrows the reserved green/amber/red); position color as a validated CVD-checked categorical palette with the chrome-accent blue held distinct from the WR data-blue; the "TAKE NOW / press D" hero and the `d` key that only fires on your turn; the snake-aware grid where cells sit in the owning team's column; VONA measured past your back-to-back pick; the "disagreement" sentence that explains model-vs-simulation divergence in plain language instead of silently picking a winner.

*Generic:* the shell — three columns, 9.5px uppercase micro-labels, a header row of tiny stat blocks, thin accent-blue, cards-in-cards, muted cool palette — is the standard SaaS-analytics uniform; swap the words and it's an observability tool. The best-available table is a plain 13-column sortable data grid; nothing but the content says "draft." Bricolage Grotesque + Space Mono sits in neutral — neither "war room" energy nor deliberate instrument restraint. The recap is an undesigned modal.

Three places the generic chrome costs real task performance: (a) the plain table exiles the tool's headline output (survival) off-screen; (b) the hero doesn't take over on your turn; (c) the recommendation oscillates because the "auto-refreshing dashboard" pattern was never tuned for "the user is mid-decision."

**Deterministic scan:**
- **Source file** (`index.html`): clean, exit 0 — it's a 111-line skeleton; all styling and content are external (not a detector miss).
- **Live URL, desktop 1440×900**: exit 2, **291 findings** — `undersized-ui-text` ×200 (9.5px column headers, 8.5–9px badges, 10.5px player-name rows), `low-contrast` ×44 (`#4e5a66` at **~2.5–2.6:1**, `#75838f` at **~4.1–4.45:1**, both under the 4.5:1 AA line), `tiny-text` ×25, `text-occlusion` ×13 (notably the "Bye" and "Still there?" column headers reported 50% covered by an `h2` at desktop width — did not reproduce narrower, likely a scroll-transient), `ai-color-palette` ×6 ("cyan neon on dark"), `gpt-thin-border-wide-shadow` ×2, `em-dash-overuse` ×1.
- **Live URL, mobile 390×844**: exit 2, **278 findings** — an essentially identical set (the layout is locked at `min-width:1140px` and never reflows), plus a mobile-only `body-text-viewport-edge` ×2 (paragraph text ~13px from the screen edge).

The detector's own "AI slop" heuristics (`ai-color-palette`, `gpt-thin-border-wide-shadow`) independently flagged the same generic-dashboard shell the design review identified by eye.

**False positives:** `em-dash-overuse` (56) is a miscount — the template uses `—` as the null/placeholder glyph in empty stat chips (`<b id="pickno">—</b>`) and `−` as a minus sign in "then −11.1 pts", not as prose. `ai-color-palette` is technically right that the palette reads as a dashboard tell, but the teal ramp is a documented, CVD-validated OKLCH sequential scale, not lazy neon. `gpt-thin-border-wide-shadow` ×2 is ordinary dropdown styling, low signal.

**Visual overlay:** `detect.js` was injected into a live render (463 overlay nodes, ~280 findings) inside the detector agent's own ephemeral tab, which has since been closed — **there is no persistent overlay in your browser.** The counts above are the reliable artifact.

---

## Overall Impression

Someone who deeply understands fantasy drafts built a competent dark dashboard — the data model and the copy are excellent, the visualization discipline is real, and the core keyboard loop is fast. But it reads as "a competent dashboard *about* drafting," not "a draft *instrument*." The single biggest opportunity: **the screen never changes when it's your turn.** The one moment the whole tool exists for — 20 seconds on the clock — gets the same three-column layout as every other moment, and the one number the tool is built on (survival) is off the right edge. Make the clock moment take over, pull the headline number onto the fold, and stop the #1 pick from reshuffling while the user is deciding.

---

## What's Working

1. **The visual-form taxonomy.** Bar / meter / donut / ladder, plus a sequential teal ramp for magnitude that never touches the reserved green/amber/red. Once you learn "teal = how much or how likely" and "green-amber-red = status," every panel is readable without a legend, and the alarm colors stay trustworthy because no data series borrows them. The CSS comments prove it's a governed system, not an accident.
2. **The scarcity ladder as a bespoke primitive.** "1 left at this value, then −22.5 pts" + urgent border + hoverable per-player blocks answers "can I wait?" faster than any table row — a rare visualization whose shape matches the shape of the decision.
3. **The command bar + `D` path.** Type-ahead results carry pos / team / ADP / VOR for disambiguation; `/` focuses, Enter records, `d` drafts the top rec on your turn. The fast path *is* the default path, not a hidden mode — the 90% action costs one keystroke and never needs the mouse.

---

## Priority Issues

### [P1] The board buries the tool's headline output off-screen
- **What:** At any realistic laptop width the best-available table needs a horizontal scroll — past Proj — to reveal "Still there?" (survival) and ADP. The README calls survival a primary column; the whole tool is built on it. Meanwhile Predicted rank, Tier, and the VOR bar (three views of the same ranking) all sit on the fold, and "Last Yr" rank earns a column survival doesn't.
- **Why it matters:** "Will he last to my next pick?" is the exact question you ask *before* deciding to wait. Forcing a horizontal scroll plus a memory hold, mid-clock, defeats the feature.
- **Fix:** drop "Last Yr" and "Age" from the default board (both already live in the profile); pull Survival and ADP left of the fold, or right-pin Survival as a sticky column; consider merging Predicted + Tier into one cell.
- **Suggested command:** `/impeccable layout`

### [P1] The hero recommendation oscillates between refreshes
- **What:** Same pick number, same roster — the "Top of your board" headline flips between Tyler Warren and Drake Maye across refreshes, the disagreement sentence rewrites itself, and the compare percentages jitter (33 → 34 → 32 → 31%). It's Monte-Carlo noise re-seeded on the 15-second `setInterval(refresh)`. The `flashSeen` change-flash even highlights the jitter, training you to ignore flashes.
- **Why it matters:** the hero is the largest element on the page and the target of the `D` keystroke. Watching your #1 change *name* while you decide is a trust-killer, and pressing `D` may draft a different player than the one you were looking at 3 seconds ago.
- **Fix:** freeze the hero's #1 for the duration of your turn (unfreeze only when a real pick mutates state); when two candidates fall inside the tie band, break the tie deterministically (higher raw model value, or lower ADP) and hold it; seed the simulation RNG per snapshot and/or raise sim count so idle refreshes stop moving the numbers. (The RNG-seed part is a backend change in `montecarlo.py` / `app.py`.)
- **Suggested command:** `/impeccable harden`

### [P1] The type system fails the read test — too small and too dim
- **What:** 200+ functional elements below the 11px floor (9.5px for *every* column header and stat caption, 8.5–9px for badges, 10.5px for player-name rows), and the label greys fail WCAG AA: `#4e5a66` at ~2.5–2.6:1 carries every `h2`, every `th`, every stat caption, the grid's empty-cell labels and the footer; `#75838f` at ~4.1–4.45:1 carries most secondary numbers and helper text. Confirmed by both the design review (by role) and the detector (by measurement), in every viewport.
- **Why it matters:** this is an Operate tool meant to be read "in a loud room, at a glance." If the labels that tell you *what each number is* are 9.5px at 2.6:1, a glance under glare or stress doesn't land — and a keyboard/low-vision user can't read the column headers at all.
- **Fix:** raise the functional text floor to 11px (12px for anything read row-by-row); raise any grey used for text to ≥3.5:1 and ideally ~4.6:1 for ≤12px; reserve the darkest greys for non-text hairlines only. Pay the density budget by cutting columns and panels, not by shrinking type.
- **Suggested command:** `/impeccable typeset`

### [P2] Destructive pick entry has no confirmation, no visible undo, and a hair-trigger
- **What:** `draft()` clears the input and re-renders with no "✓ recorded Josh Allen → Team 6." The Undo button throws away the player name the API returns, so it's a blind LIFO — a mistake two picks back means unwinding a correct pick to reach it. And the unconfirmed quick-draft ✓ appears on every board-row hover, every rec card, and always-on at 38px on the hero — one stray click during a fast scroll permanently records a real pick.
- **Why it matters:** in a loud room with fast picks you cannot tell if your entry landed or whether you took the wrong "Jefferson," and the recovery tool is an opaque black box that eats good picks.
- **Fix:** a transient toast after every pick with an inline "undo that" for ~8 seconds; surface the returned name on the Undo button ("Removed: Ashton Jeanty"); a 1-step "Draft Josh Allen? ✓" micro-confirm on the row/list ✓ variants; "edit pick" from the grid.
- **Suggested command:** `/impeccable harden` (plus `/impeccable clarify` for the confirmation / undo copy)

### [P3] The recap is a neglected modal — and it's the last thing the user feels
- **What:** a cramped 560px modal that reads like a debug dump — grade letter, best-value / reaches lists, a roster table whose `.tag` text collides into the "Full roster" heading. No team identity, no verdict sentence, no shareable artifact for the league chat.
- **Why it matters:** peak-end theory says the ending disproportionately colors the memory of the whole three-hour experience. This ending undersells the tool.
- **Fix:** make it a full-surface view (reuse the grid's real estate), lead with the grade + a one-line verdict, give best-value / reaches real visual treatment, add "copy summary."
- **Suggested command:** `/impeccable shape`

---

## Persona Red Flags

**Alex (power user — keyboard-everything, drafts fast, hates detours)**
- `d` is advertised only by a 10px `D` kbd in the hero; `u` (undo) is hinted nowhere.
- No keyboard traversal past the command bar and hero — the board table, the 8 position-filter buttons, the compare list, the slim rec list are all mouse-only. Can't arrow down the board and hit Enter.
- `e.key === "d"` won't match `"D"` — with Shift or Caps Lock held, the shortcut silently dies.
- The `D` target may have changed since he last looked (hero oscillation) — the keystroke isn't trustworthy.
- Clicking a board row opens the profile modal, not a draft; the only draft-from-board affordance is the hover-only ✓.

**Sam (accessibility — keyboard / screen reader / low vision)**
- Contrast: `#4e5a66` body text at ~2.6:1 fails AA across every `h2`, every `th`, every stat caption, the grid's empty-cell labels and the footer; `#75838f` at ~4.4:1 fails on the 9.5px "BEST / MODEL" micro-labels and on tinted rows.
- Modal focus is not trapped: `openProfile` focuses a `<div>` with no `tabindex`, no focus cycling, no return-focus-on-close, no `role="dialog"` / `aria-modal`. Tab walks into the board behind the open modal; a screen reader is never told a dialog opened. Same for the recap.
- Color-only encodings with no text / pattern fallback: tier-ladder blocks, pace bars, donut segments, the grade bar. (The board's "Pos" text column *is* a proper fallback for the row tint — credit there.)
- Bars / meters are bare `<div>`s with inline `width` — no `role="progressbar"`, no `aria-valuenow`.
- The 15-second auto-refresh re-renders the board and destroys focus if Sam is tabbing through rows.
- Metric documentation lives only in hover `title` attributes — unreliable for SR, invisible on touch.
- At 200% browser zoom the `min-width:1140px` wrap forces the whole app into horizontal scroll — reflow is broken.

**Casey (distracted, interrupted, possibly on a phone / tablet in the draft room)**
- Mobile is a fallback, not a design: `.wrap{min-width:1140px}` + `body{overflow:hidden}` says "laptop only." The stacked layout drops the columns into a very long scroll and the board stays a horizontal-scroll region (`table{min-width:620px}`) inside a 390px viewport. The detector confirms the layout never reflows — desktop and mobile produce the same findings.
- The header is not sticky in the stacked layout — scroll to the board on a phone and you lose "on the clock," "picks away," and "my next pick," the exact context you need after an interruption.
- No "what did I miss": the API already sends `recent` (last 12 picks); the UI never renders it.
- No pick confirmation — the interrupted "did I enter that?" has to be answered by hunting the roster.
- Touch + the hover-revealed ✓: `tr:focus-within` also reveals the ✓, so a second tap can land on the permanent action; the hero's always-on 38px ✓ sits a fat-finger from "View full profile."

---

## Minor Observations

- `recent[]` is sent by `snapshot()` and never rendered — a recent-picks ticker is free and would directly serve "what did I miss."
- "My next pick 24" shows while you are currently on the clock at pick 1 — mildly confusing; could read "now, then 24."
- Grade cards render each roster as a run-on comma string that ellipsis-truncates — a row of position chips would read faster.
- The VOR bar fill is `rgba(255,255,255,.16)` — so faint it barely reads as a bar, undercutting the "scan a column of bars" claim.
- The survival meter is 34×5px — too small to read as a meter; between 21% and 40% the fill differs by ~6px. It's decoration beside the real signal (the %).
- The round-insight strip frequently spends prime top-of-column space to say "No clear positional edge here."
- Grade "A+ · 1st of 12" shows at pick 1 with zero picks and every team identical — false precision the README elsewhere says it avoids.
- The `flashSeen` change-flash fires on Monte-Carlo jitter, highlighting numbers that didn't really change.
- Profile backdrop is only `rgba(6,9,12,.68)` — the busy board stays clearly legible behind the modal, competing with the content the modal exists to present.
- `text-occlusion` on the "Bye" / "Still there?" headers at 1440×900 (detector) — likely a scroll-transient between the sticky `th` and the `h2`, but worth a visual check.
- `.qcol` header carries `aria-label="Quick draft"` — a screen reader announces a "Quick draft" column of mostly-empty cells on every row.
- Mobile-only: paragraph text sits ~13px from the screen edge at 390px (detector `body-text-viewport-edge`).

---

## Questions to Consider

- On your turn, why is the hero still one column of three? What if the center and left collapsed into a single "here's the pick, here's the one reason, draft it or browse the field," and the full board only returned when you actively asked for it?
- The tool's whole thesis is "what do I lose by waiting" — so why isn't VONA the biggest number on the screen, and why is there no board column for it, while three columns compete to show the same value ranking?
- If two candidates are genuinely a coin flip, is a flickering #1 honest? What does a UI look like that says "these two are tied — here's the tiebreak for *your* roster" instead of re-rolling the headline every 15 seconds?
- Who is the real user — someone at a laptop with the draft site in another tab, or someone on their phone in the room? If the phone is ever in scope, the current stacked fallback isn't a decision, it's an absence of one.
- What's the actual cost of one dismissible "how to read this board" layer on first run — versus the cost of not having it when someone opens this 90 seconds before their draft?
