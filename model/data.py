"""Loaders that turn source files into the model's match dicts."""
from __future__ import annotations

import csv
import io
from datetime import datetime

LEAGUE_CODES = {"E0": "premier-league", "SP1": "la-liga"}

COLS = {"FTHG": "hg", "FTAG": "ag", "HTHG": "hthg", "HTAG": "htag", "HS": "hs", "AS": "as",
        "HST": "hst", "AST": "ast", "HF": "hf", "AF": "af", "HC": "hc", "AC": "ac",
        "HY": "hy", "AY": "ay", "HR": "hr", "AR": "ar"}


def _date(s):
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"unrecognised date {s!r}")


def _int(s):
    s = (s or "").strip()
    if s == "":
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_football_data_csv(text, league, season):
    """football-data.co.uk results CSV (or its GitHub mirror) -> match dicts."""
    rows = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    out = []
    for r in rows:
        if not r.get("HomeTeam") or not r.get("Date"):
            continue
        m = {"date": _date(r["Date"]), "time": (r.get("Time") or "").strip() or None,
             "league": league, "season": season,
             "home": r["HomeTeam"].strip(), "away": r["AwayTeam"].strip(),
             "referee": (r.get("Referee") or "").strip() or None}
        for src, dst in COLS.items():
            m[dst] = _int(r.get(src))
        for src, dst in (("HxG", "hxg"), ("AxG", "axg")):
            v = (r.get(src) or "").strip()
            try:
                m[dst] = float(v) if v else None
            except ValueError:
                m[dst] = None
        if m["hg"] is None or m["ag"] is None:
            continue
        m["hcards"] = None if m["hy"] is None or m["hr"] is None else m["hy"] + m["hr"]
        m["acards"] = None if m["ay"] is None or m["ar"] is None else m["ay"] + m["ar"]
        out.append(m)
    out.sort(key=lambda m: (m["date"], m["home"]))
    return out


def load_file(path, league, season):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return parse_football_data_csv(f.read(), league, season)
