"""Builds a full prediction (the data behind a prediction card) for one fixture."""
from __future__ import annotations

from . import adjustments as adj
from .core import (STATS, Params, count_probabilities, goal_probabilities, league_means,
                   promoted_prior, season_ratios, strength, team_prior, team_records)
from .views import Views

STAT_LABEL = {"goals": "goals", "corners": "corners", "cards": "cards",
              "shots": "shots", "shots_on_target": "shots on target"}

import json
import os

_TUNED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tuned.json")


def load_tuned():
    """Parameters chosen by the backtest (backtest/run.py writes model/tuned.json)."""
    if not os.path.exists(_TUNED):
        return Params(), {}
    with open(_TUNED) as f:
        t = json.load(f)
    return Params(**t["params"]), t["tuning"]


# Fallbacks if tuned.json is missing.
DEFAULT_TUNING = {"momentum_coef": 0.0, "derby_cards": 1.10, "referee_k": 1e9}


class Predictor:
    """One league-season. `prev_seasons` are complete earlier seasons, oldest first."""

    def __init__(self, league, prev_seasons, params: Params | None = None, tuning=None):
        self.league = league
        if params is None:
            params, saved = load_tuned()
            tuning = {**saved, **(tuning or {})}
        self.params = params
        self.tuning = {**DEFAULT_TUNING, **(tuning or {})}
        self.prev = prev_seasons[-1] if prev_seasons else []
        self.prev_ratios = {s: season_ratios(self.prev, s, self.params) for s in STATS} if self.prev else {s: {} for s in STATS}
        self.promoted = {s: promoted_prior(prev_seasons, s, self.params) for s in STATS}
        self.ref_history = [m for season in prev_seasons[-2:] for m in season if m.get("referee")]
        nomix = Params(league_prior_matches=0)
        season_means = {}
        for season in prev_seasons:
            if season:
                season_means[season[0]["season"]] = {st: league_means(season, None, st, nomix) for st in STATS}
        self.views = Views(prev_seasons, season_means, self.tuning.get("gap_coef"),
                           self.tuning.get("form_k"), self.tuning.get("h2h_k"))

    # -------------------------------------------------------------- step 1
    def base(self, cur, home, away):
        out, info = {}, {}
        for stat in sorted(STATS, key=lambda s: s == "goals"):  # goals last: it can borrow from shots on target
            mh, ma = league_means(cur, self.prev, stat, self.params)
            reg = self.params.prior_regress[stat]
            ph = team_prior(home, self.prev_ratios[stat], self.promoted[stat], reg)
            pa = team_prior(away, self.prev_ratios[stat], self.promoted[stat], reg)
            rh = team_records(cur, home, stat)
            ra = team_records(cur, away, stat)
            att_h, def_h = strength(rh, mh, ma, ph, self.params, stat, "H")
            att_a, def_a = strength(ra, mh, ma, pa, self.params, stat, "A")
            s = self.params.goals_sot_mix
            if stat == "goals" and s > 0:
                # goals are noisy; shots on target measure the same skill with less luck
                t = info["shots_on_target"]
                att_h = (1 - s) * att_h + s * t["home_att"]
                def_h = (1 - s) * def_h + s * t["home_def"]
                att_a = (1 - s) * att_a + s * t["away_att"]
                def_a = (1 - s) * def_a + s * t["away_def"]
            out[stat] = [mh * att_h * def_a, ma * att_a * def_h]
            info[stat] = {"league_home": mh, "league_away": ma,
                          "home_att": att_h, "home_def": def_h, "away_att": att_a, "away_def": def_a,
                          "home_n": len(rh), "away_n": len(ra),
                          "home_recs": rh, "away_recs": ra,
                          "home_prior": "last season" if home in self.prev_ratios[stat] else "promoted-team average",
                          "away_prior": "last season" if away in self.prev_ratios[stat] else "promoted-team average"}
        return out, info

    # -------------------------------------------------------------- step 2
    def adjustments(self, cur, home, away, ctx):
        out = []
        mh, ma = league_means(cur, self.prev, "cards", self.params)
        ref = ctx.get("referee")
        ref_games = [m for m in self.ref_history + [m for m in cur if m.get("referee")]
                     if ref and m.get("referee") == ref]
        out += adj.referee(ref, ref_games, mh + ma, self.tuning["referee_k"])
        out += adj.derby(home, away, self.tuning["derby_cards"])
        out += adj.congestion(ctx.get("home_rest_days"), ctx.get("home_europe_midweek"), "home", ctx.get("home_label", home))
        out += adj.congestion(ctx.get("away_rest_days"), ctx.get("away_europe_midweek"), "away", ctx.get("away_label", away))
        if ctx.get("home_missing") is not None:
            out += adj.absences(home, "home", "away", ctx["home_missing"], ctx.get("home_squad", {}))
        if ctx.get("away_missing") is not None:
            out += adj.absences(away, "away", "home", ctx["away_missing"], ctx.get("away_squad", {}))
        return out

    # -------------------------------------------------------------- full card
    def predict(self, cur, home, away, ctx=None, fast=False):
        """cur: this season's league matches played BEFORE kick-off."""
        ctx = ctx or {}
        base, info = self.base(cur, home, away)
        w = self.params.blend_weight
        blended, views, vmeta, vsum = base, None, None, None
        if w > 0:
            cur_means = {st: (info[st]["league_home"], info[st]["league_away"]) for st in STATS}
            combined, views, vmeta, vsum = self.views.compute(cur, home, away, base, info, cur_means)
            blended = {st: [(1 - w) * base[st][j] + w * combined[st][j] for j in (0, 1)] for st in STATS}
        adjs = self.adjustments(cur, home, away, ctx)
        final, mult = adj.apply(blended, adjs)
        stats = {}
        for stat, (lh, la) in final.items():
            if stat == "goals":
                probs = goal_probabilities(lh, la, self.params.dc_rho)
            else:
                probs = count_probabilities(stat, lh, la, self.params.nb_alpha[stat])
            stats[stat] = {"home": lh, "away": la, "total": lh + la,
                           "base_home": base[stat][0], "base_away": base[stat][1], **probs}
            if views is not None:
                stats[stat]["blend_home"], stats[stat]["blend_away"] = blended[stat]
                stats[stat]["views"] = views[stat]
                stats[stat]["view_meta"] = vmeta[stat]
            if not fast:
                stats[stat]["why"] = self.why(stat, ctx.get("home_label", home), ctx.get("away_label", away), info[stat])
        out = {"home": home, "away": away, "league": self.league, "stats": stats}
        if fast:
            return out
        min_n = min(info["goals"]["home_n"], info["goals"]["away_n"])
        out["adjustments"] = [a.to_dict() for a in adjs]
        out["sample"] = {"home_games": info["goals"]["home_n"], "away_games": info["goals"]["away_n"],
                         "home_prior": info["goals"]["home_prior"], "away_prior": info["goals"]["away_prior"]}
        # What the estimate rests on. (A High/Medium/Low label was removed: in testing it did not
        # predict accuracy, so the card shows these plain facts instead.)
        out["basis"] = {"min_games": min_n, "team_news": bool(ctx.get("injuries_known")),
                        "adjusted_max_pct": round(max(abs(m - 1) for pair in mult.values() for m in pair) * 100, 1)}
        out["blend"] = {"base_weight": 1 - w, "views_weight": w, **(vsum or {})}
        out["analyst_view"] = ctx.get("analyst_view", [])
        return out

    def why(self, stat, home, away, i):
        """3-4 plain-language inputs, most extreme first."""
        lab = STAT_LABEL[stat]

        def avg(recs, venue, idx):
            v = [r[idx] for r in recs if r[0] == venue]
            return (sum(v) / len(v), len(v)) if v else (None, 0)

        items = []
        hf, hn = avg(i["home_recs"], "H", 1)
        ac, an = avg(i["away_recs"], "A", 2)
        af, _ = avg(i["away_recs"], "A", 1)
        hc, _ = avg(i["home_recs"], "H", 2)
        if hf is not None:
            items.append((abs(hf / i["league_home"] - 1),
                          f"{home} average {hf:.1f} {lab} per game at home ({hn} games)"))
            items.append((abs(hc / i["league_away"] - 1),
                          f"{home} concede {hc:.1f} {lab} per game at home"))
        if af is not None:
            items.append((abs(af / i["league_away"] - 1),
                          f"{away} average {af:.1f} {lab} per game away ({an} games)"))
            items.append((abs(ac / i["league_home"] - 1),
                          f"{away} concede {ac:.1f} {lab} per game away"))
        items.sort(reverse=True)
        lines = [t for _, t in items[:3]]
        lines.append(f"League average: {i['league_home']:.1f} for home teams, {i['league_away']:.1f} for away teams")
        if i["home_n"] < 10 or i["away_n"] < 10:
            lines.append(f"Small sample: blended with {i['home_prior'] if i['home_n'] < 10 else i['away_prior']} numbers")
        return lines
