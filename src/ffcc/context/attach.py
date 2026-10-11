"""Apply team-context signals to players: display fields plus a modest,
capped nudge to proj_points. Runs after the history/market blend and before
VOR, so replacement level and every downstream number reflect the adjusted
points -- same contract as the age/trajectory adjustments in projections.blend.

Weights are kept deliberately small. This is corroborating context on top of
a projection already built from ADP + own production + aging, not a signal
strong enough to override any of them.
"""
from __future__ import annotations

OLINE_POSITIONS = ("RB", "QB")
OLINE_WEIGHT = {"RB": 0.06, "QB": 0.03}   # max +/- swing at |z| >= 1.5
SOS_WEIGHT = 0.05                          # max +/- swing at |z| >= 1.5
PLAYOFF_SOS_WEIGHT = 0.03                  # smaller, additive on top of full-season SOS -- correlated signal
VACATED_WEIGHT = {"RB": 0.15, "WR": 0.15, "TE": 0.12}
REDZONE_WEIGHT = {"RB": 0.05, "WR": 0.04, "TE": 0.04}
REDZONE_BASELINE = 0.15   # a roughly "average committed weapon" share of a team's red-zone touches

CURRENT_SEASON_LENGTH = 17   # 17-game seasons started 2021; older seasons were 16


def _clip(z: float, lim: float = 1.5) -> float:
    return max(-lim, min(lim, z))


def _durability(seasons: list[dict]) -> tuple[float | None, int | None]:
    """Career-average share of a season's games actually played.

    Display only -- baseline_projection() already discounts proj_points for
    missed games via its own exp_games calculation, so a second nudge here
    would double-count the same signal.
    """
    if not seasons:
        return None, None
    fracs = []
    for s in seasons:
        expected = CURRENT_SEASON_LENGTH if s["season"] >= 2021 else 16
        fracs.append(min(1.0, s["games"] / expected))
    return round(sum(fracs) / len(fracs), 2), len(fracs)


