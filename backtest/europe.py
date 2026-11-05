"""Backtest for European competition estimates.

Walk-forward: every European match is estimated from games played before its date only.
Tune on 2024-25, test once on 2025-26, compare with the plain European average (home/away means of
the previous year's European games), per competition.

  python -m backtest.europe          writes backtest/results_europe.json and model/tuned_europe.json
"""
from __future__ import annotations

import copy
import itertools
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.run import score_stat  # noqa: E402
from model.core import STATS, has_stat  # noqa: E402
from model.data import load_file  # noqa: E402
from model.europe import EUROPE_CTX, EuropePredictor, assemble, fit_gap  # noqa: E402
from model.predict import load_tuned  # noqa: E402
from pipeline.sources import DOMESTIC  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = os.path.join(ROOT, "data", "history")
FD_SEASONS = ["2223", "2324", "2425", "2526"]
EU_SEASONS = ["2324", "2425", "2526"]
TUNE, TEST = "2425", "2526"
COMPS = ["champions-league", "europa-league", "conference-league"]

DATA = None


def data():
    global DATA
    if DATA is None:
        fd = {lg: [m for s in FD_SEASONS for m in load_file(os.path.join(H, f"{lg}_{s}.csv"), lg, s)] for lg in DOMESTIC}
        rows, clubs = [], {}
        for s in EU_SEASONS:
            rows += json.load(open(os.path.join(H, f"europe_{s}.json")))
            for tid, games in json.load(open(os.path.join(H, f"europe_clubs_{s}.json"))).items():
                clubs.setdefault(tid, []).extend(games)
        for r in rows:
            r["season"] = next(s for s in EU_SEASONS if f"20{s[:2]}-07-01" <= r["date"][:10] < f"20{s[2:]}-07-01")
        matches, groups, names = assemble(fd, rows, clubs)
        DATA = (matches, groups, names, rows)
    return DATA


def season_eval(season):
    matches = data()[0]
    lo, hi = f"20{season[:2]}-07-01", f"20{season[2:]}-07-01"
    return [m for m in matches if m["ctx"] == EUROPE_CTX and m.get("comp") and lo <= m["date"] < hi]


def _fit_date(args):
    d, cfg = args
    from model.europe import Ratings
    matches, groups, _, _ = data()
    window = [m for m in matches if m["date"] >= f"{int(d[:4]) - 3}{d[4:]}"]
    return d, {s: Ratings(**cfg).fit(window, groups, s, d) for s in STATS}


def fit_all(season, cfg):
    matches, groups, _, _ = data()
    params, tuning = load_tuned()
    dates = sorted({m["date"] for m in season_eval(season)})
    with ProcessPoolExecutor() as ex:
        fitted = dict(ex.map(_fit_date, [(d, cfg) for d in dates]))
    return {d: EuropePredictor(params, tuning, cfg).attach(matches, groups, d, r) for d, r in fitted.items()}


def baseline_means(date, stat):
    """Plain European average: home/away means over the previous 365 days of European games."""
    hk, ak = STATS[stat]
    y = f"{int(date[:4]) - 1}{date[4:]}"
    ms = [m for m in data()[0] if m["ctx"] == EUROPE_CTX and m.get("comp") and y <= m["date"] < date and has_stat(m, stat)]
    if not ms:
        return None
    return sum(m[hk] for m in ms) / len(ms), sum(m[ak] for m in ms) / len(ms)


def pairs(season, preds, tuning, params, blend=True):
    p = copy.deepcopy(params)
    if not blend:
        p.blend_weight = 0.0
    out = []
    for m in season_eval(season):
        P = preds[m["date"]]
        P.params, P.t = p, tuning
        o = P.predict(m["home"], m["away"], fast=True)
        out.append((m, {s: (o["stats"][s]["home"], o["stats"][s]["away"]) for s in STATS}))
    return out


def base_pairs(season):
    out = []
    cache = {}
    for m in season_eval(season):
        lam = {}
        for s in STATS:
            k = (m["date"], s)
            if k not in cache:
                cache[k] = baseline_means(m["date"], s)
            lam[s] = cache[k] or (1.4, 1.1)
        out.append((m, lam))
    return out


def fit_alpha(pairs_, stat):
    hk, ak = STATS[stat]
    num = den = 0.0
    for m, lam in pairs_:
        if has_stat(m, stat):
            mu = sum(lam[stat])
            num += (m[hk] + m[ak] - mu) ** 2 - mu
            den += mu * mu
    return max(num / den, 0.0) if den else 0.0


def evaluate(pairs_, params, tuning):
    p = copy.deepcopy(params)
    p.nb_alpha = {**p.nb_alpha, **tuning.get("europe_nb_alpha", {})}
    return {s: score_stat(s, pairs_, p) for s in STATS}


