"""Live estimates for European competition matches (see model/europe.py for the model)."""
from __future__ import annotations

import glob
import json
import os
from datetime import datetime, timedelta

from model.core import STATS, count_probabilities, goal_probabilities
from model.data import load_file
from model.europe import EUROPE_CTX, EuropePredictor, Ratings, assemble
from model.predict import load_tuned
from pipeline import sources
from pipeline.predictions import rnd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY = os.path.join(ROOT, "data", "history")
TUNED = os.path.join(ROOT, "model", "tuned_europe.json")


def load_tuned_europe():
    if not os.path.exists(TUNED):
        return None
    with open(TUNED) as f:
        return json.load(f)


def live_rows(league, records, events):
    """Live European match records -> the collector's row format."""
    name = {}
    for e in events.values():
        for side in ("home", "away"):
            name[e[side]["espn_id"]] = e[side]["name"]
    out = []
    for m in records:
        out.append({"id": m.get("espn_id"), "date": m.get("kickoff") or m["date"], "comp": league,
                    "home": {"id": m["home"], "name": name.get(m["home"], m["home"])},
                    "away": {"id": m["away"], "name": name.get(m["away"], m["away"])},
                    "hg": m["hg"], "ag": m["ag"],
                    "stats": {"home": {"corners": m.get("hc"), "yellow": m.get("hy"), "red": m.get("hr"), "shots": m.get("hs"), "sot": m.get("hst")},
                              "away": {"corners": m.get("ac"), "yellow": m.get("ay"), "red": m.get("ar"), "shots": m.get("as"), "sot": m.get("ast")}}})
    return out


def club_schedules(state_path, club_ids, season_year, now, log, jload, jsave):
    """ESPN schedules (all competitions) of this season's European clubs, refreshed once a day."""
    st = jload(state_path, {"fetched": {}, "games": {}})
    for tid in club_ids:
        last = st["fetched"].get(tid)
        if last and now - datetime.fromisoformat(last) < timedelta(hours=20):
            continue
        sc = sources.espn_team_schedule(tid, season_year)
        if sc is None:
            continue
        st["games"][tid] = [g for g in sc if g["completed"] and g["hg"] is not None]
        st["fetched"][tid] = now.isoformat()
    jsave(state_path, st)
    return st["games"]


def build(season, now, fd, matches, events, team_map, sdir, log, jload, jsave):
    """Returns (predictor, team->domestic info) or (None, None) when the model isn't available."""
    tuned = load_tuned_europe()
    if not tuned:
        return None, None
    params, tuning = load_tuned()
    tuning = {**tuning, **tuned["tuning"]}
    y = 2000 + int(season[:2])
    hist_fd = {}
    for lg in fd:
        files = sorted(glob.glob(os.path.join(HISTORY, f"{lg}_*.csv")))[-3:]
        hist_fd[lg] = [m for f in files for m in load_file(f, lg, os.path.basename(f)[-8:-4])] + list(fd[lg])
    rows, clubs = [], {}
    for f in sorted(glob.glob(os.path.join(HISTORY, "europe_[0-9]*.json")))[-3:]:
        rows += json.load(open(f))
    for f in sorted(glob.glob(os.path.join(HISTORY, "europe_clubs_*.json")))[-3:]:
        for tid, games in json.load(open(f)).items():
            clubs.setdefault(tid, []).extend(games)
    eu = [lg for lg in events if lg in sources.EUROPE]
    for lg in eu:
        rows += live_rows(lg, matches[lg], events[lg])
    ids = sorted({e[side]["espn_id"] for lg in eu for e in events[lg].values() for side in ("home", "away")})
    live_clubs = club_schedules(os.path.join(sdir, "europe_clubs.json"), ids, y, now, log, jload, jsave)
    for tid, games in live_clubs.items():
        clubs.setdefault(tid, []).extend(games)
    extra = {lg: {n: t["espn_id"] for n, t in (team_map.get(lg) or {}).items()} for lg in fd}
    allm, groups, names = assemble(hist_fd, rows, clubs, extra)
    asof = (now + timedelta(days=1)).date().isoformat()
    window = [m for m in allm if m["date"] >= f"{now.year - 3}-{now.strftime('%m-%d')}"]
    cfg = tuned["rating"]
    ratings = {s: Ratings(**cfg).fit(window, groups, s, asof) for s in STATS}
    ep = EuropePredictor(params, tuning, cfg).attach(allm, groups, asof, ratings)
    ep.window = window
    log["europe_model"] = {"matches": len(window), "teams": len(ratings["goals"].att),
                           "leagues": len({g for g in groups.values()})}
    return ep, groups


def baseline(ep):
    """European average for the stat (what you'd predict knowing nothing about the teams)."""
    out = {}
    year_ago = (datetime.fromisoformat(ep.asof) - timedelta(days=365)).date().isoformat()
    for stat, (hk, ak) in STATS.items():
        ms = [m for m in ep.window if m["ctx"] == EUROPE_CTX and m.get("comp") and m["date"] >= year_ago
              and m.get(hk) is not None and m.get(ak) is not None]
        mh = sum(m[hk] for m in ms) / len(ms) if ms else 1.5
        ma = sum(m[ak] for m in ms) / len(ms) if ms else 1.1
        if stat == "goals":
            g = goal_probabilities(mh, ma, ep.params.dc_rho)
            out[stat] = {"total": mh + ma, "home_win": g["home_win"], "draw": g["draw"], "away_win": g["away_win"],
                         "over": g["over"], "btts": g["btts"]}
        else:
            alpha = ep.t.get("europe_nb_alpha", {}).get(stat, ep.params.nb_alpha[stat])
            out[stat] = {"total": mh + ma, **count_probabilities(stat, mh, ma, alpha)}
    return out


def make(ep, league, fixture, ctx, labels, made_at, version):
    p = ep.predict(fixture["home"]["espn_id"], fixture["away"]["espn_id"], ctx, labels=labels)
    p["league"] = league
    return rnd({
        "id": fixture["espn_id"], "league": league, "kickoff": fixture["kickoff"],
        "home": fixture["home"]["espn_id"], "away": fixture["away"]["espn_id"], "made_at": made_at, "model_version": version,
        "prediction": p, "baseline": baseline(ep),
        "missing": {"home": ctx.get("home_missing") or [], "away": ctx.get("away_missing") or []},
        "doubtful": {"home": ctx.get("home_doubtful") or [], "away": ctx.get("away_doubtful") or []},
        "team_news": bool(ctx.get("injuries_known")),
    })