def attach_context(players, ctx: dict) -> None:
    teams = (ctx or {}).get("teams", {})

    for p in players:
        t = teams.get(p.team)
        if not t:
            continue

        ol = t.get("oline")
        cont = t.get("oline_continuity")
        if p.position in OLINE_POSITIONS and ol and ol.get("score") is not None:
            p.oline_rank = ol.get("rank")
            p.oline_score = ol.get("score")
            eff = ol["score"]
            if cont and cont.get("continuity") is not None:
                p.oline_continuity = cont["continuity"]
                p.oline_returning = cont.get("returning")
                p.oline_total = cont.get("total")
                p.oline_departed = cont.get("departed") or []
                eff *= 0.5 + 0.5 * cont["continuity"]
            factor = 1.0 + OLINE_WEIGHT[p.position] * (_clip(eff) / 1.5)
            if abs(factor - 1.0) > 0.005:
                p.proj_points = round(p.proj_points * factor, 1)
                trend = f", {cont['returning']}/{cont['total']} starters back" if cont else ""
                p.adjustments.append({
                    "kind": "oline", "factor": round(factor, 3),
                    "note": f"O-line ranked {ol['rank']}/32 last season{trend}: "
                            f"{(factor - 1) * 100:+.0f}%",
                })

        sos = (t.get("sos") or {}).get(p.position)
        rank = (t.get("sos_rank") or {}).get(p.position)
        if p.position in ("QB", "RB", "WR", "TE") and sos is not None and rank is not None:
            p.sos_score = sos
            p.sos_rank = rank
            factor = 1.0 + SOS_WEIGHT * (_clip(sos) / 1.5)
            if abs(factor - 1.0) > 0.005:
                p.proj_points = round(p.proj_points * factor, 1)
                p.adjustments.append({
                    "kind": "schedule", "factor": round(factor, 3),
                    "note": f"schedule vs {p.position} ranks {rank}/32 easiest, "
                            f"by last season's defenses: {(factor - 1) * 100:+.0f}%",
                })

        psos = (t.get("playoff_sos") or {}).get(p.position)
        prank = (t.get("playoff_sos_rank") or {}).get(p.position)
        if p.position in ("QB", "RB", "WR", "TE") and psos is not None and prank is not None:
            p.playoff_sos_score = psos
            p.playoff_sos_rank = prank
            factor = 1.0 + PLAYOFF_SOS_WEIGHT * (_clip(psos) / 1.5)
            if abs(factor - 1.0) > 0.005:
                p.proj_points = round(p.proj_points * factor, 1)
                p.adjustments.append({
                    "kind": "playoff_schedule", "factor": round(factor, 3),
                    "note": f"fantasy-playoff schedule (weeks 15-17) vs {p.position} ranks "
                            f"{prank}/32 easiest: {(factor - 1) * 100:+.0f}%",
                })

        rz = (t.get("redzone") or {}).get(p.gsis_id) if p.gsis_id else None
        if p.position in REDZONE_WEIGHT and rz:
            p.redzone_share = rz["share"]
            p.redzone_touches = rz["touches"]
            gap = (rz["share"] - REDZONE_BASELINE) / REDZONE_BASELINE
            factor = 1.0 + REDZONE_WEIGHT[p.position] * max(-1.0, min(1.5, gap))
            if abs(factor - 1.0) > 0.005:
                p.proj_points = round(p.proj_points * factor, 1)
                p.adjustments.append({
                    "kind": "redzone", "factor": round(factor, 3),
                    "note": f"{rz['share'] * 100:.0f}% of his team's red-zone touches last season "
                            f"({rz['touches']}): {(factor - 1) * 100:+.0f}%",
                })

        if p.position == "QB":
            wp = t.get("weapons") or {}
            if wp.get("added") or wp.get("lost"):
                p.weapons_added = wp.get("added") or []
                p.weapons_lost = wp.get("lost") or []
                p.weapons_added_total = wp.get("added_total")
                p.weapons_lost_total = wp.get("lost_total")

        durability, seasons_n = _durability(p.seasons)
        if durability is not None:
            p.durability = durability
            p.durability_seasons = seasons_n

    # Vacated share needs each player's slice of his own team-position group,
    # which requires every player's proj_points already settled above.
    groups: dict[tuple, list] = {}
    for p in players:
        if p.position in VACATED_WEIGHT:
            groups.setdefault((p.team, p.position), []).append(p)

    for (team, pos), grp in groups.items():
        t = teams.get(team)
        vac = ((t or {}).get("vacated") or {}).get(pos)
        if not vac or not vac.get("share"):
            continue
        total = sum(pl.proj_points for pl in grp) or 1.0
        for pl in grp:
            pl.vacated_share = vac["share"]
            pl.vacated_departed = vac.get("departed") or []
            own_share = pl.proj_points / total
            factor = 1.0 + VACATED_WEIGHT[pos] * vac["share"] * own_share
            if abs(factor - 1.0) > 0.005:
                pl.proj_points = round(pl.proj_points * factor, 1)
                names = ", ".join(d["name"] for d in vac["departed"][:2]) or "departed players"
                word = "carries" if pos == "RB" else "targets"
                pl.adjustments.append({
                    "kind": "vacated", "factor": round(factor, 3),
                    "note": f"team vacated {vac['share'] * 100:.0f}% of last year's {pos} "
                            f"{word} ({names}): {(factor - 1) * 100:+.0f}%",
                })


def attach_handcuffs(players) -> None:
    """Flag each RB's immediate backup by depth chart order, same team.

    Display only -- there's no defensible proj_points adjustment for "your
    RB1 has good injury insurance." Draft/lineup value, not a projection input.
    """
    by_team: dict[str, list] = {}
    for p in players:
        if p.position == "RB":
            by_team.setdefault(p.team, []).append(p)

    for grp in by_team.values():
        ordered = sorted((p for p in grp if p.depth_chart_order), key=lambda p: p.depth_chart_order)
        for i, p in enumerate(ordered[:-1]):
            nxt = ordered[i + 1]
            p.handcuff_key = nxt.key
            p.handcuff_name = nxt.name
