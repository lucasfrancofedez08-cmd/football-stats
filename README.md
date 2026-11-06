# Matchday Numbers

Past match statistics and statistical estimates for upcoming matches in seven leagues (Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie, Primeira Liga), and the Champions, Europa and Conference League. An information tool, not betting advice: every estimate shows its inputs, its uncertainty and its track record.

**Website:** https://lucasfrancofedez08-cmd.github.io/football-stats/

## How it runs

A GitHub Actions workflow (`.github/workflows/update.yml`) runs every 3 hours:

1. Downloads results and match stats from **football-data.co.uk**, fixtures, lineups, goals and Champions League matches from **ESPN's public feed**, and team news from **FotMob**.
2. Cross-checks the two sources stat by stat (and FotMob for referees). A stat the sources disagree on is shown with both values and left out of the model for that match.
3. Makes predictions for every match in the next 31 days, all ten competitions. A prediction is rewritten on each run until kick-off, then **frozen** (never touched again) and scored after the match. The git history of `data/predictions/` is the proof that each one existed before kick-off.
4. Writes the site data (`site/data/`) and publishes `site/` to GitHub Pages.

Team news (injured and suspended players) comes from **FotMob's public feed** for matches in the next 4 days. When FotMob has nothing, suspensions are worked out from cards. `data/overrides/injuries.json` is a manual override that is merged on top.

## Model

One recipe for every match, league or European (`model/recipe.py`, run by `pipeline/engine.py`):

**final = 60% base + 40% adjusted**

- **Base (60%)** — `model/ratings.py`: a penalised, time-weighted Poisson rating fit per stat (half-life 300 days, last three seasons). The home team's home attack against the away team's away defence (and the reverse), opponent-adjusted and measured against the competition's average; small team-specific home/away deviations. League games use a fit on that league only; European games use one joint fit over every league, every club's domestic and qualifying games (ESPN team schedules) and the European matches, so clubs share a scale. How far a team may sit from its league's level (`tau_by_stat`) was tuned per stat: wide for goals, narrow for corners and shots, where raw team averages overstate real differences.
- **Adjustments (40%)**, each listed on the match page with its effect on the final number: momentum (last 6 games in any competition vs what the ratings expected, with head-to-head as 20% of it), missing players (factor 1 − the player's share of team goals + ½ assists, which at 40% weight means a replacement covers 60%; a missing regular keeper or defender adds 3% to the opponent), referee for cards (his record blended with 30 average games), fixture congestion, derby and high stakes. Measured effects are converted so their effect on the final number equals what was measured.
- **Probabilities**: Dixon-Coles for goals, negative binomial for corners, cards and shots.
- **Analyst view**: optional written judgement per match (`data/overrides/analyst.json`), shown separately and never mixed into the numbers.

`backtest/recipe.py` tunes on 2024-25 and tests once on 2025-26 (2,895 matches, all ten competitions, walk-forward by week), against plain averages and against the previous method. Results in `backtest/results_recipe.json`, settings in `model/tuned_recipe.json`. On the test season:

- Win/draw/loss and goals beat the plain average in every competition (Brier 0.585 vs 0.648 overall) and are level with the previous method (within about 1% everywhere; best gain Premier League +1.1%).
- Cards, shots and shots on target each beat the average in 8 of 10 competitions (by small margins); corners are level with the average (−2% to +2%).
- Momentum measured as weak: recent form adds little once the base weights recent games, so its tuned size is small. Derbies: +18% cards. Stakes and congestion: no measurable effect (shown for information, size 0).

Referees for every competition come from FotMob (`tools/collect_referees.py` for history, live for upcoming matches). Finished matches without a frozen estimate get a "model check" (`data/retro/`), clearly labelled and outside the track record. Older modules (`model/predict.py`, `model/views.py`, `model/europe.py` predictor) are kept for earlier frozen estimates and the previous backtests.

## Layout

```
model/       prediction model (no network)
pipeline/    sources, merge & cross-check, players, predictions, site data
backtest/    tuning and test on past seasons
data/        history CSVs, state, frozen predictions, overrides
site/        static website (index.html, app.js, styles.css, data/)
tests/       python -m pytest -q
```
