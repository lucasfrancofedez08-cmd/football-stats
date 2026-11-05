"""Walk-forward backtest: every match is predicted using only data from before its date.

Tune on 2023-24 + 2024-25, test once on 2025-26 (both leagues), compare with a
league-average baseline that knows nothing about the teams.

  python -m backtest.run            # tune + test, writes backtest/results.json
"""
from __future__ import annotations

import copy
import itertools
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.core import (STATS, Params, count_probabilities, goal_probabilities,  # noqa: E402
                        has_stat, league_means)
from model.data import load_file  # noqa: E402
from model.predict import Predictor  # noqa: E402
from model import adjustments as adj  # noqa: E402
from model.views import season_ppg, team_ppg  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "history")
SEASONS = ["2122", "2223", "2324", "2425", "2526"]
from pipeline.sources import DOMESTIC as LEAGUES  # noqa: E402
TUNE = ["2324", "2425"]
TEST = ["2526"]
EPS = 1e-12


def load_all():
    return {lg: [load_file(os.path.join(RAW, f"{lg}_{s}.csv"), lg, s) for s in SEASONS] for lg in LEAGUES}


DATA = None


def data():
    global DATA
    if DATA is None:
        DATA = load_all()
    return DATA


def ll(p, y):
    p = min(max(p, EPS), 1 - EPS)
    return -(math.log(p) if y else math.log(1 - p))


def walk(league, season, params, tuning=None, stats=None, baseline=False):
    """Yields (match, {stat: (lh, la)}) for every match of the season."""
    seasons = data()[league]
    idx = SEASONS.index(season)
    pred = Predictor(league, seasons[:idx], params, tuning)
    matches = seasons[idx]
    stats = stats or list(STATS)
    by_date = {}
    for m in matches:
        by_date.setdefault(m["date"], []).append(m)
    cur = []
    for d in sorted(by_date):
        for m in by_date[d]:
            if baseline:
                lam = {s: league_means(cur, pred.prev, s, params) for s in stats}
            elif tuning is None:
                full = len(stats) > 1 or (stats[0] == "goals" and params.goals_sot_mix > 0)
                base, _ = pred.base(cur, m["home"], m["away"]) if full else _one(pred, cur, m, stats[0])
                lam = {s: tuple(base[s]) for s in stats}
            else:
                ctx = {"referee": m.get("referee")}
                p = pred.predict(cur, m["home"], m["away"], ctx, fast=True)
                lam = {s: (p["stats"][s]["home"], p["stats"][s]["away"]) for s in stats}
            yield m, lam
        cur.extend(by_date[d])


def _one(pred, cur, m, stat):
    from model.core import strength, team_prior, team_records
    mh, ma = league_means(cur, pred.prev, stat, pred.params)
    reg = pred.params.prior_regress[stat]
    ph = team_prior(m["home"], pred.prev_ratios[stat], pred.promoted[stat], reg)
    pa = team_prior(m["away"], pred.prev_ratios[stat], pred.promoted[stat], reg)
    ah, dh = strength(team_records(cur, m["home"], stat), mh, ma, ph, pred.params, stat, "H")
    aa, da = strength(team_records(cur, m["away"], stat), mh, ma, pa, pred.params, stat, "A")
    return {stat: [mh * ah * da, ma * aa * dh]}, None


def score_stat(stat, pairs, params):
    """Mean log loss used for tuning, plus detailed metrics."""
    out = {"n": 0, "ll": 0.0, "brier": 0.0, "mae": 0.0, "lines": {}}
    for m, lam in pairs:
        if not has_stat(m, stat):
            continue
        hk, ak = STATS[stat]
        lh, la = lam[stat]
        tot = m[hk] + m[ak]
        out["n"] += 1
        out["mae"] += abs(lh + la - tot)
        if stat == "goals":
            g = goal_probabilities(lh, la, params.dc_rho)
            res = "H" if m[hk] > m[ak] else "D" if m[hk] == m[ak] else "A"
            probs = {"H": g["home_win"], "D": g["draw"], "A": g["away_win"]}
            out["ll"] += -math.log(max(probs[res], EPS))
            out["brier"] += sum((probs[k] - (k == res)) ** 2 for k in probs)
            overs = g["over"]
        else:
            overs = count_probabilities(stat, lh, la, params.nb_alpha[stat])["over"]
        for line, p in overs.items():
            y = tot > float(line)
            d = out["lines"].setdefault(line, {"n": 0, "ll": 0.0, "brier": 0.0, "hits": 0, "rate": 0})
            d["n"] += 1
            d["ll"] += ll(p, y)
            d["brier"] += (p - y) ** 2
            d["hits"] += int((p >= 0.5) == y)
            d["rate"] += int(y)
    n = max(out["n"], 1)
    out["mae"] /= n
    out["ll"] /= n
    out["brier"] /= n
    for d in out["lines"].values():
        for k in ("ll", "brier"):
            d[k] /= d["n"]
        d["hit_rate"] = d.pop("hits") / d["n"]
        d["actual_over_rate"] = d.pop("rate") / d["n"]
    # tuning objective: 1X2 + O/U2.5 for goals; mean over lines for counts
    if stat == "goals":
        out["objective"] = out["ll"] + out["lines"]["2.5"]["ll"]
    else:
        out["objective"] = sum(d["ll"] for d in out["lines"].values()) / len(out["lines"])
    return out


