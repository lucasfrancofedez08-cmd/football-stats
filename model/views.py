"""The 40% "form & matchup" side of the prediction (the user's chosen split).

Three views, each giving expected numbers for home and away. Every view is pulled
toward the statistical base when its own sample is small, so a view with little
evidence behind it falls back to the base instead of adding noise.

  form      last 5 league games only (momentum)
  gap       quality gap: points-per-game difference, mapped to each stat with
            coefficients measured on past seasons (backtest/run.py)
  h2h       past meetings between the two teams (up to 6, last 5 seasons)
"""
from __future__ import annotations

import math

from .core import STATS, has_stat

VIEW_WEIGHTS = {"form": 0.40, "gap": 0.35, "h2h": 0.25}   # shares of the 40%
FORM_N = 5
FORM_K = 2.0      # pseudo-games of base strength mixed into the last-5 form
H2H_MAX = 6
H2H_K = 3.0       # pseudo-meetings of base mixed into head-to-head
PPG_K = 5.0       # pseudo-games of last season's points per game
PROMOTED_PPG = 1.05

# log effect of a 1-point ppg gap on (home stat, away stat), measured in backtest; defaults until then
DEFAULT_GAP = {"goals": (0.22, -0.24), "corners": (0.12, -0.13), "cards": (-0.06, 0.07),
               "shots": (0.14, -0.15), "shots_on_target": (0.19, -0.2)}


def _points(m, team):
    gf, ga = (m["hg"], m["ag"]) if m["home"] == team else (m["ag"], m["hg"])
    return 3 if gf > ga else 1 if gf == ga else 0


def team_ppg(cur, team, prev_ppg):
    games = [m for m in cur if team in (m["home"], m["away"]) and m.get("hg") is not None]
    prior = prev_ppg.get(team, PROMOTED_PPG)
    pts = sum(_points(m, team) for m in games)
    return (pts + PPG_K * prior) / (len(games) + PPG_K), len(games)


def season_ppg(season):
    acc = {}
    for m in season:
        for t in (m["home"], m["away"]):
            a = acc.setdefault(t, [0, 0])
            a[0] += _points(m, t)
            a[1] += 1
    return {t: p / n for t, (p, n) in acc.items() if n}


def form_view(cur, team, venue, stat, mh, ma, base_att, base_def, k=FORM_K):
    hk, ak = STATS[stat]
    games = sorted([m for m in cur if team in (m["home"], m["away"]) and has_stat(m, stat)],
                   key=lambda m: m["date"])[-FORM_N:]
    sa = sd = 0.0
    for m in games:
        if m["home"] == team:
            sa += m[hk] / mh
            sd += m[ak] / ma
        else:
            sa += m[ak] / ma
            sd += m[hk] / mh
    n = len(games)
    att = (sa + k * base_att) / (n + k)
    dfn = (sd + k * base_def) / (n + k)
    return att, dfn, n


def h2h_meetings(history, home, away):
    ms = [m for m in history if {m["home"], m["away"]} == {home, away} and m.get("hg") is not None]
    ms.sort(key=lambda m: m["date"])
    return ms[-H2H_MAX:]


class Views:
    def __init__(self, prev_seasons, season_means, gap_coef=None, form_k=None, h2h_k=None):
        self.form_k = FORM_K if form_k is None else form_k
        self.h2h_k = H2H_K if h2h_k is None else h2h_k
        self.history = [m for s in prev_seasons for m in s]
        self.season_means = season_means          # {season: {stat: (mh, ma)}}
        self.prev_ppg = season_ppg(prev_seasons[-1]) if prev_seasons else {}
        self.gap = {**DEFAULT_GAP, **{k: tuple(v) for k, v in (gap_coef or {}).items()}}

    def compute(self, cur, home, away, base, info, cur_means):
        """base: {stat: [h, a]}; info: per-stat strengths from the statistical base."""
        ppg_h, nh = team_ppg(cur, home, self.prev_ppg)
        ppg_a, na = team_ppg(cur, away, self.prev_ppg)
        gap = ppg_h - ppg_a
        meetings = h2h_meetings(self.history + list(cur), home, away)
        out, meta = {}, {}
        for stat in STATS:
            mh, ma = info[stat]["league_home"], info[stat]["league_away"]
            i = info[stat]
            # form
            ah, dh, fn_h = form_view(cur, home, "H", stat, mh, ma, i["home_att"], i["home_def"], self.form_k)
            aa, da, fn_a = form_view(cur, away, "A", stat, mh, ma, i["away_att"], i["away_def"], self.form_k)
            form = [mh * ah * da, ma * aa * dh]
            # team gap
            bh, ba = self.gap[stat]
            gapv = [mh * math.exp(bh * gap), ma * math.exp(ba * gap)]
            # head to head: each meeting as ratios to that season's venue averages
            hk, ak = STATS[stat]
            rs = []
            for m in meetings:
                if not has_stat(m, stat):
                    continue
                smh, sma = self.season_means.get(m.get("season"), {}).get(stat) or cur_means[stat]
                if m["home"] == home:
                    rs.append((m[hk] / smh, m[ak] / sma))
                else:  # reverse fixture: the upcoming home side played away
                    rs.append((m[ak] / sma, m[hk] / smh))
            bh_ratio, ba_ratio = base[stat][0] / mh, base[stat][1] / ma
            n = len(rs)
            k = self.h2h_k
            h2h = [mh * (sum(r[0] for r in rs) + k * bh_ratio) / (n + k),
                   ma * (sum(r[1] for r in rs) + k * ba_ratio) / (n + k)]
            out[stat] = {"form": form, "gap": gapv, "h2h": h2h}
            meta[stat] = {"form_games": [fn_h, fn_a], "h2h_meetings": n}
        w = VIEW_WEIGHTS
        combined = {s: [sum(w[k] * v[k][j] for k in w) for j in (0, 1)] for s, v in out.items()}
        summary = {
            "ppg": [ppg_h, ppg_a], "ppg_games": [nh, na], "gap": gap,
            "h2h": [{"date": m["date"], "home": m["home"], "away": m["away"], "score": [m["hg"], m["ag"]]}
                    for m in reversed(meetings)],
            "weights": w,
        }
        return combined, out, meta, summary
