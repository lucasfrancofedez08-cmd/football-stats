"""Runs in GitHub Actions: checks every source for candidate leagues and saves history CSVs.
Writes probe/report.json. Usage: python tools/probe_leagues.py"""
import csv
import gzip
import io
import json
import os
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
OUT = "probe"
os.makedirs(OUT, exist_ok=True)
os.makedirs("data/history", exist_ok=True)

FD = {"bundesliga": "D1", "serie-a": "I1", "ligue-1": "F1", "eredivisie": "N1", "primeira-liga": "P1",
      "scottish-premiership": "SC0", "belgian-pro-league": "B1", "super-lig": "T1"}
ESPN = {"bundesliga": "ger.1", "serie-a": "ita.1", "ligue-1": "fra.1", "eredivisie": "ned.1", "primeira-liga": "por.1",
        "europa-league": "uefa.europa", "conference-league": "uefa.europa.conf", "scottish-premiership": "sco.1",
        "belgian-pro-league": "bel.1", "super-lig": "tur.1"}
FOTMOB = {"bundesliga": 54, "serie-a": 55, "ligue-1": 53, "eredivisie": 57, "primeira-liga": 61,
          "europa-league": 73, "conference-league": 10216, "scottish-premiership": 64, "belgian-pro-league": 40, "super-lig": 71}
SEASONS = ["2122", "2223", "2324", "2425", "2526"]
report = {}


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = r.read()
                if d[:2] == b"\x1f\x8b":
                    d = gzip.decompress(d)
                time.sleep(0.2)
                return r.status, d
        except urllib.error.HTTPError as e:
            return e.code, b""
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                return f"ERR {e!r}"[:80], b""
            time.sleep(2)


def fd_summary(text):
    rows = list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))
    cols = rows[0].keys() if rows else []
    def cov(c):
        return sum(1 for r in rows if (r.get(c) or "").strip()) if c in cols else None
    return {"rows": len(rows), "has": {c: cov(c) for c in ("HS", "HST", "HC", "HY", "HR", "Referee", "HxG")},
            "first": rows[0]["Date"] if rows else None, "last": rows[-1]["Date"] if rows else None}


# ---------------------------------------------------------------- football-data.co.uk
for lg, code in FD.items():
    r = report.setdefault(lg, {})
    for s in SEASONS + ["2627"]:
        st, d = get(f"https://www.football-data.co.uk/mmz4281/{s}/{code}.csv")
        if st == 200 and d:
            text = d.decode("utf-8-sig", errors="replace")
            r.setdefault("fd", {})[s] = fd_summary(text)
            if s != "2627":
                with open(f"data/history/{lg}_{s}.csv", "w") as f:
                    f.write(text)
        else:
            r.setdefault("fd", {})[s] = {"status": st}

# ---------------------------------------------------------------- ESPN
E = "https://site.api.espn.com/apis/site/v2/sports/soccer"
for lg, code in ESPN.items():
    r = report.setdefault(lg, {})
    days = ["20261022", "20261023", "20261030"] if "uefa" in code else ["20261101", "20261031", "20261102"]
    events = []
    for dday in days:
        st, d = get(f"{E}/{code}/scoreboard?dates={dday}")
        if st == 200:
            events += json.loads(d).get("events", [])
    done = [e for e in events if e["status"]["type"].get("completed")]
    r["espn"] = {"events": len(events), "completed": len(done)}
    if done:
        st, d = get(f"{E}/{code}/summary?event={done[0]['id']}")
        if st == 200:
            s = json.loads(d)
            teams = s.get("boxscore", {}).get("teams", [])
            r["espn"]["box_stats"] = sorted({x["name"] for t in teams for x in t.get("statistics", [])} &
                                            {"wonCorners", "yellowCards", "redCards", "totalShots", "shotsOnTarget"})
            r["espn"]["rosters"] = sum(len(x.get("roster", [])) for x in s.get("rosters", []))
            r["espn"]["key_events"] = len(s.get("keyEvents") or [])
    # past season availability (for backtests)
    past = "20250927" if "uefa" not in code else "20251001"
    st, d = get(f"{E}/{code}/scoreboard?dates={past}")
    pe = json.loads(d).get("events", []) if st == 200 else []
    r["espn"]["past_season_events"] = len(pe)
    pdone = [e for e in pe if e["status"]["type"].get("completed")]
    if pdone:
        st, d = get(f"{E}/{code}/summary?event={pdone[0]['id']}")
        if st == 200:
            teams = json.loads(d).get("boxscore", {}).get("teams", [])
            r["espn"]["past_box_stats"] = len({x["name"] for t in teams for x in t.get("statistics", [])})

# range queries (fewer calls if supported)
for q in ["dates=20261001-20261031", "dates=202610", "dates=2026&limit=1000", "dates=20261031&limit=200"]:
    st, d = get(f"{E}/ger.1/scoreboard?{q}")
    report.setdefault("_espn_range", {})[q] = [st, len(json.loads(d).get("events", [])) if st == 200 and d else 0]

# ---------------------------------------------------------------- FotMob
seen = {}
for dday in ["20261107", "20261108", "20261105", "20261106"]:
    st, d = get(f"https://www.fotmob.com/api/data/matches?date={dday}")
    if st != 200:
        report.setdefault("_fotmob", {})[dday] = st
        continue
    for L in json.loads(d).get("leagues", []):
        pid = L.get("primaryId")
        for lg, fid in FOTMOB.items():
            if pid == fid and L.get("matches"):
                seen.setdefault(lg, {"name": L.get("name"), "matches": []})["matches"] += [m["id"] for m in L["matches"]]
for lg, v in seen.items():
    r = report.setdefault(lg, {})
    r["fotmob"] = {"name": v["name"], "matches": len(v["matches"])}
    st, d = get(f"https://www.fotmob.com/api/data/matchDetails?matchId={v['matches'][0]}")
    if st == 200:
        lu = (json.loads(d).get("content") or {}).get("lineup") or {}
        r["fotmob"]["unavailable"] = [len((lu.get(k) or {}).get("unavailable") or []) for k in ("homeTeam", "awayTeam")]
for lg in FOTMOB:
    report.setdefault(lg, {}).setdefault("fotmob", {"matches": 0})

with open(f"{OUT}/report.json", "w") as f:
    json.dump(report, f, indent=1)
print(json.dumps(report, indent=1)[:6000])
