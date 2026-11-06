"""Venue-aware team ratings: the 60% base of every estimate.

For one stat and one set of matches (a league, or all competitions for European games):

    log E[home value] = mu[ctx] + H[ctx] + att[i] + att_home[i] - (def[j] - def_away[j])
    log E[away value] = mu[ctx]          + att[j] - att_home[j] - (def[i] + def_away[i])

  * mu, H        league (or competition) average level and home advantage
  * att, def     a team's strength relative to that average, adjusted for the opponents it faced
  * att_home     how much better (worse) the team is at home than away; def_away likewise
                 -> "home team's home numbers vs away team's away numbers"
  * games are weighted by age (half-life): recent games count more
  * ratings are pulled toward the team's group level (small samples move little);
    group = league, or "new" for teams that weren't in it at the start of the window (promoted)
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
from scipy.optimize import minimize

from .core import STATS, has_stat


def _ord(s):
    return date.fromisoformat(s[:10]).toordinal()


class Ratings:
    def __init__(self, half_life=300.0, tau=0.3, sigma=0.6, home_tau=0.15, venue_tau=0.1):
        self.half_life, self.tau, self.sigma, self.home_tau, self.venue_tau = half_life, tau, sigma, home_tau, venue_tau

    def fit(self, matches, groups, stat, asof):
        hk, ak = STATS[stat]
        ms = [m for m in matches if m["date"] < asof and has_stat(m, stat)]
        if not ms:
            raise ValueError(f"no {stat} data before {asof}")
        teams = sorted({m["home"] for m in ms} | {m["away"] for m in ms})
        ti = {t: i for i, t in enumerate(teams)}
        gnames = sorted({groups.get(t, "other") for t in teams})
        gi = {g: i for i, g in enumerate(gnames)}
        cnames = sorted({m["ctx"] for m in ms})
        ci = {c: i for i, c in enumerate(cnames)}
        T, G, C = len(teams), len(gnames), len(cnames)
        Hh = np.array([ti[m["home"]] for m in ms])
        Aa = np.array([ti[m["away"]] for m in ms])
        X = np.array([ci[m["ctx"]] for m in ms])
        yh = np.array([m[hk] for m in ms], float)
        ya = np.array([m[ak] for m in ms], float)
        a0 = _ord(asof)
        w = 0.5 ** (np.array([a0 - _ord(m["date"]) for m in ms], float) / self.half_life)
        tg = np.array([gi[groups.get(t, "other")] for t in teams])
        mu0 = np.zeros(C)
        for c in range(C):
            s = X == c
            mu0[c] = math.log(max((yh[s].sum() + ya[s].sum()) / (2 * s.sum()), 0.05))
        x0 = np.concatenate([mu0, np.full(C, 0.1), np.zeros(4 * T + 2 * G)])
        it2, s2, h2, v2 = 1 / self.tau ** 2, 1 / self.sigma ** 2, 1 / self.home_tau ** 2, 1 / self.venue_tau ** 2
        o = [0, C, 2 * C, 2 * C + T, 2 * C + 2 * T, 2 * C + 3 * T, 2 * C + 4 * T, 2 * C + 4 * T + G, 2 * C + 4 * T + 2 * G]

        def unpack(x):
            return [x[o[k]:o[k + 1]] for k in range(8)]

        def f(x):
            mu, hm, att, dfn, uh, vd, ga, gd = unpack(x)
            lh = mu[X] + hm[X] + att[Hh] + uh[Hh] - dfn[Aa] + vd[Aa]
            la = mu[X] + att[Aa] - uh[Aa] - dfn[Hh] - vd[Hh]
            eh, ea = np.exp(lh), np.exp(la)
            nll = np.sum(w * (eh - yh * lh)) + np.sum(w * (ea - ya * la))
            ra, rd = att - ga[tg], dfn - gd[tg]
            hbar = hm.mean()
            pen = (0.5 * it2 * (ra @ ra + rd @ rd) + 0.5 * s2 * (ga @ ga + gd @ gd)
                   + 0.5 * h2 * np.sum((hm - hbar) ** 2) + 0.5 * v2 * (uh @ uh + vd @ vd))
            rh, rA = w * (eh - yh), w * (ea - ya)
            bH_h, bA_a = np.bincount(Hh, rh, T), np.bincount(Aa, rA, T)
            bA_h, bH_a = np.bincount(Aa, rh, T), np.bincount(Hh, rA, T)
            g = [np.bincount(X, rh + rA, C), np.bincount(X, rh, C) + h2 * (hm - hbar),
                 bH_h + bA_a + it2 * ra, -bA_h - bH_a + it2 * rd,
                 bH_h - bA_a + v2 * uh, bA_h - bH_a + v2 * vd,
                 -it2 * np.bincount(tg, ra, G) + s2 * ga, -it2 * np.bincount(tg, rd, G) + s2 * gd]
            return nll + pen, np.concatenate(g)

        res = minimize(f, x0, jac=True, method="L-BFGS-B", options={"maxiter": 800})
        mu, hm, att, dfn, uh, vd, ga, gd = unpack(res.x)
        self.stat, self.asof, self.groups = stat, asof, groups
        self.ctx = {c: (float(mu[i]), float(hm[i])) for c, i in ci.items()}
        self.att = {t: float(att[i]) for t, i in ti.items()}
        self.dfn = {t: float(dfn[i]) for t, i in ti.items()}
        self.uh = {t: float(uh[i]) for t, i in ti.items()}
        self.vd = {t: float(vd[i]) for t, i in ti.items()}
        self.gatt = {g: float(ga[i]) for g, i in gi.items()}
        self.gdfn = {g: float(gd[i]) for g, i in gi.items()}
        self.games = {}  # [home, away] games behind each rating
        for m in ms:
            self.games.setdefault(m["home"], [0, 0])[0] += 1
            self.games.setdefault(m["away"], [0, 0])[1] += 1
        # observed (time-weighted) averages per competition, and the average team's ratings there
        self.avg, self.mean = {}, {}
        for c, i in ci.items():
            sel = X == i
            wsum = w[sel].sum()
            self.avg[c] = (float((w[sel] * yh[sel]).sum() / wsum), float((w[sel] * ya[sel]).sum() / wsum))
            tix = np.unique(np.concatenate([Hh[sel], Aa[sel]]))
            self.mean[c] = (float(att[tix].mean()), float(dfn[tix].mean()), float(uh[tix].mean()), float(vd[tix].mean()))
        return self

    def team(self, t):
        g = self.groups.get(t, "other")
        return (self.att.get(t, self.gatt.get(g, 0.0)), self.dfn.get(t, self.gdfn.get(g, 0.0)),
                self.uh.get(t, 0.0), self.vd.get(t, 0.0))

    def expect(self, home, away, ctx):
        mu, hm = self.ctx.get(ctx) or next(iter(self.ctx.values()))
        ah, dh, uh_h, vd_h = self.team(home)
        aa, da, uh_a, vd_a = self.team(away)
        return (math.exp(mu + hm + ah + uh_h - da + vd_a), math.exp(mu + aa - uh_a - dh - vd_h))

    def venue(self, ctx):
        """Observed average per game for home and away teams in this competition."""
        return self.avg.get(ctx) or next(iter(self.avg.values()))

    def parts(self, team, ctx, side):
        """Multipliers vs the competition's average team at this venue: (attack, conceding)."""
        a, d, u, v = self.team(team)
        ma, md, mu_, mv = self.mean.get(ctx) or next(iter(self.mean.values()))
        if side == "home":
            return math.exp((a + u) - (ma + mu_)), math.exp(-(d + v) + (md + mv))
        return math.exp((a - u) - (ma - mu_)), math.exp(-(d - v) + (md - mv))


def league_groups(matches, window_start):
    """Group per team: the league, or '<league>:new' for teams with no games before the window's latest season."""
    first = {}
    for m in matches:
        for t in (m["home"], m["away"]):
            first.setdefault(t, m["date"])
    seasons = sorted({m.get("season") for m in matches if m.get("season")})
    latest_start = min((m["date"] for m in matches if m.get("season") == seasons[-1]), default=window_start) if seasons else window_start
    out = {}
    for m in matches:
        for t in (m["home"], m["away"]):
            out[t] = f"{m['ctx']}:new" if first[t] >= latest_start and seasons and len(seasons) > 1 else m["ctx"]
    return out
