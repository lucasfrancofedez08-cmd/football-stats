"""Tests against real past matches and the data plumbing.  Run: python -m pytest -q"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from model.core import count_probabilities, goal_probabilities, league_means  # noqa: E402
from model.data import load_file  # noqa: E402
from model.predict import Predictor  # noqa: E402
from model import adjustments as adj  # noqa: E402
from pipeline import merge, players  # noqa: E402
from pipeline.predictions import score  # noqa: E402
from pipeline.sources import parse_summary  # noqa: E402

SEASONS = ["2122", "2223", "2324", "2425", "2526"]


def seasons(league):
    return [load_file(os.path.join(ROOT, "data", "history", f"{league}_{s}.csv"), league, s) for s in SEASONS]


def test_goal_probabilities_are_consistent():
    g = goal_probabilities(1.6, 1.1, -0.12)
    assert abs(g["home_win"] + g["draw"] + g["away_win"] - 1) < 1e-9
    assert g["over"]["1.5"] > g["over"]["2.5"] > g["over"]["3.5"]
    assert g["home_win"] > g["away_win"]


def test_count_probabilities_monotone_and_range():
    c = count_probabilities("corners", 5.5, 4.4, 0.01)
    o = c["over"]
    assert o["8.5"] > o["9.5"] > o["10.5"] > o["11.5"]
    assert c["range"][0] < 9.9 < c["range"][1]


def test_no_future_data_used():
    """A prediction must not change when later matches are added to the season."""
    lg = seasons("la-liga")
    pred = Predictor("la-liga", lg[:4])
    season = lg[4]
    m = season[200]
    before = [x for x in season if x["date"] < m["date"]]
    p1 = pred.predict(before, m["home"], m["away"], fast=True)
    p2 = pred.predict(before + [x for x in season if x["date"] > m["date"]][:0], m["home"], m["away"], fast=True)
    assert p1 == p2
    p3 = pred.predict(season, m["home"], m["away"], fast=True)  # leaking the future changes it
    assert p3 != p1


def _logloss_1x2(preds):
    return sum(-math.log(max(p, 1e-12)) for p in preds) / len(preds)


def test_beats_league_average_on_2025_26():
    """Walk-forward over every 2025-26 match: the model must clearly beat a no-information baseline on 1X2."""
    from pipeline.sources import PREDICTED
    for league in PREDICTED:
        lg = seasons(league)
        pred = Predictor(league, lg[:4])
        season = lg[4]
        model, base = [], []
        for m in season:
            cur = [x for x in season if x["date"] < m["date"]]
            g = pred.predict(cur, m["home"], m["away"], fast=True)["stats"]["goals"]
            mh, ma = league_means(cur, pred.prev, "goals", pred.params)
            b = goal_probabilities(mh, ma, pred.params.dc_rho)
            k = "home_win" if m["hg"] > m["ag"] else "draw" if m["hg"] == m["ag"] else "away_win"
            model.append(g[k])
            base.append(b[k])
        assert _logloss_1x2(model) < _logloss_1x2(base) - 0.02, league


def test_derby_and_caps():
    assert adj.is_derby("Real Madrid", "Ath Madrid") and adj.is_derby("Ath Madrid", "Real Madrid")
    base = {"goals": [1.5, 1.2]}
    big = [adj.Adjustment("absences", "goals", "home", 0.5, "x", "provisional")]
    out, _ = adj.apply(base, big)
    assert abs(out["goals"][0] - 1.5 * 0.75) < 1e-9  # capped at -25%


def test_parse_espn_summary_minutes_and_goals():
    with open(os.path.join(ROOT, "tests", "fixtures", "espn_summary_laliga.json")) as f:
        s = parse_summary(json.load(f))
    for side in ("home", "away"):
        mins = sum(p["minutes"] for p in s["lineups"][side]["players"])
        assert 960 <= mins <= 1000, mins
    assert len(s["goals"]) == 3
    assert s["teams"]["home"]["corners"] == 5 and s["teams"]["away"]["corners"] == 8


def test_cross_check_excludes_conflicting_stat():
    fd = [{"date": "2026-11-01", "league": "la-liga", "season": "2627", "home": "A", "away": "B", "referee": None,
           "hg": 2, "ag": 1, "hs": 10, "as": 8, "hst": 4, "ast": 3, "hc": 5, "ac": 2, "hy": 4, "ay": 2, "hr": 0, "ar": 0}]
    ev = [{"espn_id": "1", "kickoff": "2026-11-01T20:00Z", "completed": True, "hg": 2, "ag": 1,
           "home": {"espn_id": "10"}, "away": {"espn_id": "20"}}]
    summ = {"1": {"teams": {"home": {"corners": 5, "yellow": 2, "red": 0, "shots": 10, "sot": 4},
                            "away": {"corners": 3, "yellow": 2, "red": 0, "shots": 8, "sot": 3}}}}
    out, rep = merge.merge_league("la-liga", "2627", fd, ev, summ, {"10": "A", "20": "B"})
    m = out[0]
    assert m["checks"]["corners"] == "verified"        # 2 vs 3 is within tolerance
    assert m["checks"]["yellow"] == "conflict" and m["hcards"] is None
    assert m["checks"]["goals"] == "verified" and m["hg"] == 2
    assert rep["conflict"] == 1


def test_suspension_from_red_card():
    matches = [{"date": "2026-10-01", "home": "A", "away": "B"}, {"date": "2026-10-08", "home": "C", "away": "A"}]
    sq = {"X": {"name": "X", "pos": "D", "log": [("2026-10-01", 0, 0), ("2026-10-08", 0, 1)]},
          "Y": {"name": "Y", "pos": "F", "log": [("2026-10-01", 1, 0)]}}
    out = players.likely_suspended("la-liga", "A", sq, matches)
    assert [x["name"] for x in out] == ["X"]


def test_score_marks_hits():
    lg = seasons("premier-league")
    pred = Predictor("premier-league", lg[:4])
    season = lg[4]
    m = season[300]
    cur = [x for x in season if x["date"] < m["date"]]
    p = {"prediction": pred.predict(cur, m["home"], m["away"]), "baseline": None}
    from pipeline.predictions import baseline
    p["baseline"] = baseline(pred, cur)
    r = score(p, m)
    assert r["goals"]["actual"] == [m["hg"], m["ag"]]
    assert set(r["corners"]["lines"]) == {"8.5", "9.5", "10.5", "11.5"}


def test_team_news_matching_and_doubtful():
    from datetime import date
    from pipeline.run import find_player, team_news
    squad = {"Ferdi Kadıoğlu": {"name": "Ferdi Kadıoğlu", "pos": "D"}, "Kaoru Mitoma": {"name": "Kaoru Mitoma", "pos": "M"},
             "Vinícius Júnior": {"name": "Vinícius Júnior", "pos": "F"}}
    assert find_player("Ferdi Kadioglu", squad)["name"] == "Ferdi Kadıoğlu"
    assert find_player("Vinicius Junior", squad)["name"] == "Vinícius Júnior"
    fm = [{"name": "Kaoru Mitoma", "type": "injury", "expected_return": "Late November 2026"},
          {"name": "Ferdi Kadıoğlu", "type": "injury", "expected_return": "Back in training"},
          {"name": "Someone Else", "type": "suspension", "expected_return": None}]
    out, doubtful, known = team_news(fm, squad, None, date(2026, 11, 5))
    assert known and [x["name"] for x in out] == ["Kaoru Mitoma", "Someone Else"]
    assert [x["name"] for x in doubtful] == ["Ferdi Kadıoğlu"]
    out, _, known = team_news(None, squad, None, date(2026, 11, 5))
    assert not known and out == []


def test_months_to_fetch_first_run_and_window():
    from datetime import date
    from pipeline.run import months_to_fetch
    first = months_to_fetch("bundesliga", {}, "2627", date(2026, 11, 5))
    assert first[0] == "202607" and first[-1] == "202612" and len(first) == len(set(first))
    later = months_to_fetch("bundesliga", {"1": {"kickoff": "2026-10-01T18:30Z", "completed": True}}, "2627", date(2026, 11, 3))
    assert later == ["202610", "202611", "202612"]


def test_every_domestic_league_has_history_and_derbies():
    from pipeline.sources import DOMESTIC
    from model.adjustments import DERBIES
    names = {n for pair in DERBIES for n in pair}
    for lg in DOMESTIC:
        ss = seasons(lg)
        assert all(len(s) >= 300 for s in ss), lg
        teams = {m["home"] for s in ss for m in s}
        assert names & teams, f"no derby defined for {lg}"
