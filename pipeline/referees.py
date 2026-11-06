"""Referees (from FotMob) joined to our match records."""
from __future__ import annotations

import difflib
import glob
import json
import os
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

EUROPE_CTX = "europe"


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    for w in ("fc ", " fc", "cf ", " cf", "afc ", "ac ", "sc ", " sc", "1. ", "club "):
        s = s.replace(w, " ")
    return " ".join(s.replace("-", " ").replace(".", " ").split())


def load_rows(history_dir):
    rows = []
    for f in sorted(glob.glob(os.path.join(history_dir, "referees_*.json"))):
        with open(f) as fh:
            rows += json.load(fh)
    return rows


def join(matches, names, rows, domestic):
    """FotMob referee records -> {(date, home, away): referee}, matched on day (+-1), score and team names."""
    idx = defaultdict(list)
    for m in matches:
        if m["ctx"] in domestic or m["ctx"] == EUROPE_CTX:
            idx[(m["ctx"], m["date"])].append(m)
    out = {}
    for r in rows:
        if not r.get("referee") or not r.get("kickoff") or r.get("hg") is None:
            continue
        ctx = r["league"] if r["league"] in domestic else EUROPE_CTX
        d = date.fromisoformat(r["kickoff"][:10])
        best, bs = None, 0.0
        for k in (0, -1, 1):
            for m in idx.get((ctx, (d + timedelta(days=k)).isoformat()), []):
                if (m["hg"], m["ag"]) != (r["hg"], r["ag"]):
                    continue
                sc = (difflib.SequenceMatcher(None, norm(names.get(m["home"], "")), norm(r["home"])).ratio()
                      + difflib.SequenceMatcher(None, norm(names.get(m["away"], "")), norm(r["away"])).ratio())
                if sc > bs:
                    best, bs = m, sc
        if best and bs >= 1.0:
            out[(best["date"], best["home"], best["away"])] = r["referee"]
    return out
