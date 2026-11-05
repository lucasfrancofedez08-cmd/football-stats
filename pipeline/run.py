"""One update run: fetch -> merge & cross-check -> predict & freeze -> score -> write site data.

  python -m pipeline.run            # normal run (GitHub Actions, every few hours)
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import sys
import traceback
import unicodedata
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.data import load_file  # noqa: E402
from model.predict import Predictor  # noqa: E402
from pipeline import merge, players, predictions, site_data, sources, teams  # noqa: E402
from pipeline.sources import DOMESTIC, EUROPE, LEAGUES, PREDICTED  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
HISTORY = os.path.join(DATA, "history")
UPCOMING_DAYS = 31


def jload(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def jsave(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), default=str)
    os.replace(tmp, path)


def model_version():
    h = hashlib.sha256()
    for p in sorted(glob.glob(os.path.join(ROOT, "model", "*.py"))) + [os.path.join(ROOT, "model", "tuned.json")]:
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:10]


def season_start(season, league):
    y = 2000 + int(season[:2])
    return date(y, 9, 1) if league in EUROPE else date(y, 7, 25)


def history_seasons(league, season):
    """Complete earlier seasons from data/history, oldest first."""
    files = sorted(glob.glob(os.path.join(HISTORY, f"{league}_*.csv")))
    out = []
    for f in files:
        s = os.path.basename(f).split("_")[1].split(".")[0]
        if s < season:
            out.append(load_file(f, league, s))
    return out


def roll_history(season, sdir):
    """When a new season starts, keep last season's final football-data.co.uk file as history."""
    y = int(season[:2])
    prev = f"{y - 1:02d}{y:02d}"
    for lg in DOMESTIC:
        dst = os.path.join(HISTORY, f"{lg}_{prev}.csv")
        src = os.path.join(DATA, "state", prev, f"fd_{lg}.csv")
        if not os.path.exists(dst) and os.path.exists(src):
            shutil.copy(src, dst)


def _month(d):
    return d.strftime("%Y%m")


def months_to_fetch(league, events, season, today):
    """ESPN scoreboard months to (re)load: the whole season so far on the first run, then the
    current window (4 days back to a month ahead) plus months holding unfinished past games."""
    if not events:
        d, end, out = season_start(season, league), today + timedelta(days=UPCOMING_DAYS), []
        while d <= end:
            if _month(d) not in out:
                out.append(_month(d))
            d += timedelta(days=27)
        if _month(end) not in out:
            out.append(_month(end))
        return out
    months = {_month(today - timedelta(days=4)), _month(today), _month(today + timedelta(days=UPCOMING_DAYS))}
    for e in events.values():
        d = date.fromisoformat(e["kickoff"][:10])
        if not e.get("completed") and today - timedelta(days=60) <= d < today:
            months.add(_month(d))
    return sorted(months)


_CHARS = str.maketrans({"ı": "i", "ø": "o", "Ø": "O", "ð": "d", "ł": "l", "Ł": "L", "æ": "ae", "ß": "ss", "đ": "d"})


def norm(name):
    s = unicodedata.normalize("NFKD", (name or "").translate(_CHARS)).encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").replace(".", " ").split())


def find_player(name, squad):
    """Squad entry for a name written by another source (accents, initials, surname only)."""
    by_norm = {norm(n): p for n, p in squad.items()}
    k = norm(name)
    if k in by_norm:
        return by_norm[k]
    last = k.split()[-1:] if k else []
    cands = [p for n, p in by_norm.items() if last and n.split()[-1:] == last]
    if len(cands) == 1:
        return cands[0]
    first = k.split()[:1]
    cands = [p for n, p in by_norm.items() if first and len(k.split()) == 1 and n.split()[:1] == first]
    return cands[0] if len(cands) == 1 else None


NOT_OUT = ("doubtful", "back in training")


def injury_text(ret):
    low = (ret or "").strip().lower()
    if not low or low == "unknown":
        return "injured, return date unknown"
    if "season" in low:
        return "injured, out for the season"
    if low.startswith(("early", "mid", "late")):
        parts = ret.split()
        return f"injured, expected back {parts[0].lower()}-{parts[1]}" if len(parts) > 1 else f"injured, expected back {low}"
    return f"injured, {low}"


