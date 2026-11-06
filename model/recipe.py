"""The estimate recipe used for every match (league and European alike).

  final = 60% base + 40% adjusted

  base      venue-aware ratings (model/ratings.py): home team's home numbers vs away team's away
            numbers, adjusted for opponent strength relative to the league (or competition)
            average, recent games weighted more. League games come from that league only;
            European games use one joint fit over every competition so clubs share a scale.
  adjusted  base x momentum (last 6 games, any competition, vs what the ratings expected; head-to-head
            as a minor part) x missing players x referee (cards) x fixture congestion x derby/stakes.

Because adjustments carry 40% of the weight, a factor F in the adjusted part moves the final number by
0.4 x (F - 1). Measured effects (derbies, stakes, congestion, referees) are converted so that their
effect on the FINAL number equals what was measured; a missing player's factor is 1 - his share of
team goal involvement, which at 40% weight means a replacement covers 60% of his output.
"""
from __future__ import annotations

import math
from collections import defaultdict

from .core import STATS, count_probabilities, goal_probabilities, has_stat

BASE_W, ADJ_W = 0.6, 0.4
FORM_N = 6
H2H_MAX = 6
H2H_SHARE = 0.2          # head-to-head is a minor part of the momentum factor
F_MIN, F_MAX = 0.5, 2.0  # adjusted-part factor caps -> final effect between -20% and +40%
LABEL = {"goals": "goals", "corners": "corners", "cards": "cards", "shots": "shots", "shots_on_target": "shots on target"}


def from_final(effect):
    """Factor inside the 40% part that moves the final number by `effect` (e.g. 0.16 for +16%)."""
    return 1 + effect / ADJ_W


class Adj:
    def __init__(self, kind, stat, side, factor, detail, status):
        self.kind, self.stat, self.side, self.factor, self.detail, self.status = kind, stat, side, factor, detail, status

    def to_dict(self):
        return {"kind": self.kind, "stat": self.stat, "side": self.side, "factor": round(self.factor, 4),
                "effect_pct": round(ADJ_W * (self.factor - 1) * 100, 1), "detail": self.detail, "status": self.status}


