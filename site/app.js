"use strict";
const app = document.getElementById("app");
const STAT = { goals: "Goals", corners: "Corners", cards: "Cards", shots: "Shots", shots_on_target: "Shots on target" };
const STAT_HELP = { cards: "yellow + red, both teams", corners: "both teams", goals: "both teams", shots: "both teams", shots_on_target: "both teams" };
const LEAGUES = { "la-liga": "La Liga", "premier-league": "Premier League", "champions-league": "Champions League" };
const BANNER = `<p class="banner">Statistical estimates, not advice. Football is unpredictable — use your own judgement.</p>`;
let version = String(Date.now());
const cache = {};

function get(path) {
  if (!cache[path]) {
    cache[path] = fetch(`data/${path}?v=${encodeURIComponent(version)}`).then(r => {
      if (!r.ok) throw new Error(`${r.status} ${path}`);
      return r.json();
    });
  }
  return cache[path];
}

/* ---------------------------------------------------------------- helpers */
const h = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = p => (p == null ? "–" : `${Math.round(p * 100)}%`);
const fx = (x, d = 1) => (x == null ? "–" : Number(x).toFixed(d));
const kickFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const kick = iso => (iso ? kickFmt.format(new Date(iso)) : "");
const day = iso => (iso ? dayFmt.format(new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso)) : "");
const time = iso => (iso ? timeFmt.format(new Date(iso)) : "");
function ago(iso) {
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  if (m < 60) return `${m} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
  return day(iso);
}
const crest = (t, cls = "sm") => (t && t.logo ? `<img class="crest ${cls}" src="${h(t.logo)}" alt="" loading="lazy" width="22" height="22" onerror="this.style.visibility='hidden'">` : `<span class="crest ${cls}"></span>`);
const tlink = t => `<a class="tlink" href="#/team/${h(t.slug)}">${crest(t)}<span>${h(t.short || t.name)}</span></a>`;

function rgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function lum(c) { return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255; }
function dist(a, b) { return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]); }
function teamColors(home, away) {
  const usable = t => [t.color, t.alt_color].map(rgb).filter(c => c && lum(c) > 0.05 && lum(c) < 0.86);
  const hc = usable(home)[0] || [29, 106, 78];
  const ac = usable(away).find(c => dist(c, hc) > 90) || (dist([90, 104, 110], hc) > 90 ? [90, 104, 110] : [180, 120, 30]);
  return [`rgb(${hc})`, `rgb(${ac})`];
}

function strip(home, away, g, big = true) {
  const [hc, ac] = teamColors(home, away);
  const bar = `<span style="flex-basis:${g.home_win * 100}%;background:${hc}"></span><span class="d" style="flex-basis:${g.draw * 100}%"></span><span style="flex-basis:${g.away_win * 100}%;background:${ac}"></span>`;
  if (!big) return `<div class="mini" aria-hidden="true">${bar}</div>`;
  return `<div class="strip">
    <div class="strip-bar" role="img" aria-label="${h(home.name)} win ${pct(g.home_win)}, draw ${pct(g.draw)}, ${h(away.name)} win ${pct(g.away_win)}">${bar}</div>
    <div class="strip-legend">
      <div><div class="p">${pct(g.home_win)}</div><div class="who">${h(home.short || home.name)} win</div></div>
      <div><div class="p">${pct(g.draw)}</div><div class="who">Draw</div></div>
      <div><div class="p">${pct(g.away_win)}</div><div class="who">${h(away.short || away.name)} win</div></div>
    </div></div>`;
}

function setNav(key) {
  document.querySelectorAll("[data-nav]").forEach(a => { if (a.dataset.nav !== key) a.removeAttribute("aria-current"); else a.setAttribute("aria-current", "page"); });
}
function title(t) { document.title = t ? `${t} — Matchday Numbers` : "Matchday Numbers"; }

function leagueTabs(active, prefix = "#/league/") {
  return `<nav class="tabs" aria-label="Competition">${Object.entries(LEAGUES).map(([k, v]) =>
    `<a class="tab" href="${prefix}${k}" aria-current="${k === active}">${h(v)}</a>`).join("")}</nav>`;
}

/* ---------------------------------------------------------------- league / home */
function fixtureRow(u) {
  const p = u.prediction;
  const right = p
    ? `<div class="fx-pred">${strip(u.home, u.away, p, false)}
         <div class="tri"><b>${pct(p.home_win)}</b><b>${pct(p.draw)}</b><b>${pct(p.away_win)}</b></div>
         <div>${fx(p.goals)} goals, ${fx(p.corners)} corners, ${fx(p.cards)} cards expected</div></div>`
    : `<div class="fx-pred">${u.comp === "champions-league" ? "Stats only" : "Prediction soon"}</div>`;
  return `<li><a class="row" href="#/match/${h(u.id)}">
    <div class="fx-when">${h(day(u.kickoff))}<br>${h(time(u.kickoff))}</div>
    <div class="fx-teams"><div class="fx-team">${crest(u.home)}${h(u.home.name)}</div><div class="fx-team">${crest(u.away)}${h(u.away.name)}</div></div>
    ${right}</a></li>`;
}
function resultRow(r) {
  const [a, b] = r.score;
  return `<li><a class="row" href="#/match/${h(r.id)}">
    <div class="fx-when">${h(day(r.kickoff || r.date))}</div>
    <div class="fx-teams"><div class="fx-team">${crest(r.home)}${h(r.home.name)}<span class="g">${a}</span></div>
    <div class="fx-team">${crest(r.away)}${h(r.away.name)}<span class="g">${b}</span></div></div>
    <div class="fx-pred">${r.has_prediction ? "Prediction vs result" : ""}</div></a></li>`;
}
function tableHtml(rows, highlight) {
  return `<div class="tscroll"><table><thead><tr><th class="n">#</th><th>Team</th><th class="n">P</th><th class="n">W</th><th class="n">D</th><th class="n">L</th><th class="n">GF</th><th class="n">GA</th><th class="n">GD</th><th class="n">Pts</th></tr></thead><tbody>
  ${rows.map(r => `<tr class="${r.team.slug === highlight ? "me" : ""}"><td class="n">${r.pos}</td><td>${tlink(r.team)}</td><td class="n">${r.p}</td><td class="n">${r.w}</td><td class="n">${r.d}</td><td class="n">${r.l}</td><td class="n">${r.gf}</td><td class="n">${r.ga}</td><td class="n">${r.gd > 0 ? "+" : ""}${r.gd}</td><td class="n">${r.pts}</td></tr>`).join("")}
  </tbody></table></div>`;
}

async function renderLeague(lg) {
  try { localStorage.setItem("league", lg); } catch (e) { /* private mode */ }
  const L = await get(`league-${lg}.json`);
  title(L.name);
  setNav("home");
  const week = L.upcoming.slice(0, 20);
  app.innerHTML = `
    ${leagueTabs(lg)}
    <h1>${h(L.name)}</h1>
    <p class="sub">${L.matches_played} matches played this season${L.cross_check ? `. ${L.cross_check.verified} checked against both sources` : ""}.</p>
    ${L.predictions_available ? BANNER : `<p class="note">Champions League: full match stats and results. Predictions are left out for now, because teams from different leagues can't be compared reliably yet.</p>`}
    <h2>Next matches</h2>
    ${week.length ? `<ul class="fixtures">${week.map(fixtureRow).join("")}</ul>` : `<p class="empty">No matches scheduled in the next 10 days.</p>`}
    <h2>Latest results</h2>
    ${L.recent.length ? `<ul class="fixtures">${L.recent.slice(0, 12).map(resultRow).join("")}</ul>` : `<p class="empty">No results yet.</p>`}
    <h2>${lg === "champions-league" ? "League phase table" : "Table"}</h2>
    ${tableHtml(L.table)}`;
}

/* ---------------------------------------------------------------- match */
function lineList(stat, s, result) {
  const res = result && result[stat];
  return `<ul class="lines">${Object.entries(s.over).map(([line, p]) => {
    const r = res && !res.excluded ? res.lines[line] : null;
    const cls = r ? (r.hit ? "hit" : "miss") : "";
    return `<li class="${cls}"><span>Over ${h(line)}</span><span class="bar"><span style="width:${p * 100}%"></span></span><span class="pct">${pct(p)}</span></li>`;
  }).join("")}</ul>`;
}

function accuracyLine(acc, lg, stat) {
  const live = acc && acc.live && acc.live.by_league && acc.live.by_league[lg] && acc.live.by_league[lg][stat];
  if (live && live.n >= 10) {
    const lines = Object.entries(live.lines).map(([l, d]) => `over ${l}: ${pct(d.hit_rate)}`).join(", ");
    return `Track record (${live.n} matches, frozen before kick-off): average miss ${fx(live.mae, 1)} vs ${fx(live.baseline_mae, 1)} for league averages; calls right ${lines}.`;
  }
  const bt = acc && acc.backtest && acc.backtest.test && acc.backtest.test[stat];
  const bb = acc && acc.backtest && acc.backtest.baseline && acc.backtest.baseline[stat];
  if (bt) {
    const lines = Object.entries(bt.lines).map(([l, d]) => `over ${l}: ${pct(d.hit_rate)}`).join(", ");
    return `Not enough live results yet. In testing on the 2025-26 season: average miss ${fx(bt.mae, 2)} vs ${fx(bb.mae, 2)} for league averages; calls right ${lines}.`;
  }
  return "";
}

function statPanel(stat, P, m, acc) {
  const s = P.stats[stat];
  const res = m.prediction && m.prediction.result && m.prediction.result[stat];
  const actual = res && !res.excluded ? `<span class="range">Actual: <b>${res.actual_total}</b></span>` : "";
  let extra = "";
  if (stat === "goals") {
    extra = `<p class="small" style="margin-top:10px">Both teams score: <b>${pct(s.btts)}</b>. Clean sheet: ${h(m.home.short)} ${pct(s.clean_sheet_home)}, ${h(m.away.short)} ${pct(s.clean_sheet_away)}.<br>
      Most likely scores: ${s.likely_scores.map(x => `<span class="nw">${h(x.score.replace("-", "–"))} (${pct(x.p)})</span>`).join(", ")}</p>`;
  }
  return `<section class="panel">
    <h3>${STAT[stat]} <span class="sub">${STAT_HELP[stat]}</span></h3>
    <div class="stat-row"><span class="stat-big">${fx(s.total)}</span><span class="range">likely ${s.range[0]}–${s.range[1]}</span>${actual}</div>
    <p class="small sub" style="margin:4px 0 0">${h(m.home.short)} ${fx(s.home)}, ${h(m.away.short)} ${fx(s.away)}</p>
    ${lineList(stat, s, m.prediction && m.prediction.result)}
    ${extra}
    <details><summary>Why</summary><ul class="why">${(s.why || []).map(w => `<li>${h(w)}</li>`).join("")}</ul>
    <p class="small sub" style="margin-top:8px">${h(accuracyLine(acc, m.comp, stat))}</p></details>
  </section>`;
}

function predictionCard(m, acc) {
  const pr = m.prediction;
  const P = pr.prediction;
  const conf = P.confidence;
  const adjs = P.adjustments || [];
  const statusLabel = { measured: "applied", provisional: "applied, provisional", info: "context only" };
  const miss = pr.missing || pr.suspended || {};
  const doubt = pr.doubtful || {};
  const tag = side => x => ({ ...x, team: side === "home" ? m.home.short : m.away.short });
  const susp = [...(miss.home || []).map(tag("home")), ...(miss.away || []).map(tag("away"))];
  const dbt = [...(doubt.home || []).map(tag("home")), ...(doubt.away || []).map(tag("away"))];
  return `
    ${strip(m.home, m.away, P.stats.goals)}
    <p class="meta"><span class="pill ${h(conf.level)}">${h(conf.level)} confidence</span>
      ${conf.reasons.length ? ` ${h(conf.reasons.join("; "))}.` : ""}
      Based on ${P.sample.home_games} and ${P.sample.away_games} league games this season${P.sample.home_games < 10 || P.sample.away_games < 10 ? ", blended with last season" : ""}.
      ${m.status === "upcoming" ? `Updated ${h(ago(pr.made_at))}; frozen at kick-off.` : `Frozen before kick-off (last update ${h(kick(pr.made_at))}).`}</p>
    <h2>Expected numbers</h2>
    <div class="grid">${["goals", "corners", "cards", "shots", "shots_on_target"].map(s => statPanel(s, P, m, acc)).join("")}</div>
    <h2>Adjustments</h2>
    <p class="sub">Each change to the statistical base is listed with its effect. Provisional sizes are not yet calibrated on data.</p>
    ${adjs.length ? `<ul class="adj">${adjs.map(a => `<li><span class="eff">${a.effect_pct > 0 ? "+" : ""}${fx(a.effect_pct, 1)}%</span><span>${h(STAT[a.stat] || a.stat)}, ${h(a.side === "both" ? "both teams" : a.side === "home" ? m.home.short : m.away.short)}: ${h(a.detail)}</span><span class="pill ${h(a.status)}" title="${a.status === "info" ? "Shown for context; not used in the numbers" : a.status === "provisional" ? "Used in the numbers; size not yet calibrated on data" : "Used in the numbers; size measured on past seasons"}">${h(statusLabel[a.status] || a.status)}</span></li>`).join("")}</ul>` : `<p class="empty">No adjustments for this match.</p>`}
    <h2>Missing players</h2>
    ${susp.length || dbt.length ? `<ul class="adj">${susp.map(x => `<li><span class="eff">${h(x.team)}</span><span>${h(x.name)}: ${h(x.reason)}</span><span class="pill provisional" title="Counted in the numbers">out</span></li>`).join("")}${dbt.map(x => `<li><span class="eff">${h(x.team)}</span><span>${h(x.name)}: ${h(x.reason)}</span><span class="pill info" title="Not counted in the numbers">may play</span></li>`).join("")}</ul>` : `<p class="empty">${pr.team_news ? "No injuries or suspensions reported." : "No team news yet."}</p>`}
    <p class="note">${pr.team_news ? "Team news comes from FotMob in the last 4 days before kick-off and is refreshed every 3 hours. It can still change before the match." : "Team news appears 4 days before kick-off. Until then, only suspensions worked out from cards are counted, and they may miss appeals or cup bans."}</p>
    ${(P.analyst_view || []).length ? `<h2>Analyst view</h2><div class="panel">${P.analyst_view.map(x => `<p>${h(x)}</p>`).join("")}<p class="sub small">Opinion, not part of the numbers above.</p></div>` : ""}`;
}

function matchHead(m) {
  const mid = m.status === "finished"
    ? `<div class="score">${m.score[0]}–${m.score[1]}</div>`
    : `<div class="vs">${h(day(m.kickoff))}<br><b>${h(time(m.kickoff))}</b></div>`;
  return `<div class="mhead">
    <div class="mteam">${crest(m.home, "")}<a href="#/team/${h(m.home.slug)}">${h(m.home.name)}</a></div>
    ${mid}
    <div class="mteam away">${crest(m.away, "")}<a href="#/team/${h(m.away.slug)}">${h(m.away.name)}</a></div></div>
    <p class="meta">${h(LEAGUES[m.comp])}${m.round ? `, ${h(m.round)}` : ""}${m.status === "finished" ? `, ${h(kick(m.kickoff || m.date))}` : ""}${m.venue ? `. ${h(m.venue)}` : ""}${m.referee ? `. Referee: ${h(m.referee)}` : ""}</p>`;
}

function cmpRow(label, a, b, colors, check, conflict) {
  if (a == null && b == null) return "";
  const tot = (a || 0) + (b || 0) || 1;
  const flag = check === "conflict"
    ? ` <span class="pill conflict" title="${h(JSON.stringify(conflict || {}))}">sources disagree</span>`
    : check === "single" ? ` <span class="pill single">one source</span>` : check === "verified" ? ` <span class="pill">checked</span>` : "";
  return `<li><div class="lab"><span>${h(label)}${flag}</span></div>
    <span class="v">${a ?? "–"}</span>
    <span class="b"><span style="flex:${a || 0.0001};background:${colors[0]}"></span><span style="flex:${b || 0.0001};background:${colors[1]}"></span></span>
    <span class="v r">${b ?? "–"}</span></li>`;
}

async function renderMatch(id) {
  const [m, acc] = await Promise.all([get(`match/${id}.json`), get("accuracy.json").catch(() => null)]);
  title(`${m.home.short} v ${m.away.short}`);
  setNav("home");
  let body = matchHead(m);
  if (m.status === "upcoming") {
    body += m.prediction ? BANNER + predictionCard(m, acc) : `<p class="note">${h(m.note || "")}</p>`;
    app.innerHTML = body;
    return;
  }
  const colors = teamColors(m.home, m.away);
  const S = m.stats, C = m.checks || {};
  const conf = m.conflict_values || {};
  body += `<h2>Match stats</h2><ul class="cmp">
    ${cmpRow("Goals", S.goals[0], S.goals[1], colors, C.goals, conf.goals)}
    ${S.xg ? cmpRow("Expected goals (xG)", S.xg[0], S.xg[1], colors) : ""}
    ${cmpRow("Shots", S.shots[0], S.shots[1], colors, C.shots, conf.shots)}
    ${cmpRow("Shots on target", S.shots_on_target[0], S.shots_on_target[1], colors, C.sot, conf.sot)}
    ${cmpRow("Corners", S.corners[0], S.corners[1], colors, C.corners, conf.corners)}
    ${cmpRow("Yellow cards", S.yellow[0], S.yellow[1], colors, C.yellow, conf.yellow)}
    ${cmpRow("Red cards", S.red[0], S.red[1], colors, C.red, conf.red)}
    ${cmpRow("Fouls", S.fouls[0], S.fouls[1], colors)}
    ${cmpRow("Possession %", S.possession[0], S.possession[1], colors)}
  </ul>
  <p class="sub small">Sources: ${h((m.sources || []).join(" and "))}. "Checked" means both sources agree; when they disagree, the stat is left out of the model for this match${Object.keys(conf).length ? ": " + Object.entries(conf).map(([k, v]) => `${k} ${Object.entries(v).map(([s, x]) => `${s} ${x[0]}–${x[1]}`).join(" vs ")}`).join("; ") : ""}.</p>`;
  const events = [...(m.goals || []).map(g => ({ min: g.minute, html: `⚽ <b>${h(g.scorer || "Goal")}</b>${g.penalty ? " (pen)" : ""}${g.own_goal ? " (own goal)" : ""}${g.assist ? `, assist ${h(g.assist)}` : ""} <span class="sub">${h(g.team)}</span>` })),
    ...(m.cards || []).map(c => ({ min: c.minute, html: `${c.card === "red" ? "🟥" : "🟨"} ${h(c.player)} <span class="sub">${h(c.team)}</span>` }))]
    .sort((a, b) => (a.min ?? 0) - (b.min ?? 0));
  if (events.length) body += `<h2>Goals and cards</h2><ul class="timeline">${events.map(e => `<li><span class="min">${e.min ?? ""}'</span>${e.html}</li>`).join("")}</ul>`;
  if (m.prediction && m.prediction.result) {
    const P = m.prediction.prediction, R = m.prediction.result;
    const g = R.goals || {};
    body += `<h2>Prediction vs result</h2>
      <p>Before kick-off the model gave ${h(m.home.short)} ${pct(P.stats.goals.home_win)}, draw ${pct(P.stats.goals.draw)}, ${h(m.away.short)} ${pct(P.stats.goals.away_win)}.
      The actual result had a ${pct(g.p_outcome)} chance. ${g.pick_correct ? "The most likely outcome happened." : "The most likely outcome did not happen."}</p>
      <div class="tscroll"><table><thead><tr><th>Stat</th><th class="n">Expected</th><th class="n">Likely range</th><th class="n">Actual</th><th>Lines</th></tr></thead><tbody>
      ${Object.keys(STAT).map(s => {
        const r = R[s], p = P.stats[s];
        if (!r || r.excluded) return `<tr><td>${STAT[s]}</td><td class="n">${fx(p.total)}</td><td class="n">${p.range[0]}–${p.range[1]}</td><td class="n">–</td><td class="sub">left out (sources disagree or missing)</td></tr>`;
        return `<tr><td>${STAT[s]}</td><td class="n">${fx(p.total)}</td><td class="n">${p.range[0]}–${p.range[1]}</td><td class="n">${r.actual_total}</td><td>${Object.entries(r.lines).map(([l, d]) => `over ${l} ${pct(d.p_over)} ${d.hit ? "✓" : "✗"}`).join(", ")}</td></tr>`;
      }).join("")}</tbody></table></div>
      <details><summary>Full prediction card as it was frozen</summary>${predictionCard({ ...m, status: "finished" }, acc)}</details>`;
  } else if (m.comp !== "champions-league") {
    body += `<p class="note">No frozen prediction for this match: it was played before predictions started on this site.</p>`;
  }
  if (m.lineups && m.lineups.home) {
    const lu = side => {
      const L = m.lineups[side];
      const ps = (L.players || []).filter(p => p.minutes > 0).sort((a, b) => b.starter - a.starter || b.minutes - a.minutes);
      return `<div><h3>${h(m[side].short)} ${L.formation ? `<span class="sub">${h(L.formation)}</span>` : ""}</h3><table><thead><tr><th>Player</th><th class="n">Min</th><th class="n">G</th><th class="n">A</th></tr></thead><tbody>
        ${ps.map(p => `<tr><td>${h(p.name)}${p.starter ? "" : ' <span class="sub">(sub)</span>'}</td><td class="n">${p.minutes}</td><td class="n">${p.goals || ""}</td><td class="n">${p.assists || ""}</td></tr>`).join("")}</tbody></table></div>`;
    };
    body += `<h2>Lineups</h2><div class="lineups">${lu("home")}${lu("away")}</div>`;
  }
  app.innerHTML = body;
}

/* ---------------------------------------------------------------- team */
function formHtml(results) { return `<span class="form">${[...results].map(r => `<i class="${r}">${r}</i>`).join("")}</span>`; }

async function renderTeam(slug) {
  const t = await get(`team/${slug}.json`);
  title(t.name);
  setNav("teams");
  const A = t.averages, R = t.record;
  const rows = Object.keys(STAT).map(s => {
    const a = A[s];
    return `<tr><td>${STAT[s]}</td>${["overall", "home", "away"].map(v => `<td class="n">${fx(a[v].for)}</td><td class="n">${fx(a[v].against)}</td>`).join("")}</tr>`;
  }).join("");
  const rate = (k, v) => (R[v].p ? `${R[v][k]} (${pct(R[v][k] / R[v].p)})` : "–");
  const f5 = t.form.last5, f10 = t.form.last10;
  const formCmp = f10 ? `<table><thead><tr><th></th><th class="n">Last 5</th><th class="n">Last 10</th><th class="n">Season</th></tr></thead><tbody>
    <tr><td>Points per game</td><td class="n">${fx(f5.ppg, 2)}</td><td class="n">${fx(f10.ppg, 2)}</td><td class="n">${fx(R.overall.p ? (3 * R.overall.w + R.overall.d) / R.overall.p : null, 2)}</td></tr>
    ${Object.keys(STAT).map(s => `<tr><td>${STAT[s]} for / against</td><td class="n">${fx(f5.averages[s].for)} / ${fx(f5.averages[s].against)}</td><td class="n">${fx(f10.averages[s].for)} / ${fx(f10.averages[s].against)}</td><td class="n">${fx(A[s].overall.for)} / ${fx(A[s].overall.against)}</td></tr>`).join("")}
    </tbody></table>` : "";
  app.innerHTML = `
    <div class="teamhead">${crest(t, "")}<div><h1>${h(t.name)}</h1>
      <p class="meta">${h(LEAGUES[t.league])}: played ${R.overall.p}, won ${R.overall.w}, drew ${R.overall.d}, lost ${R.overall.l}</p></div></div>
    ${f10 ? `<p>Last 10 ${formHtml(f10.results)}</p>` : ""}
    ${t.upcoming.length ? `<h2>Next matches</h2><ul class="fixtures">${t.upcoming.map(fixtureRow).join("")}</ul>` : ""}
    <h2>Season averages per game</h2>
    <div class="tscroll"><table><thead><tr><th rowspan="2">Stat</th><th class="n" colspan="2">Overall</th><th class="n" colspan="2">Home</th><th class="n" colspan="2">Away</th></tr>
      <tr><th class="n">For</th><th class="n">Against</th><th class="n">For</th><th class="n">Against</th><th class="n">For</th><th class="n">Against</th></tr></thead>
      <tbody>${rows}
      <tr><td>Clean sheets</td><td class="n" colspan="2">${rate("clean_sheets", "overall")}</td><td class="n" colspan="2">${rate("clean_sheets", "home")}</td><td class="n" colspan="2">${rate("clean_sheets", "away")}</td></tr>
      <tr><td>Both teams scored</td><td class="n" colspan="2">${rate("btts", "overall")}</td><td class="n" colspan="2">${rate("btts", "home")}</td><td class="n" colspan="2">${rate("btts", "away")}</td></tr>
      <tr><td>Over 2.5 goals</td><td class="n" colspan="2">${rate("over25", "overall")}</td><td class="n" colspan="2">${rate("over25", "home")}</td><td class="n" colspan="2">${rate("over25", "away")}</td></tr>
      <tr><td>Won / drawn / lost</td><td class="n" colspan="2">${R.overall.w}/${R.overall.d}/${R.overall.l}</td><td class="n" colspan="2">${R.home.w}/${R.home.d}/${R.home.l}</td><td class="n" colspan="2">${R.away.w}/${R.away.d}/${R.away.l}</td></tr>
      </tbody></table></div>
    <p class="sub small">Cards count yellow and red cards the team received. League matches only.</p>
    ${formCmp ? `<h2>Form</h2><div class="tscroll">${formCmp}</div>` : ""}
    <h2>Goals and assists</h2>
    ${t.scorers.length ? `<div class="tscroll"><table><thead><tr><th>Player</th><th class="n">Goals</th><th class="n">Assists</th><th>Share of team goals</th><th class="n">Apps</th><th class="n">Min</th></tr></thead><tbody>
      ${t.scorers.map(p => `<tr><td>${h(p.name)}</td><td class="n">${p.goals}</td><td class="n">${p.assists}</td><td><span class="share"><span style="width:${Math.min(100, p.share_goals * 100)}%"></span></span>${pct(p.share_goals)} scored, ${pct(p.share_involvement)} involved</td><td class="n">${p.apps}</td><td class="n">${p.minutes}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="empty">No player data yet.</p>`}
    <h2>Game by game</h2>
    <div class="tscroll"><table><thead><tr><th>Date</th><th>Comp</th><th>Opponent</th><th class="n">H/A</th><th class="n">Score</th><th class="n">Corners</th><th class="n">Cards</th><th class="n">Shots</th><th class="n">On target</th></tr></thead><tbody>
      ${[...t.log].reverse().map(r => `<tr><td><a href="#/match/${h(r.id)}">${h(day(r.kickoff || r.date))}</a></td><td class="sub">${r.comp === "champions-league" ? "UCL" : "League"}</td><td>${tlink(r.opp)}</td><td class="n">${r.venue}</td>
        <td class="n"><span class="form"><i class="${r.result}">${r.result}</i></span> ${r.goals[0]}–${r.goals[1]}</td>
        ${["corners", "cards", "shots", "shots_on_target"].map(s => `<td class="n">${r[s][0] ?? "–"}–${r[s][1] ?? "–"}</td>`).join("")}</tr>`).join("")}
    </tbody></table></div>
    <p class="sub small">Each pair is for–against.</p>`;
}

async function renderTeams() {
  const teams = await get("teams.json");
  title("Teams");
  setNav("teams");
  const groups = Object.keys(LEAGUES).map(k => [k, teams.filter(t => t.league === k)]);
  const draw = q => groups.map(([k, ts]) => {
    const f = ts.filter(t => t.name.toLowerCase().includes(q));
    return f.length ? `<h2>${h(LEAGUES[k])}${k === "champions-league" ? " (other clubs)" : ""}</h2><ul class="teamgrid">${f.map(t => `<li><a href="#/team/${h(t.slug)}">${crest(t)}${h(t.name)}</a></li>`).join("")}</ul>` : "";
  }).join("") || `<p class="empty">No team matches that name.</p>`;
  app.innerHTML = `<h1>Teams</h1><p class="sub">Season averages, form, scorers and every game.</p>
    <label class="sub small" for="q">Find a team</label><br><input id="q" class="search" type="search" placeholder="Real Madrid, Arsenal…" autocomplete="off"><div id="tl">${draw("")}</div>`;
  const q = document.getElementById("q");
  q.addEventListener("input", () => { document.getElementById("tl").innerHTML = draw(q.value.trim().toLowerCase()); });
}

/* ---------------------------------------------------------------- accuracy */
function calibSvg(bins) {
  const pts = bins.filter(b => b.n >= 20);
  const W = 320, H = 300, pad = 40, R = 22;
  const x = v => pad + v * (W - pad - R), y = v => H - pad - v * (H - pad - 12);
  return `<svg class="calib" viewBox="0 0 ${W} ${H}" role="img" aria-label="Calibration: predicted probability against how often it happened">
    <line x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(1)}" stroke="var(--line)" stroke-width="2" stroke-dasharray="4 4"/>
    <line x1="${x(0)}" y1="${y(0)}" x2="${x(1)}" y2="${y(0)}" stroke="var(--muted)"/><line x1="${x(0)}" y1="${y(0)}" x2="${x(0)}" y2="${y(1)}" stroke="var(--muted)"/>
    ${[0, 0.25, 0.5, 0.75, 1].map(v => `<text x="${x(v)}" y="${H - 14}" text-anchor="middle">${v * 100}%</text><text x="${pad - 6}" y="${y(v) + 4}" text-anchor="end">${v * 100}%</text>`).join("")}
    <polyline fill="none" stroke="var(--pitch)" stroke-width="2.5" points="${pts.map(b => `${x(b.avg_predicted)},${y(b.actual)}`).join(" ")}"/>
    ${pts.map(b => `<circle cx="${x(b.avg_predicted)}" cy="${y(b.actual)}" r="${3 + Math.min(5, Math.sqrt(b.n) / 8)}" fill="var(--pitch)"><title>Predicted ${pct(b.avg_predicted)}, happened ${pct(b.actual)} (${b.n} predictions)</title></circle>`).join("")}
  </svg>`;
}
function statTable(rows, base) {
  return `<div class="tscroll"><table><thead><tr><th>Stat</th><th class="n">Avg miss</th><th class="n">League avg miss</th><th>Line: calls right (Brier, lower is better; league average in brackets)</th></tr></thead><tbody>
    ${Object.keys(STAT).filter(s => rows[s]).map(s => {
      const r = rows[s], b = base ? base[s] : null;
      return `<tr><td>${STAT[s]}</td><td class="n">${fx(r.mae, 2)}</td><td class="n">${b ? fx(b.mae, 2) : fx(r.baseline_mae, 2)}</td>
        <td>${Object.entries(r.lines).map(([l, d]) => `over ${l}: ${pct(d.hit_rate)} (${fx(d.brier, 3)} vs ${fx(b ? b.lines[l].brier : d.baseline_brier, 3)})`).join("<br>")}</td></tr>`;
    }).join("")}</tbody></table></div>`;
}

async function renderAccuracy() {
  const acc = await get("accuracy.json");
  title("Track record");
  setNav("accuracy");
  const live = acc.live, bt = acc.backtest;
  let html = `<h1>Track record</h1>
    <p>Every prediction is frozen at kick-off and compared with what happened, misses included. "Avg miss" is how far the expected total was from the real one. A good model should beat the plain league average, and its 70% calls should come true about 70% of the time.</p>`;
  if (!live.matches) {
    html += `<h2>Live predictions</h2><p class="empty">No predictions have been scored yet. The first ones are frozen at kick-off of the next league matches and appear here after the final whistle.</p>`;
  } else {
    html += `<h2>Live predictions: ${live.matches} matches</h2>`;
    const all = live.by_league.all;
    if (all.goals) html += `<p>Most likely result (win/draw/loss) came true in <b>${pct(all.goals.pick_rate)}</b> of matches. Brier score ${fx(all.goals.brier_1x2, 3)} vs ${fx(all.goals.baseline_brier_1x2, 3)} for league averages (lower is better). Exact score right: ${pct(all.goals.score_rate)}.</p>`;
    for (const lg of ["all", "la-liga", "premier-league"]) {
      if (live.by_league[lg]) html += `<h3 style="margin-top:20px">${lg === "all" ? "Both leagues" : h(LEAGUES[lg])}</h3>${statTable(live.by_league[lg])}`;
    }
    html += `<h3 style="margin-top:20px">Calibration</h3>${calibSvg(live.calibration)}<p class="sub small">Dots on the dashed line mean the probabilities are honest. Only groups with 20+ predictions are drawn.</p>`;
    html += `<h3 style="margin-top:20px">Latest scored predictions</h3><ul class="fixtures">${acc.recent.slice(0, 20).map(r => `<li><a class="row" href="#/match/${h(r.id)}">
      <div class="fx-when">${h(day(r.kickoff))}</div>
      <div class="fx-teams"><div class="fx-team">${crest(r.home)}${h(r.home.name)}<span class="g">${r.score ? r.score[0] : ""}</span></div><div class="fx-team">${crest(r.away)}${h(r.away.name)}<span class="g">${r.score ? r.score[1] : ""}</span></div></div>
      <div class="fx-pred">${r.pick_correct ? "Most likely result ✓" : "Most likely result ✗"}<br>Goals ${fx(r.goals[0])} vs ${r.goals[1] ?? "–"}, corners ${fx(r.corners[0])} vs ${r.corners[1] ?? "–"}</div></a></li>`).join("")}</ul>`;
  }
  if (bt && bt.test) {
    const g = bt.test.goals, gb = bt.baseline.goals;
    html += `<h2>Testing on last season</h2>
      <p>Before going live, the model was tuned on the 2023-24 and 2024-25 seasons, then run once over all ${bt.matches} Premier League and La Liga matches of 2025-26, each predicted using only games played before it. This is a test, not a live record.</p>
      <p>Win/draw/loss Brier score ${fx(g.brier, 3)} vs ${fx(gb.brier, 3)} for league averages.</p>
      ${statTable(bt.test, bt.baseline)}
      <h3 style="margin-top:20px">Calibration in testing</h3>${calibSvg(bt.calibration)}
      <p class="sub small">Momentum and referee adjustments didn't improve accuracy in testing, so they're shown on cards for context but not applied. Derby matches had ${fx((bt.tuning.derby_cards - 1) * 100, 0)}% more cards than expected, so that adjustment is applied.</p>`;
  }
  app.innerHTML = html;
}

/* ---------------------------------------------------------------- about */
function renderAbout() {
  title("How it works");
  setNav("about");
  app.innerHTML = `<div class="prose"><h1>How it works</h1>
  <p>Matchday Numbers shows past statistics and statistical estimates for upcoming La Liga and Premier League matches, plus full stats for the Champions League. It is an information tool: every estimate shows its inputs, its uncertainty and its track record, so you can decide how much to trust it.</p>
  <h2>Where the data comes from</h2>
  <ul><li><b>football-data.co.uk</b>: results, shots, corners and cards for both leagues, and referees for the Premier League.</li>
  <li><b>ESPN</b>: fixtures, kick-off times, Champions League matches, lineups, goals, assists and minutes.</li>
  <li><b>FotMob</b>: team news (injured and suspended players) for the next few days' matches.</li></ul>
  <p>The ESPN and FotMob feeds are public but unofficial, so they can change without notice. If one breaks, the site keeps the last good data and says so.</p>
  <p>Where both sources cover a match, they are compared stat by stat. If they disagree by more than a corner or card (two shots), that stat is shown with both values and left out of the model for that match. Data refreshes every three hours.</p>
  <h2>The model, in plain words</h2>
  <ol><li><b>Statistical base.</b> For each stat, start from the league average for home or away teams, then multiply by the home side's attacking strength and the away side's defensive weakness (and the other way round). Strengths compare a team with the league average; the last 6 games count double. Early in the season, or with few games, numbers are pulled toward last season's level (or a typical promoted team's). Goals also borrow from shots on target, which measure the same thing with less luck.</li>
  <li><b>Adjustments</b>, each listed on the card with its effect: derby matches (more cards, measured on past seasons), missing players (provisional: a team's expected goals drop by 40% of the missing player's share of its goals and assists, and a missing regular keeper or defender adds 3% to the opponent), and short rest (provisional). Momentum and referee history are shown for context only, because they didn't improve accuracy in testing.</li>
  <li><b>Probabilities.</b> Goals use a Dixon-Coles model to get win/draw/loss, likely scores and over/under chances. Corners, cards and shots use a negative binomial distribution, which allows for more spread than a simple average suggests.</li></ol>
  <p>Confidence is Low, Medium or High depending on how many games the numbers rest on and how much the adjustments moved them.</p>
  <h2>What it can't do</h2>
  <ul><li>Team news is only as good as FotMob's reports, and doubtful players aren't counted.</li>
  <li>Champions League predictions are left out: teams from different leagues can't be compared reliably yet.</li>
  <li>Corners and cards are hard to predict for anyone. The model beats league averages on them, but only slightly.</li>
  <li>Analyst views (new manager, motivation) are kept in a separate box and never mixed into the numbers.</li></ul>
  <p>Every prediction is saved in the project's public history before kick-off, so the track record can't be edited after the fact.</p></div>`;
}

/* ---------------------------------------------------------------- router */
async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/");
  try {
    if (parts[0] === "match" && parts[1]) await renderMatch(parts[1]);
    else if (parts[0] === "team" && parts[1]) await renderTeam(parts[1]);
    else if (parts[0] === "teams") await renderTeams();
    else if (parts[0] === "accuracy") await renderAccuracy();
    else if (parts[0] === "about") renderAbout();
    else {
      let lg = parts[0] === "league" && LEAGUES[parts[1]] ? parts[1] : null;
      if (!lg) { try { lg = localStorage.getItem("league"); } catch (e) { lg = null; } }
      await renderLeague(LEAGUES[lg] ? lg : "la-liga");
    }
  } catch (e) {
    app.innerHTML = `<h1>Not found</h1><p>This page doesn't exist or its data hasn't been published yet. <a href="#/">Go to matches</a>.</p><p class="sub small">${h(e.message)}</p>`;
  }
  window.scrollTo(0, 0);
  app.focus({ preventScroll: true });
}

async function boot() {
  try {
    const meta = await fetch(`data/meta.json?t=${Date.now()}`, { cache: "no-store" }).then(r => r.json());
    version = meta.updated_at;
    const fd = meta.sources.football_data_last_match || {};
    document.getElementById("freshness").textContent =
      `Data last updated ${kick(meta.updated_at)} (your time). Refreshed every 3 hours. ` +
      `Latest football-data.co.uk match: ${Object.entries(fd).map(([k, v]) => `${LEAGUES[k]} ${v ? day(v) : "none"}`).join(", ")}.`;
  } catch (e) {
    document.getElementById("freshness").textContent = "Data freshness unknown.";
  }
  window.addEventListener("hashchange", route);
  route();
}
boot();