def evaluate(stat, params, seasons, tuning=None, baseline=False):
    pairs = [x for lg in LEAGUES for s in seasons for x in walk(lg, s, params, tuning, [stat] if tuning is None else None, baseline)]
    return score_stat(stat, pairs, params)


def fit_alpha(stat, params, seasons):
    """Method-of-moments over-dispersion of match totals around model means."""
    num = den = 0.0
    for lg in LEAGUES:
        for s in seasons:
            for m, lam in walk(lg, s, params, None, [stat]):
                if not has_stat(m, stat):
                    continue
                hk, ak = STATS[stat]
                mu = sum(lam[stat])
                y = m[hk] + m[ak]
                num += (y - mu) ** 2 - mu
                den += mu ** 2
    return max(num / den, 0.0)


def _grid_job(args):
    stat, k, reg, vb, rw = args
    p = Params()
    p.shrink_k = {**p.shrink_k, stat: k}
    p.prior_regress = {**p.prior_regress, stat: reg}
    p.venue_blend = vb
    p.recent_weight = rw
    return (k, reg, vb, rw), evaluate(stat, p, TUNE)["objective"]


def tune():
    best = {}
    grid = list(itertools.product([10.0, 14.0, 20.0, 30.0], [0.5, 0.75, 0.9], [0.0, 0.3], [1.0, 2.0]))
    with ProcessPoolExecutor() as ex:
        for stat in STATS:
            res = list(ex.map(_grid_job, [(stat, *g) for g in grid]))
            res.sort(key=lambda r: r[1])
            best[stat] = res[0]
            print(f"  {stat:16s} best k={res[0][0][0]} regress={res[0][0][1]} venue_blend={res[0][0][2]} "
                  f"recent_weight={res[0][0][3]}  obj={res[0][1]:.4f}  (worst {res[-1][1]:.4f})", flush=True)
    return best


def build_params(best):
    p = Params()
    p.shrink_k = {s: best[s][0][0] for s in STATS}
    p.prior_regress = {s: best[s][0][1] for s in STATS}
    # venue blend / recency are global: take the majority choice
    vb = [best[s][0][2] for s in STATS]
    rw = [best[s][0][3] for s in STATS]
    p.venue_blend = max(set(vb), key=vb.count)
    p.recent_weight = max(set(rw), key=rw.count)
    return p


def fit_rho(params, seasons):
    best = None
    for rho in [-0.15, -0.12, -0.09, -0.06, -0.03, 0.0]:
        params.dc_rho = rho
        o = evaluate("goals", params, seasons)["ll"]
        if best is None or o < best[1]:
            best = (rho, o)
    return best[0]


def measure_derby(params, seasons):
    """Actual / expected cards in derbies (model without adjustments)."""
    act = exp = 0.0
    n = 0
    for lg in LEAGUES:
        for s in seasons:
            for m, lam in walk(lg, s, params, None, ["cards"]):
                if adj.is_derby(m["home"], m["away"]) and has_stat(m, "cards"):
                    act += m["hcards"] + m["acards"]
                    exp += sum(lam["cards"])
                    n += 1
    return (act / exp if exp else 1.0), n


def fit_gap(train):
    """Team-gap effect: log(stat / league venue average) against the pre-match points-per-game gap."""
    num = {s: [0.0, 0.0] for s in STATS}
    den = {s: [0.0, 0.0] for s in STATS}
    nomix = Params(league_prior_matches=0)
    for lg in LEAGUES:
        seasons = data()[lg]
        for sname in train:
            i = SEASONS.index(sname)
            prev = season_ppg(seasons[i - 1])
            means = {s: league_means(seasons[i], None, s, nomix) for s in STATS}
            cur = []
            for m in seasons[i]:
                g = team_ppg(cur, m["home"], prev)[0] - team_ppg(cur, m["away"], prev)[0]
                for s, (hk, ak) in STATS.items():
                    if has_stat(m, s):
                        for j, (x, mu) in enumerate(((m[hk], means[s][0]), (m[ak], means[s][1]))):
                            num[s][j] += g * math.log((x + 0.5) / (mu + 0.5))
                            den[s][j] += g * g
                cur.append(m)
    return {s: [round(num[s][j] / den[s][j], 4) for j in (0, 1)] for s in STATS}