class Recipe:
    def __init__(self, params, tuning):
        """params: model.core.Params (dc_rho, nb_alpha); tuning: dict (see backtest/recipe.py)."""
        self.params, self.t = params, tuning

    def attach(self, matches, asof, league_fits, joint_fits, referees=None):
        """matches: assembled matches (model.europe.assemble), sorted by date.
        league_fits: {league: {stat: Ratings}}; joint_fits: {stat: Ratings} (all competitions).
        referees: {match id or (date, home, away): referee name}."""
        self.asof, self.lf, self.jf = asof, league_fits, joint_fits
        self.by_team = defaultdict(list)
        self.ref_games = defaultdict(list)
        refs = referees or {}
        for m in matches:
            if m["date"] >= asof:
                break
            self.by_team[m["home"]].append(m)
            self.by_team[m["away"]].append(m)
            r = refs.get(m.get("id")) or refs.get((m["date"], m["home"], m["away"]))
            if r and m.get("hcards") is not None and m.get("acards") is not None:
                self.ref_games[r].append((m["ctx"], m["hcards"] + m["acards"]))
        return self

    # ------------------------------------------------------------ helpers
    def fit_for(self, ctx, stat):
        lf = self.lf.get(ctx)
        return lf[stat] if lf and stat in lf else self.jf[stat]

    def _k(self, name, stat, default):
        """A tuning strength: one number for every stat, or {stat: number}."""
        v = self.t.get(name, default)
        return v.get(stat, default) if isinstance(v, dict) else v

    def expect(self, m, stat):
        return self.fit_for(m["ctx"], stat).expect(m["home"], m["away"], m["ctx"])

    def momentum(self, team, stat):
        hk, ak = STATS[stat]
        games = [m for m in self.by_team.get(team, ()) if has_stat(m, stat)][-FORM_N:]
        sf = ef = sa = ea = 0.0
        for m in games:
            lh, la = self.expect(m, stat)
            if m["home"] == team:
                sf, ef, sa, ea = sf + m[hk], ef + lh, sa + m[ak], ea + la
            else:
                sf, ef, sa, ea = sf + m[ak], ef + la, sa + m[hk], ea + lh
        k = self._k("form_k", stat, 6.0)
        return (sf + k) / (ef + k), (sa + k) / (ea + k), len(games), (sf, ef, sa, ea)

    def h2h(self, home, away, stat):
        hk, ak = STATS[stat]
        ms = [m for m in self.by_team.get(home, ()) if away in (m["home"], m["away"]) and has_stat(m, stat)][-H2H_MAX:]
        rh = ra = 0.0
        for m in ms:
            lh, la = self.expect(m, stat)
            if m["home"] == home:
                rh, ra = rh + m[hk] / lh, ra + m[ak] / la
            else:
                rh, ra = rh + m[ak] / la, ra + m[hk] / lh
        k = self._k("h2h_k", stat, 4.0)
        n = len(ms)
        return (rh + k) / (n + k), (ra + k) / (n + k), ms

    # ------------------------------------------------------------ the estimate
    def predict(self, home, away, ctx_key, info=None, labels=None, fast=False):
        info, labels = info or {}, labels or {}
        hn, an = labels.get("home", home), labels.get("away", away)
        stats, adjs_all, recipe = {}, [], {}
        for stat in STATS:
            fit = self.fit_for(ctx_key, stat)
            bh, ba = fit.expect(home, away, ctx_key)
            fa_h, fd_h, nh, raw_h = self.momentum(home, stat)
            fa_a, fd_a, na, raw_a = self.momentum(away, stat)
            mh, ma = fa_h * fd_a, fa_a * fd_h
            qh, qa, meet = self.h2h(home, away, stat)
            form_h = (1 - H2H_SHARE) * mh + H2H_SHARE * qh
            form_a = (1 - H2H_SHARE) * ma + H2H_SHARE * qa
            adjs = [Adj("momentum", stat, "home", (1 - H2H_SHARE) * mh + H2H_SHARE,
                        f"{hn} {LABEL[stat]} in last {nh}: {raw_h[0]:.0f} for (expected {raw_h[1]:.1f}); {an} conceded {raw_a[2]:.0f} (expected {raw_a[3]:.1f})" if nh else f"{hn}: no recent games",
                        "measured"),
                    Adj("momentum", stat, "away", (1 - H2H_SHARE) * ma + H2H_SHARE,
                        f"{an} {LABEL[stat]} in last {na}: {raw_a[0]:.0f} for (expected {raw_a[1]:.1f}); {hn} conceded {raw_h[2]:.0f} (expected {raw_h[3]:.1f})" if na else f"{an}: no recent games",
                        "measured")]
            if meet:
                adjs += [Adj("h2h", stat, "home", (1 - H2H_SHARE) + H2H_SHARE * qh, f"{len(meet)} past meetings (minor factor)", "measured"),
                         Adj("h2h", stat, "away", (1 - H2H_SHARE) + H2H_SHARE * qa, f"{len(meet)} past meetings (minor factor)", "measured")]
            fh, fa = form_h, form_a
            # missing players (goals): factor = 1 - share of team goal involvement (60% covered by a replacement)
            if stat == "goals":
                for side, other, key in (("home", "away", "home_missing"), ("away", "home", "away_missing")):
                    for x in info.get(key) or []:
                        share = x.get("share")
                        if share:
                            a = Adj("missing", "goals", side, max(1 - share, F_MIN), f"{x['name']} out ({x.get('reason', 'unavailable')}): {share:.0%} of team goal involvement", "rule")
                            adjs.append(a)
                            if side == "home":
                                fh *= a.factor
                            else:
                                fa *= a.factor
                        if x.get("regular_defender"):
                            a = Adj("missing", "goals", other, from_final(0.03), f"{x['name']} (regular {'goalkeeper' if x.get('position') == 'G' else 'defender'}) out", "rule")
                            adjs.append(a)
                            if other == "home":
                                fh *= a.factor
                            else:
                                fa *= a.factor
                # fixture congestion (measured effect on a team's own goals)
                for side in ("home", "away"):
                    rest, euro = info.get(f"{side}_rest_days"), info.get(f"{side}_europe_midweek")
                    if (rest is not None and rest < 4) or euro:
                        eff = self.t.get("congestion_goals", 0.0)
                        name = hn if side == "home" else an
                        a = Adj("congestion", "goals", side, from_final(eff),
                                f"{name}: {rest} days' rest{', European game midweek' if euro else ''}", "measured" if eff else "info")
                        adjs.append(a)
                        if side == "home":
                            fh *= a.factor
                        else:
                            fa *= a.factor
            if stat == "cards":
                both = 1.0
                ref = info.get("referee")
                if ref:
                    games = self.ref_games.get(ref, [])
                    n = len(games)
                    mu = sum(fit.venue(ctx_key))
                    k = self.t.get("referee_k", 15.0)
                    tot = sum(c for _, c in games)
                    r = (tot + k * mu) / ((n + k) * mu)
                    a = Adj("referee", "cards", "both", from_final(r - 1),
                            f"{ref}: {tot / n:.1f} cards per game in {n} games (average {mu:.1f})" if n else f"{ref}: no past games on record", "measured" if n else "info")
                    adjs.append(a)
                    both *= a.factor
                else:
                    adjs.append(Adj("referee", "cards", "both", 1.0, "Referee not announced yet", "info"))
                if info.get("derby"):
                    a = Adj("derby", "cards", "both", from_final(self.t.get("derby_cards", 0.0)), "Derby / rivalry", "measured")
                    adjs.append(a)
                    both *= a.factor
                if info.get("stakes"):
                    eff = self.t.get("stakes_cards", 0.0)
                    a = Adj("stakes", "cards", "both", from_final(eff), info["stakes"], "measured" if eff else "info")
                    adjs.append(a)
                    both *= a.factor
                fh, fa = fh * both, fa * both
            fh, fa = min(max(fh, F_MIN), F_MAX), min(max(fa, F_MIN), F_MAX)
            lh = BASE_W * bh + ADJ_W * bh * fh
            la = BASE_W * ba + ADJ_W * ba * fa
            if stat == "goals":
                probs = goal_probabilities(lh, la, self.params.dc_rho)
            else:
                alpha = self.t.get("nb_alpha", {}).get(stat, self.params.nb_alpha.get(stat, 0.03))
                probs = count_probabilities(stat, lh, la, alpha)
            stats[stat] = {"home": lh, "away": la, "total": lh + la, "base_home": bh, "base_away": ba,
                           "adj_home": bh * fh, "adj_away": ba * fa, **probs}
            recipe[stat] = {"factor": [fh, fa], "form_games": [nh, na], "h2h_meetings": len(meet)}
            if not fast:
                stats[stat]["why"] = self.why(stat, fit, home, away, ctx_key, hn, an)
            adjs_all += adjs
        out = {"home": home, "away": away, "stats": stats}
        if fast:
            return out
        g = self.fit_for(ctx_key, "goals")
        gh, ga = g.games.get(home, [0, 0]), g.games.get(away, [0, 0])
        meet = self.h2h(home, away, "goals")[2]
        out["recipe"] = {"base_weight": BASE_W, "adj_weight": ADJ_W, "by_stat": recipe}
        out["adjustments"] = [a.to_dict() for a in adjs_all if not (a.kind in ("momentum", "h2h") and abs(a.factor - 1) < 0.005)]
        out["sample"] = {"home_games": gh[0], "away_games": ga[1], "home_all": sum(gh), "away_all": sum(ga)}
        out["basis"] = {"min_games": min(gh[0], ga[1]), "team_news": bool(info.get("injuries_known"))}
        out["h2h"] = [{"date": m["date"], "home": m["home"], "away": m["away"], "score": [m["hg"], m["ag"]]} for m in reversed(meet)]
        out["analyst_view"] = info.get("analyst_view") or {}
        return out

    def why(self, stat, fit, home, away, ctx, hn, an):
        lab = LABEL[stat]
        vh, va = fit.venue(ctx)
        ha, hd = fit.parts(home, ctx, "home")
        aa, ad = fit.parts(away, ctx, "away")
        gh, ga = fit.games.get(home, [0, 0]), fit.games.get(away, [0, 0])
        items = [(abs(math.log(ha)), f"{hn} at home: {ha:.2f}x the average home side's {lab} (opponent-adjusted, {gh[0]} home games)"),
                 (abs(math.log(hd)), f"{hn} at home concede {hd:.2f}x the usual {lab}"),
                 (abs(math.log(aa)), f"{an} away: {aa:.2f}x the average away side's {lab} ({ga[1]} away games)"),
                 (abs(math.log(ad)), f"{an} away concede {ad:.2f}x the usual {lab}")]
        items.sort(key=lambda x: -x[0])
        return [t for _, t in items[:3]] + [f"Average: {vh:.1f} for home teams, {va:.1f} for away teams"]
