"""Runs in GitHub Actions. Collects history for the European model:

  data/history/europe_<season>.json        UCL/UEL/UECL matches with team stats (ESPN scoreboards + summaries)
  data/history/europe_clubs_<season>.json  every match (all competitions) of each club that played in Europe,
                                           from ESPN team schedules (results only)

  python tools/collect_europe.py --probe        quick check of the endpoints
  python tools/collect_europe.py 2023 2024 2025 seasons by start year
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline.sources import ESPN, fetch, parse_event, parse_summary  # noqa: E402

COMPS = {"champions-league": "uefa.champions", "europa-league": "uefa.europa", "conference-league": "uefa.europa.conf"}
OUT = "data/history"


def months(start_year):
    for y, m in [(start_year, m) for m in range(7, 13)] + [(start_year + 1, m) for m in range(1, 7)]:
        yield f"{y}{m:02d}"


def score_of(c):
    s = c.get("score")
    if isinstance(s, dict):
        s = s.get("value", s.get("displayValue"))
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return None


def schedule(team_id, season):
    data = fetch(f"{ESPN}/all/teams/{team_id}/schedule?season={season}", "espn")
    if not data:
        return None
    out = []
    for e in json.loads(data).get("events", []):
        comp = e["competitions"][0]
        st = (comp.get("status") or e.get("status") or {}).get("type", {})
        cs = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if "home" not in cs or "away" not in cs:
            continue
        lg = e.get("league") or {}
        out.append({"id": e["id"], "date": e["date"], "league": lg.get("slug") or lg.get("abbreviation"),
                    "league_name": lg.get("name"), "completed": bool(st.get("completed")),
                    "home": {"id": cs["home"]["team"]["id"], "name": cs["home"]["team"].get("displayName")},
                    "away": {"id": cs["away"]["team"]["id"], "name": cs["away"]["team"].get("displayName")},
                    "hg": score_of(cs["home"]), "ag": score_of(cs["away"])})
    return out


def europe_season(start_year):
    rows = []
    for comp, code in COMPS.items():
        seen = {}
        for mo in months(start_year):
            data = fetch(f"{ESPN}/{code}/scoreboard?dates={mo}&limit=500", "espn")
            if not data:
                continue
            for e in json.loads(data).get("events", []):
                ev = parse_event(e)
                if ev["completed"]:
                    seen[ev["espn_id"]] = ev
        for ev in sorted(seen.values(), key=lambda e: e["kickoff"]):
            data = fetch(f"{ESPN}/{code}/summary?event={ev['espn_id']}", "espn")
            s = parse_summary(json.loads(data)) if data else None
            t = (s or {}).get("teams", {})
            rows.append({"id": ev["espn_id"], "date": ev["kickoff"], "comp": comp, "round": ev.get("round"),
                         "home": {"id": ev["home"]["espn_id"], "name": ev["home"]["name"]},
                         "away": {"id": ev["away"]["espn_id"], "name": ev["away"]["name"]},
                         "hg": ev["hg"], "ag": ev["ag"], "venue": ev.get("venue"),
                         "stats": {side: {k: t.get(side, {}).get(k) for k in ("corners", "yellow", "red", "shots", "sot")}
                                   for side in ("home", "away")} if s else None})
        print(f"  {start_year} {comp}: {len([r for r in rows if r['comp'] == comp])} matches", flush=True)
    return rows


def main():
    os.makedirs(OUT, exist_ok=True)
    if "--probe" in sys.argv:
        rep = {}
        for comp, code in COMPS.items():
            data = fetch(f"{ESPN}/{code}/scoreboard?dates=202511&limit=500", "espn")
            evs = json.loads(data).get("events", []) if data else []
            rep[comp] = {"nov2025_events": len(evs), "completed": sum(1 for e in evs if e["status"]["type"].get("completed"))}
            if evs:
                tid = evs[0]["competitions"][0]["competitors"][0]["team"]["id"]
                for season in (2024, 2025):
                    sc = schedule(tid, season) or []
                    rep[comp][f"schedule_{season}"] = {"team": tid, "events": len(sc),
                                                       "first": sc[0]["date"] if sc else None, "last": sc[-1]["date"] if sc else None,
                                                       "leagues": sorted({x["league"] or "" for x in sc}),
                                                       "scored": sum(1 for x in sc if x["hg"] is not None)}
        os.makedirs("probe", exist_ok=True)
        json.dump(rep, open("probe/europe.json", "w"), indent=1)
        print(json.dumps(rep, indent=1))
        return
    for y in [int(a) for a in sys.argv[1:]]:
        code = f"{y % 100:02d}{(y + 1) % 100:02d}"
        rows = europe_season(y)
        json.dump(rows, open(f"{OUT}/europe_{code}.json", "w"), separators=(",", ":"))
        clubs = sorted({r["home"]["id"] for r in rows} | {r["away"]["id"] for r in rows})
        sched = {}
        for tid in clubs:
            sc = schedule(tid, y)
            if sc is not None:
                sched[tid] = [x for x in sc if x["completed"] and x["hg"] is not None]
            time.sleep(0.05)
        json.dump(sched, open(f"{OUT}/europe_clubs_{code}.json", "w"), separators=(",", ":"))
        print(f"{code}: {len(rows)} European matches, schedules for {len(sched)}/{len(clubs)} clubs", flush=True)


if __name__ == "__main__":
    main()