def tune_views(params, tuning):
    best = None
    for fk, hk in itertools.product([2.0, 5.0, 10.0], [3.0, 6.0, 12.0]):
        t = {**tuning, "form_k": fk, "h2h_k": hk}
        pairs = [x for lg in LEAGUES for s in TUNE for x in walk(lg, s, params, t)]
        obj = sum(score_stat(st, pairs, params)["objective"] for st in STATS)
        print(f"  views form_k={fk} h2h_k={hk}: {obj:.4f}", flush=True)
        if best is None or obj < best[0]:
            best = (obj, fk, hk)
    return best[1], best[2]


def adjustment_tests(params, seasons):
    """Effect of each adjustment on the tuning seasons (lower log loss = better)."""
    out = {}
    base_tuning = {"momentum_coef": 0.0, "derby_cards": 1.0, "referee_k": 1e9}
    def run(stat, tuning):
        pairs = [x for lg in LEAGUES for s in seasons for x in walk(lg, s, params, tuning)]
        return score_stat(stat, pairs, params)["objective"]
    # referee: Premier League only (La Liga files have no referee)
    def run_pl(tuning):
        pairs = [x for s in seasons for x in walk("premier-league", s, params, tuning)]
        return score_stat("cards", pairs, params)["objective"]
    out["pl_cards_no_referee"] = run_pl(base_tuning)
    for k in [5.0, 10.0, 20.0, 40.0]:
        out[f"pl_cards_referee_k{int(k)}"] = run_pl({**base_tuning, "referee_k": k})
    return out


def calibration(params, tuning, seasons):
    bins = [{"lo": i / 10, "hi": (i + 1) / 10, "n": 0, "p_sum": 0.0, "hits": 0} for i in range(10)]
    for lg in LEAGUES:
        for s in seasons:
            for m, lam in walk(lg, s, params, tuning):
                for stat in STATS:
                    if not has_stat(m, stat):
                        continue
                    hk, ak = STATS[stat]
                    lh, la = lam[stat]
                    tot = m[hk] + m[ak]
                    if stat == "goals":
                        g = goal_probabilities(lh, la, params.dc_rho)
                        events = [(g["home_win"], m[hk] > m[ak]), (g["draw"], m[hk] == m[ak]),
                                  (g["away_win"], m[hk] < m[ak]), (g["btts"], m[hk] > 0 and m[ak] > 0)]
                        events += [(p, tot > float(l)) for l, p in g["over"].items()]
                    else:
                        o = count_probabilities(stat, lh, la, params.nb_alpha[stat])["over"]
                        events = [(p, tot > float(l)) for l, p in o.items()]
                    for p, y in events:
                        b = bins[min(int(p * 10), 9)]
                        b["n"] += 1
                        b["p_sum"] += p
                        b["hits"] += int(y)
    for b in bins:
        b["avg_predicted"] = b.pop("p_sum") / b["n"] if b["n"] else None
        b["actual"] = b.pop("hits") / b["n"] if b["n"] else None
    return bins


def per_league(params, tuning, pure):
    """Test-season results league by league, against league averages and statistics alone."""
    out = {}
    for lg in LEAGUES:
        r = {"matches": 0, "stats": {}}
        for stat in STATS:
            pairs = list(walk(lg, TEST[0], params, tuning))
            m = score_stat(stat, pairs, params)
            b = score_stat(stat, list(walk(lg, TEST[0], params, baseline=True, stats=[stat])), params)
            pu = score_stat(stat, list(walk(lg, TEST[0], pure, tuning)), pure)
            r["matches"] = max(r["matches"], m["n"])
            r["stats"][stat] = {"objective": m["objective"], "baseline_objective": b["objective"],
                                "pure_objective": pu["objective"], "mae": m["mae"], "baseline_mae": b["mae"]}
            if stat == "goals":
                r["brier_1x2"], r["baseline_brier_1x2"] = m["brier"], b["brier"]
                r["ll_1x2"], r["baseline_ll_1x2"] = m["ll"], b["ll"]
        out[lg] = r
        wins = sum(v["objective"] < v["baseline_objective"] for v in r["stats"].values())
        print(f"  {lg:15s} n={r['matches']:3d} 1X2 brier {r['brier_1x2']:.4f} vs {r['baseline_brier_1x2']:.4f}"
              f" ({(1 - r['brier_1x2'] / r['baseline_brier_1x2']) * 100:+.1f}%)  beats baseline on {wins}/5 stats  "
              + " ".join(f"{s[:4]} {(1 - v['objective'] / v['baseline_objective']) * 100:+.1f}%" for s, v in r["stats"].items()),
              flush=True)
    return out