def main():
    params, tuning = load_tuned()
    print(f"European matches: {len(season_eval(TUNE))} in {TUNE}, {len(season_eval(TEST))} in {TEST}", flush=True)
    best = None
    for hl, tau in itertools.product([400.0, 700.0], [0.15, 0.25]):
        cfg = {"half_life": hl, "tau": tau, "sigma": 0.6}
        preds = fit_all(TUNE, cfg)
        gap = fit_gap(preds, season_eval(TUNE))
        for fk in (10.0, 20.0):
            t = {**tuning, "europe_gap_coef": gap, "europe_form_k": fk, "europe_h2h_k": 3.0}
            pr = pairs(TUNE, preds, t, params)
            t["europe_nb_alpha"] = {s: (0.0 if s == "goals" else round(fit_alpha(pr, s), 4)) for s in STATS}
            res = evaluate(pr, params, t)
            obj = sum(r["objective"] for r in res.values())
            print(f"  half_life={hl:.0f} tau={tau} form_k={fk}: objective {obj:.4f}  (1X2 ll {res['goals']['ll']:.4f})", flush=True)
            if best is None or obj < best[0]:
                best = (obj, cfg, t)
    _, cfg, t = best
    print("Chosen:", cfg, {k: t[k] for k in ("europe_form_k",)}, flush=True)

    print(f"Testing on {TEST}", flush=True)
    preds = fit_all(TEST, cfg)
    model_p = pairs(TEST, preds, t, params)
    pure_p = pairs(TEST, preds, t, params, blend=False)
    base_p = base_pairs(TEST)
    res = {"model": evaluate(model_p, params, t), "pure": evaluate(pure_p, params, t), "baseline": evaluate(base_p, params, t)}
    for s in STATS:
        m, b, pu = res["model"][s], res["baseline"][s], res["pure"][s]
        print(f"  {s:16s} model {m['objective']:.4f} vs Europe average {b['objective']:.4f} ({(1 - m['objective'] / b['objective']) * 100:+.1f}%)"
              f" | statistics alone {pu['objective']:.4f} | MAE {m['mae']:.2f} vs {b['mae']:.2f}", flush=True)
    g, gb = res["model"]["goals"], res["baseline"]["goals"]
    print(f"  1X2 brier {g['brier']:.4f} vs {gb['brier']:.4f} ({(1 - g['brier'] / gb['brier']) * 100:+.1f}%), log loss {g['ll']:.4f} vs {gb['ll']:.4f}", flush=True)
    by_comp = {}
    for c in COMPS:
        mp = [x for x in model_p if x[0]["comp"] == c]
        bp = [x for x in base_p if x[0]["comp"] == c]
        pp = [x for x in pure_p if x[0]["comp"] == c]
        rm, rb, rp = evaluate(mp, params, t), evaluate(bp, params, t), evaluate(pp, params, t)
        by_comp[c] = {"matches": len(mp), "brier_1x2": rm["goals"]["brier"], "baseline_brier_1x2": rb["goals"]["brier"],
                      "ll_1x2": rm["goals"]["ll"], "baseline_ll_1x2": rb["goals"]["ll"],
                      "stats": {s: {"objective": rm[s]["objective"], "baseline_objective": rb[s]["objective"],
                                    "pure_objective": rp[s]["objective"], "mae": rm[s]["mae"], "baseline_mae": rb[s]["mae"]} for s in STATS}}
        print(f"  {c:18s} n={len(mp):3d} 1X2 brier {rm['goals']['brier']:.4f} vs {rb['goals']['brier']:.4f}"
              f" ({(1 - rm['goals']['brier'] / rb['goals']['brier']) * 100:+.1f}%)  "
              + " ".join(f"{s[:4]} {(1 - rm[s]['objective'] / rb[s]['objective']) * 100:+.1f}%" for s in STATS), flush=True)
    # calibration of all probabilities
    bins = [{"lo": i / 10, "hi": (i + 1) / 10, "n": 0, "p": 0.0, "hits": 0} for i in range(10)]
    from model.core import count_probabilities, goal_probabilities
    for m, lam in model_p:
        for s in STATS:
            if not has_stat(m, s):
                continue
            hk, ak = STATS[s]
            tot = m[hk] + m[ak]
            lh, la = lam[s]
            if s == "goals":
                gp = goal_probabilities(lh, la, params.dc_rho)
                ev = [(gp["home_win"], m[hk] > m[ak]), (gp["draw"], m[hk] == m[ak]), (gp["away_win"], m[hk] < m[ak])]
                ev += [(p_, tot > float(l)) for l, p_ in gp["over"].items()]
            else:
                ev = [(p_, tot > float(l)) for l, p_ in count_probabilities(s, lh, la, t["europe_nb_alpha"][s])["over"].items()]
            for p_, y in ev:
                b = bins[min(int(p_ * 10), 9)]
                b["n"] += 1
                b["p"] += p_
                b["hits"] += int(y)
    for b in bins:
        b["avg_predicted"] = b.pop("p") / b["n"] if b["n"] else None
        b["actual"] = b.pop("hits") / b["n"] if b["n"] else None
        if b["n"]:
            print(f"    {b['lo']:.0%}-{b['hi']:.0%}: n={b['n']:4d} predicted {b['avg_predicted']:.1%} actual {b['actual']:.1%}", flush=True)
    out = {"season": TEST, "rating": cfg, "tuning": {k: v for k, v in t.items() if k.startswith("europe_")},
           "matches": len(model_p), "test": res["model"], "baseline": res["baseline"], "pure_stats": res["pure"],
           "by_comp": by_comp, "calibration": bins}
    json.dump(out, open(os.path.join(ROOT, "backtest", "results_europe.json"), "w"), indent=1, default=float)
    json.dump({"rating": cfg, "tuning": out["tuning"]}, open(os.path.join(ROOT, "model", "tuned_europe.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