def team_news(fm_side, squad, overrides_entry, today):
    """Players out for this match. Returns (out, doubtful, known)."""
    out, doubtful, known = [], [], False
    if fm_side is not None:
        known = True
        for u in fm_side:
            p = find_player(u["name"], squad)
            rec = {"name": p["name"] if p else u["name"], "position": (p or {}).get("pos"),
                   "source": "FotMob"}
            ret = (u.get("expected_return") or "").strip()
            if u.get("type") == "suspension":
                rec["reason"] = "suspended"
            elif ret.lower() in NOT_OUT:
                rec["reason"] = f"injury, {ret.lower()}"
                doubtful.append(rec)
                continue
            else:
                rec["reason"] = injury_text(ret)
            out.append(rec)
    if overrides_entry and overrides_entry.get("checked") and \
            (today - date.fromisoformat(overrides_entry["checked"])).days <= 8:
        known = True
        have = {norm(x["name"]) for x in out}
        for x in overrides_entry.get("out", []):
            p = find_player(x["name"], squad)
            if norm((p or x)["name"]) not in have:
                out.append({"name": (p or x)["name"], "position": (p or {}).get("pos"),
                            "reason": x.get("reason") or "out", "source": x.get("source") or "manual"})
    return out, doubtful, known


def fotmob_ids(state_path, fixtures, league_of, now):
    """Links upcoming ESPN fixtures to FotMob matches (same day, closest team names)."""
    import difflib
    ids = jload(state_path, {})
    days = {}
    for e in fixtures:
        if e["espn_id"] not in ids:
            days.setdefault(e["kickoff"][:10].replace("-", ""), []).append(e)
    for d, evs in days.items():
        fm = sources.fotmob_day(d)
        if not fm:
            continue
        for e in evs:
            cands = [m for m in fm if m["league"] == league_of[e["espn_id"]]]
            def sc(m):
                return (difflib.SequenceMatcher(None, norm(m["home"]), norm(e["home"]["name"])).ratio()
                        + difflib.SequenceMatcher(None, norm(m["away"]), norm(e["away"]["name"])).ratio())
            if cands:
                best = max(cands, key=sc)
                if sc(best) >= 1.2:
                    ids[e["espn_id"]] = best["fotmob_id"]
    jsave(state_path, ids)
    return ids