def main():
    print("Tuning base model on", TUNE, flush=True)
    best = tune()
    params = build_params(best)
    mix_scores = {}
    for mix in [0.0, 0.25, 0.5, 0.75]:
        params.goals_sot_mix = mix
        mix_scores[mix] = evaluate("goals", params, TUNE)["objective"]
        print(f"  goals_sot_mix {mix}: {mix_scores[mix]:.4f}", flush=True)
    params.goals_sot_mix = min(mix_scores, key=mix_scores.get)
    print("Fitting over-dispersion and Dixon-Coles rho", flush=True)
    params.nb_alpha = {s: (0.0 if s == "goals" else round(fit_alpha(s, params, TUNE), 4)) for s in STATS}
    params.dc_rho = fit_rho(params, TUNE)
    print("  alpha", params.nb_alpha, "rho", params.dc_rho, flush=True)

    print("Testing adjustments on", TUNE, flush=True)
    tests = adjustment_tests(params, TUNE)
    for k, v in tests.items():
        print(f"  {k:28s} {v:.4f}", flush=True)
    derby, derby_n = measure_derby(params, ["2122", "2223"] + TUNE)
    momentum_coef = 0.0  # momentum now enters through the form view of the 40% blend
    refk = min([5.0, 10.0, 20.0, 40.0], key=lambda k: tests[f"pl_cards_referee_k{int(k)}"])
    referee_k = refk if tests[f"pl_cards_referee_k{int(refk)}"] < tests["pl_cards_no_referee"] - 0.001 else 1e9
    tuning = {"momentum_coef": momentum_coef, "derby_cards": round(derby, 3), "referee_k": referee_k}
    print("  chosen tuning", tuning, f"(derby sample {derby_n})", flush=True)

    # 60/40 split chosen by the user: 60% statistical base, 40% form / team gap / head-to-head
    print("Fitting the 40% views (team gap measured on 2022-25)", flush=True)
    tuning["gap_coef"] = fit_gap(["2223", "2324", "2425"])
    params.blend_weight = 0.4
    tuning["form_k"], tuning["h2h_k"] = tune_views(params, tuning)
    print("  views", {k: tuning[k] for k in ("gap_coef", "form_k", "h2h_k")}, flush=True)

    print("Final test on", TEST, flush=True)
    results = {"params": params.__dict__, "tuning": tuning, "adjustment_tests": tests,
               "derby_sample": derby_n, "test": {}, "baseline": {}, "pure_stats": {}}
    pure = copy.deepcopy(params)
    pure.blend_weight = 0.0
    for stat in STATS:
        pairs = [x for lg in LEAGUES for s in TEST for x in walk(lg, s, params, tuning)]
        model = score_stat(stat, pairs, params)
        base_pairs = [x for lg in LEAGUES for s in TEST for x in walk(lg, s, params, baseline=True, stats=[stat])]
        base = score_stat(stat, base_pairs, params)
        results["test"][stat] = model
        results["baseline"][stat] = base
        pure_pairs = [x for lg in LEAGUES for s in TEST for x in walk(lg, s, pure, tuning)]
        results["pure_stats"][stat] = score_stat(stat, pure_pairs, pure)
        print(f"  {stat:16s} model obj {model['objective']:.4f} vs baseline {base['objective']:.4f} | "
              f"MAE {model['mae']:.2f} vs {base['mae']:.2f}", flush=True)
        for line, d in model["lines"].items():
            b = base["lines"][line]
            print(f"      over {line:5s} brier {d['brier']:.4f} vs {b['brier']:.4f}  hit {d['hit_rate']:.1%} vs {b['hit_rate']:.1%}"
                  f"  (actual over rate {d['actual_over_rate']:.1%})", flush=True)
        if stat == "goals":
            print(f"      1X2 brier {model['brier']:.4f} vs {base['brier']:.4f}  logloss {model['ll']:.4f} vs {base['ll']:.4f}", flush=True)
    print("Per league (2025-26):", flush=True)
    results["by_league"] = per_league(params, tuning, pure)
    results["matches"] = sum(v["matches"] for v in results["by_league"].values())
    results["calibration"] = calibration(params, tuning, TEST)
    print("  calibration (predicted -> actual):", flush=True)
    for b in results["calibration"]:
        if b["n"]:
            print(f"    {b['lo']:.0%}-{b['hi']:.0%}: n={b['n']:5d} predicted {b['avg_predicted']:.1%} actual {b['actual']:.1%}", flush=True)
    with open(os.path.join(ROOT, "backtest", "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=float)
    with open(os.path.join(ROOT, "model", "tuned.json"), "w") as f:
        json.dump({"params": params.__dict__, "tuning": tuning}, f, indent=1)


if __name__ == "__main__":
    main()
