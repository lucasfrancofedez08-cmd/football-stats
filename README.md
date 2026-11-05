# Matchday Numbers

Past match statistics and statistical estimates for upcoming matches in seven leagues (Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie, Primeira Liga), plus full stats for the Champions, Europa and Conference League. An information tool, not betting advice: every estimate shows its inputs, its uncertainty and its track record.

**Website:** https://lucasfrancofedez08-cmd.github.io/football-stats/

## How it runs

A GitHub Actions workflow (`.github/workflows/update.yml`) runs every 3 hours:

1. Downloads results and match stats from **football-data.co.uk**, fixtures, lineups, goals and Champions League matches from **ESPN's public feed**, and team news from **FotMob**.
2. Cross-checks the two sources stat by stat. A stat the sources disagree on is shown with both values and left out of the model for that match.
3. Makes predictions for every league match in the next 31 days. A prediction is rewritten on each run until kick-off, then **frozen** (never touched again) and scored after the match. The git history of `data/predictions/` is the proof that each one existed before kick-off.
4. Writes the site data (`site/data/`) and publishes `site/` to GitHub Pages.

Team news (injured and suspended players) comes from **FotMob's public feed** for matches in the next 4 days. When FotMob has nothing, suspensions are worked out from cards. `data/overrides/injuries.json` is a manual override that is merged on top.

## Model

`model/` — expected numbers are 60% statistical base and 40% "form & matchup" views (the owner's chosen split).

- Base (60%): league venue averages × team attack × opponent defence, recency-weighted (last 6 games count double) and shrunk toward last season (or a promoted-team prior). Goals borrow half their strength from shots on target.
- Views (40%, `model/views.py`): form over the last 5 games (16%), team gap in points per game mapped to each stat with effects measured on 2022-25 (14%), and up to 6 head-to-head meetings (10%). Each view shrinks toward the base when its sample is small.
- Then separate, listed adjustments (derby cards, missing players, short rest), and Dixon-Coles for goals / negative binomial for corners, cards and shots.

`backtest/run.py` tunes on 2023-24 and 2024-25 and tests once on 2025-26 (2,364 matches across the seven leagues, walk-forward), with a per-league report. A league only gets estimates (`PREDICTED` in `pipeline/sources.py`) if it beats league averages on win/draw/loss and goals. Results in `backtest/results.json`; tuned parameters in `model/tuned.json`. On the test season the model beats league averages on every stat; the margin is large for win/draw/loss and shots, small for corners and cards. The 60/40 mix scores almost the same as the base alone (slightly better on four stats, slightly worse on cards). Referee history did not improve accuracy, so it is shown for context only.

## Layout

```
model/       prediction model (no network)
pipeline/    sources, merge & cross-check, players, predictions, site data
backtest/    tuning and test on past seasons
data/        history CSVs, state, frozen predictions, overrides
site/        static website (index.html, app.js, styles.css, data/)
tests/       python -m pytest -q
```
