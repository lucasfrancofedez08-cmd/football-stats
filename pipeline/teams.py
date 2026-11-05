"""Links football-data.co.uk team names to ESPN teams.

Learned automatically: two records of the same match (same day, same score) vote for
the pairing. Names listed in KNOWN are used when there are not enough votes yet
(e.g. a team's first game of the season).
"""
from __future__ import annotations

import difflib
from collections import Counter, defaultdict
from datetime import date, timedelta

KNOWN = {
    "premier-league": {
        "Man City": "Manchester City", "Man United": "Manchester United", "Nott'm Forest": "Nottingham Forest",
        "Newcastle": "Newcastle United", "Wolves": "Wolverhampton Wanderers", "Tottenham": "Tottenham Hotspur",
        "West Ham": "West Ham United", "Brighton": "Brighton & Hove Albion", "Bournemouth": "AFC Bournemouth",
        "Leeds": "Leeds United", "Coventry": "Coventry City", "Ipswich": "Ipswich Town", "Leicester": "Leicester City",
        "Luton": "Luton Town", "Sheffield United": "Sheffield United", "Sunderland": "Sunderland",
        "Middlesbrough": "Middlesbrough", "Norwich": "Norwich City", "Watford": "Watford", "Hull": "Hull City",
        "Stoke": "Stoke City", "West Brom": "West Bromwich Albion", "Swansea": "Swansea City", "Cardiff": "Cardiff City",
    },
    "la-liga": {
        "Ath Madrid": "Atlético Madrid", "Ath Bilbao": "Athletic Club", "Betis": "Real Betis", "Sociedad": "Real Sociedad",
        "Vallecano": "Rayo Vallecano", "Espanol": "Espanyol", "Celta": "Celta Vigo", "Alaves": "Alavés",
        "Santander": "Racing Santander", "Cadiz": "Cádiz", "Almeria": "Almería", "Leganes": "Leganés",
        "Las Palmas": "Las Palmas", "Mallorca": "Mallorca", "Granada": "Granada", "Valladolid": "Real Valladolid",
        "Oviedo": "Real Oviedo", "Elche": "Elche", "Levante": "Levante", "Girona": "Girona", "Osasuna": "Osasuna",
        "Sp Gijon": "Sporting Gijón", "Zaragoza": "Real Zaragoza", "La Coruna": "Deportivo La Coruña",
        "Huesca": "Huesca", "Eibar": "Eibar", "Malaga": "Málaga", "Cordoba": "Córdoba", "Castellon": "Castellón",
        "Mirandes": "Mirandés", "Burgos": "Burgos", "Albacete": "Albacete", "Eldense": "Eldense", "Tenerife": "Tenerife",
    },
}


def _d(s):
    return date.fromisoformat(s[:10])


def learn(league, fd_matches, espn_events, previous):
    """Returns {fd_name: espn_team_dict}. `previous` is the last stored mapping."""
    votes = defaultdict(Counter)
    teams_by_id = {}
    by_day = defaultdict(list)
    for e in espn_events:
        teams_by_id[e["home"]["espn_id"]] = e["home"]
        teams_by_id[e["away"]["espn_id"]] = e["away"]
        if e.get("completed"):
            by_day[_d(e["kickoff"])].append(e)
    for m in fd_matches:
        d = _d(m["date"])
        for day in (d, d + timedelta(days=1), d - timedelta(days=1)):
            cands = [e for e in by_day.get(day, []) if e["hg"] == m["hg"] and e["ag"] == m["ag"]]
            for e in cands:
                w = 1.0 / len(cands)
                votes[m["home"]][e["home"]["espn_id"]] += w
                votes[m["away"]][e["away"]["espn_id"]] += w
    mapping = dict(previous or {})
    fd_names = {m["home"] for m in fd_matches} | {m["away"] for m in fd_matches}
    used = set()
    for name, c in sorted(votes.items(), key=lambda kv: -max(kv[1].values())):
        (tid, top), *rest = c.most_common(2) + [(None, 0)]
        second = rest[0][1] if rest else 0
        if top >= 2 and top >= 2 * second and tid not in used:
            mapping[name] = dict(teams_by_id[tid])
            used.add(tid)
    by_name = {t["name"]: t for t in teams_by_id.values()}
    for name in fd_names - set(mapping):
        target = KNOWN.get(league, {}).get(name, name)
        if target in by_name:
            mapping[name] = dict(by_name[target])
            continue
        close = difflib.get_close_matches(target, list(by_name), n=1, cutoff=0.75)
        if close:
            mapping[name] = dict(by_name[close[0]])
    return mapping


def espn_to_fd(mapping):
    return {t["espn_id"]: name for name, t in mapping.items()}