def main():
    now = sources.now_utc()
    today = now.date()
    season = sources.season_code(now)
    sdir = os.path.join(DATA, "state", season)
    log = {"started": now.isoformat(), "season": season, "errors": [], "leagues": {}}
    roll_history(season, sdir)

    # ------------------------------------------------------------ 1. ESPN fixtures & results
    events, summaries = {}, {}
    for lg in LEAGUES:
        path = os.path.join(sdir, f"espn_events_{lg}.json")
        ev = jload(path, {})
        fetched = 0
        for mo in months_to_fetch(lg, ev, season, today):
            res = sources.espn_scoreboard(lg, mo)
            if res is None:
                continue
            if len(res) >= 500:
                log["errors"].append(f"{lg} {mo}: ESPN month query hit its limit, some games may be missing")
            fetched += 1
            for e in res:
                ev[e["espn_id"]] = e
        jsave(path, ev)
        events[lg] = ev
        # ------------------------------------------------------------ 2. match details
        spath = os.path.join(sdir, f"espn_summaries_{lg}.json")
        summ = jload(spath, {})
        new = 0
        for e in ev.values():
            if not e.get("completed") or e["espn_id"] in summ:
                continue
            ko = datetime.fromisoformat(e["kickoff"].replace("Z", "+00:00"))
            if now - ko < timedelta(hours=3):
                continue  # let ESPN's numbers settle
            s = sources.espn_summary(lg, e["espn_id"])
            if s:
                summ[e["espn_id"]] = s
                new += 1
        jsave(spath, summ)
        summaries[lg] = summ
        log["leagues"][lg] = {"scoreboard_months": fetched, "events": len(ev), "new_summaries": new}

    # ------------------------------------------------------------ 3. football-data.co.uk
    fd = {}
    for lg in DOMESTIC:
        path = os.path.join(sdir, f"fd_{lg}.csv")
        text = sources.fd_results_csv(lg, season)
        if text and "HomeTeam" in text:
            with open(path, "w") as f:
                f.write(text)
        elif os.path.exists(path):
            log["errors"].append(f"football-data.co.uk {lg}: download failed, using last good copy")
        fd[lg] = load_file(path, lg, season) if os.path.exists(path) else []
    fixtures_txt = sources.fd_fixtures_csv() or ""
    referees = {}
    if fixtures_txt:
        import csv
        import io
        for r in csv.DictReader(io.StringIO(fixtures_txt.lstrip("﻿"))):
            if r.get("Div") == "E0" and r.get("Referee"):
                d = datetime.strptime(r["Date"].strip(), "%d/%m/%Y").date()
                referees[(d.isoformat(), r["HomeTeam"].strip(), r["AwayTeam"].strip())] = r["Referee"].strip()

    # ------------------------------------------------------------ 4. teams
    tpath = os.path.join(sdir, "teams.json")
    team_map = jload(tpath, {})
    for lg in DOMESTIC:
        team_map[lg] = teams.learn(lg, fd[lg], list(events[lg].values()), team_map.get(lg))
        names = {m["home"] for m in fd[lg]} | {m["away"] for m in fd[lg]}
        missing = sorted(names - set(team_map[lg]))
        if missing:
            log["errors"].append(f"{lg}: no ESPN match for teams {missing}")
    jsave(tpath, team_map)
    espn_teams = {}
    for lg in LEAGUES:
        for e in events[lg].values():
            for side in ("home", "away"):
                t = e[side]
                if t.get("espn_id"):
                    espn_teams[t["espn_id"]] = {**espn_teams.get(t["espn_id"], {}), **{k: v for k, v in t.items() if v}}

    # ------------------------------------------------------------ 5. merge & cross-check
    matches, reports = {}, {}
    fd_of_espn = {}
    for lg in DOMESTIC:
        fe = teams.espn_to_fd(team_map[lg])
        fd_of_espn[lg] = fe
        matches[lg], reports[lg] = merge.merge_league(lg, season, fd[lg], list(events[lg].values()), summaries[lg], fe)
        log["leagues"][lg]["cross_check"] = {k: v for k, v in reports[lg].items() if k != "conflicts"}
        log["leagues"][lg]["conflicts"] = reports[lg]["conflicts"][-30:]
    for lg in EUROPE:
        matches[lg] = merge.europe_records(lg, list(events[lg].values()), summaries[lg], season)

    # ------------------------------------------------------------ 6. players
    squad = {}
    for lg in LEAGUES:
        squad[lg] = players.season_players(matches[lg], summaries[lg], lambda m, side: m[side])

    # ------------------------------------------------------------ 7. predictions (freeze at kick-off)
    version = model_version()
    pdir = os.path.join(DATA, "predictions", season)
    overrides = jload(os.path.join(DATA, "overrides", "injuries.json"), {})
    upcoming = [e for lg in PREDICTED for e in events[lg].values()
                if e.get("status") == "pre" and now < datetime.fromisoformat(e["kickoff"].replace("Z", "+00:00")) < now + timedelta(days=4)]
    league_of = {e["espn_id"]: lg for lg in DOMESTIC for e in events[lg].values()}
    fm_ids = fotmob_ids(os.path.join(sdir, "fotmob_ids.json"), upcoming, league_of, now)
    made = frozen = 0
    for lg in PREDICTED:
        made_lg = made
        prev = history_seasons(lg, season)
        predictor = Predictor(lg, prev)
        fe = fd_of_espn[lg]
        for e in events[lg].values():
            path = os.path.join(pdir, lg, f"{e['espn_id']}.json")
            ko = datetime.fromisoformat(e["kickoff"].replace("Z", "+00:00"))
            if e.get("status") != "pre" or ko <= now:
                frozen += os.path.exists(path)
                continue  # kicked off (or postponed and not rescheduled): never rewritten
            if ko - now > timedelta(days=UPCOMING_DAYS):
                continue
            home, away = fe.get(e["home"]["espn_id"]), fe.get(e["away"]["espn_id"])
            if not home or not away:
                log["errors"].append(f"{lg} {e['espn_id']}: unmapped team, no prediction")
                continue
            cur = [m for m in matches[lg] if m["date"] < e["kickoff"][:10]]
            ctx = {"referee": referees.get((e["kickoff"][:10], home, away))
                   or referees.get(((ko - timedelta(days=1)).date().isoformat(), home, away))}
            news = None
            if ko - now < timedelta(days=4) and e["espn_id"] in fm_ids:
                news = sources.fotmob_unavailable(fm_ids[e["espn_id"]])
            known = True
            for side, team in (("home", home), ("away", away)):
                ctx[f"{side}_label"] = (team_map[lg].get(team) or {}).get("name") or team
                sq = squad[lg].get(team, {})
                ctx[f"{side}_squad"] = sq
                ov = (overrides.get("teams", {}).get(lg, {}) or {}).get(team)
                out, doubtful, ok = team_news(news[side] if news else None, sq, ov, today)
                if not ok:  # no team news: fall back to suspensions worked out from cards
                    out = players.likely_suspended(lg, team, sq, cur) if sq else []
                known = known and ok
                ctx[f"{side}_missing"] = out
                ctx[f"{side}_doubtful"] = doubtful
                if ko - now < timedelta(days=3):
                    last = sources.espn_team_last_match(e[side]["espn_id"], e["kickoff"])
                    if last:
                        lko = datetime.fromisoformat(last[0].replace("Z", "+00:00"))
                        ctx[f"{side}_rest_days"] = (ko.date() - lko.date()).days
                        ctx[f"{side}_europe_midweek"] = "UEFA" in last[1] and (ko - lko).days <= 5
            ctx["injuries_known"] = known
            try:
                p = predictions.make(predictor, e, home, away, cur, ctx, now.isoformat(), version)
                jsave(path, p)
                made += 1
            except Exception as ex:  # one bad fixture must not stop the run
                log["errors"].append(f"prediction {lg} {e['espn_id']}: {ex!r}")
                traceback.print_exc()
        log["leagues"][lg]["predictions"] = made - made_lg
    log["predictions"] = {"made_or_updated": made, "frozen_total": frozen}

    # ------------------------------------------------------------ 8. score frozen predictions
    by_id = {m.get("espn_id"): m for lg in DOMESTIC for m in matches[lg] if m.get("espn_id")}
    scored = []
    for path in glob.glob(os.path.join(DATA, "predictions", "*", "*", "*.json")):
        p = jload(path, None)
        if not p:
            continue
        m = by_id.get(p["id"])
        ko = datetime.fromisoformat(p["kickoff"].replace("Z", "+00:00"))
        if m and ko <= now:
            res = predictions.score(p, m)
            if p.get("result") != res:
                p["result"] = res
                p["scored_at"] = now.isoformat()
                jsave(path, p)
        if p.get("result"):
            scored.append(p)
    log["scored"] = len(scored)

    # ------------------------------------------------------------ 9. site data
    log["calls"] = {"espn": sources.CALLS["espn"], "football_data": sources.CALLS["fd"], "fotmob": sources.CALLS["fotmob"]}
    log["team_news_linked"] = len(fm_ids)
    log["errors"] += sources.CALLS["errors"][-40:]
    log["finished"] = sources.now_utc().isoformat()
    site_data.write(ROOT, season, now, matches, events, summaries, fd, team_map, espn_teams, squad,
                    pdir, scored, log, reports)
    jsave(os.path.join(DATA, "state", "last_run.json"), log)
    print(json.dumps({k: v for k, v in log.items() if k != "errors"}, indent=1))
    if log["errors"]:
        print("ERRORS:\n  " + "\n  ".join(log["errors"][:60]))


if __name__ == "__main__":
    main()
