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
const sgn = (x, d = 1) => (x == null ? "–" : `${x > 0 ? "+" : ""}${Number(x).toFixed(d)}`);
const kickFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const dayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
const longDayFmt = new Intl.DateTimeFormat("en-GB", { weekday: "long", day: "numeric", month: "long" });
const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });
const asDate = iso => new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso);
const kick = iso => (iso ? kickFmt.format(asDate(iso)) : "");
const day = iso => (iso ? dayFmt.format(asDate(iso)) : "");
const longDay = iso => (iso ? longDayFmt.format(asDate(iso)) : "");
const time = iso => (iso ? timeFmt.format(asDate(iso)) : "");
function ago(iso) {
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  if (m < 60) return `${Math.max(m, 1)} min ago`;
  if (m < 48 * 60) return `${Math.round(m / 60)} h ago`;
  return day(iso);
}
function disc(t, size = "sm") {
  const ini = h(((t && (t.abbr || t.short || t.name)) || "?").slice(0, 3));
  return t && t.logo
    ? `<span class="disc ${size}"><img src="${h(t.logo)}" alt="" loading="lazy" onerror="this.replaceWith(document.createTextNode('${ini}'))"></span>`
    : `<span class="disc ${size}" style="font-size:.7rem;font-weight:800;color:#13201c">${ini}</span>`;
}
const tlink = t => `<a class="tlink" href="#/team/${h(t.slug)}">${disc(t, "xs")}<span>${h(t.short || t.name)}</span></a>`;

/* colours: clubs' own colours, kept readable */
function rgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const lum = c => (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255;
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const css = c => `rgb(${c.map(Math.round).join(",")})`;
function pick(t, avoid) {
  const cands = [t && t.color, t && t.alt_color].map(rgb).filter(c => c && lum(c) > 0.05 && lum(c) < 0.86);
  return cands.find(c => !avoid || dist(c, avoid) > 90) || null;
}
function teamColors(home, away) {
  const hc = pick(home) || [27, 106, 76];
  const ac = pick(away, hc) || (dist([84, 102, 110], hc) > 90 ? [84, 102, 110] : [176, 120, 32]);
  return [hc, ac];
}
function deep(c) { // darken until white text is comfortable on it
  let x = c.slice();
  while (lum(x) > 0.3) x = x.map(v => v * 0.85);
  return x;
}

function strip(home, away, g, big = true) {
  const [hc, ac] = teamColors(home, away);
  const bar = `<span style="flex:${g.home_win};background:${css(hc)}"></span><span class="d" style="flex:${g.draw}"></span><span style="flex:${g.away_win};background:${css(ac)}"></span>`;
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
  document.querySelectorAll("[data-nav]").forEach(a => {
    if (a.dataset.nav === key) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
}
function title(t) { document.title = t ? `${t} — Matchday Numbers` : "Matchday Numbers"; }
const wrap = html => `<div class="wrap">${html}</div>`;

/* ---------------------------------------------------------------- league */
function fixtureCard(u) {
  const p = u.prediction;
  const [hc, ac] = teamColors(u.home, u.away);
  const lead = p ? (p.home_win >= p.away_win ? "h" : "a") : null;
  const body = p
    ? `<div class="fc-team">${disc(u.home)}<span class="nm">${h(u.home.name)}</span><span class="pp ${lead === "h" ? "lead" : ""}">${pct(p.home_win)}</span></div>
       <div class="fc-draw"><span>Draw</span><span>${pct(p.draw)}</span></div>
       <div class="fc-team">${disc(u.away)}<span class="nm">${h(u.away.name)}</span><span class="pp ${lead === "a" ? "lead" : ""}">${pct(p.away_win)}</span></div>
       ${strip(u.home, u.away, p, false)}
       <div class="fc-exp"><div><b>${fx(p.goals)}</b>goals</div><div><b>${fx(p.corners)}</b>corners</div><div><b>${fx(p.cards)}</b>cards</div></div>`
    : `<div class="fc-team">${disc(u.home)}<span class="nm">${h(u.home.name)}</span><span></span></div>
       <div class="fc-team">${disc(u.away)}<span class="nm">${h(u.away.name)}</span><span></span></div>
       <p class="fc-none">${u.comp === "champions-league" ? "Stats only for this competition" : "Estimate appears closer to kick-off"}</p>`;
  return `<a class="fcard" style="--hc:${css(hc)};--ac:${css(ac)}" href="#/match/${h(u.id)}">
    <div class="fc-top"><span>${h(time(u.kickoff))}${u.round ? `, ${h(u.round)}` : ""}</span>${p ? `<span class="pill ${h(p.confidence)}">${h(p.confidence)} confidence</span>` : ""}</div>
    ${body}</a>`;
}
function fixtureGroups(list) {
  const groups = {};
  list.forEach(u => { const k = longDay(u.kickoff); (groups[k] = groups[k] || []).push(u); });
  return Object.entries(groups).map(([k, us]) => `<div class="day">${h(k)}</div><div class="cards">${us.map(fixtureCard).join("")}</div>`).join("");
}
function resultItem(r) {
  const [a, b] = r.score;
  return `<li><a href="#/match/${h(r.id)}">
    <span class="r-when">${h(day(r.kickoff || r.date))}${r.has_prediction ? `<br><span class="tag">vs estimate</span>` : ""}</span>
    <span><span class="r-t ${a > b ? "w" : a < b ? "l" : ""}">${disc(r.home, "xs")}${h(r.home.name)}</span><span class="r-t ${b > a ? "w" : b < a ? "l" : ""}">${disc(r.away, "xs")}${h(r.away.name)}</span></span>
    <span class="r-s">${a}<br>${b}</span></a></li>`;
}
function formDots(s, cls = "sm") { return `<span class="form ${cls}">${[...(s || "")].map(r => `<i class="${r}" title="${r === "W" ? "Win" : r === "D" ? "Draw" : "Loss"}">${r}</i>`).join("")}</span>`; }
function tableHtml(rows, lg) {
  const n = rows.length;
  const zone = r => (lg !== "champions-league" && r.pos <= 4 ? "z-top" : lg !== "champions-league" && r.pos > n - 3 ? "z-bot" : lg === "champions-league" && r.pos <= 8 ? "z-top" : "");
  return `<div class="tscroll"><table><thead><tr><th class="n">#</th><th>Team</th><th class="n">P</th><th class="n">W</th><th class="n">D</th><th class="n">L</th><th class="n">GD</th><th class="n">Pts</th><th>Last 5</th></tr></thead><tbody>
  ${rows.map(r => `<tr class="${zone(r)}"><td class="n pos">${r.pos}</td><td>${tlink(r.team)}</td><td class="n">${r.p}</td><td class="n">${r.w}</td><td class="n">${r.d}</td><td class="n">${r.l}</td><td class="n">${r.gd > 0 ? "+" : ""}${r.gd}</td><td class="n pts">${r.pts}</td><td>${formDots(r.form)}</td></tr>`).join("")}
  </tbody></table></div>
  <div class="legend">${lg === "champions-league"
    ? `<span><i style="background:var(--pitch)"></i>Top 8 go straight to the last 16</span>`
    : `<span><i style="background:var(--pitch)"></i>Champions League places</span><span><i style="background:var(--red)"></i>Relegation</span>`}</div>`;
}

async function renderLeague(lg) {
  try { localStorage.setItem("league", lg); } catch (e) { /* private mode */ }
  const L = await get(`league-${lg}.json`);
  title(L.name);
  setNav("home");
  const goals = L.table.reduce((s, r) => s + r.gf, 0);
  const games = L.table.reduce((s, r) => s + r.p, 0) / 2;
  const feat = L.upcoming.find(u => u.prediction);
  const featured = feat ? `<a class="feature grow" href="#/match/${h(feat.id)}">
      <div class="feature-top"><span>Next up, ${h(kick(feat.kickoff))}</span><span>${h(feat.venue || "")}</span></div>
      <div class="feature-teams"><span class="t">${disc(feat.home, "md")}<span>${h(feat.home.name)}</span></span><span class="x">v</span><span class="t a"><span>${h(feat.away.name)}</span>${disc(feat.away, "md")}</span></div>
      ${strip(feat.home, feat.away, feat.prediction)}
    </a>` : "";
  const rest = L.upcoming.filter(u => !feat || u.id !== feat.id).slice(0, 19);
  app.innerHTML = `
    <section class="hero turf"><div class="wrap">
      <nav class="tabs" aria-label="Competition">${Object.entries(LEAGUES).map(([k, v]) => `<a class="tab" href="#/league/${k}" aria-current="${k === lg}">${h(v)}</a>`).join("")}</nav>
      <h1>${h(L.name)}</h1>
      <div class="hero-meta"><span><b>${L.matches_played}</b>matches played</span><span><b>${games ? fx(goals / games, 2) : "–"}</b>goals a game</span>${L.cross_check ? `<span><b>${L.cross_check.verified}</b>checked against two sources</span>` : ""}</div>
      ${featured}
    </div></section>
    ${wrap(`
      ${L.predictions_available ? BANNER : `<p class="note">Champions League: full match stats and results. Estimates are left out for now, because teams from different leagues can't be compared reliably yet.</p>`}
      <section class="section"><h2>Next matches</h2>
      ${rest.length ? fixtureGroups(rest) : `<p class="empty">No other matches scheduled in the next 10 days.</p>`}</section>
      <section class="section"><h2>Latest results</h2>
      ${L.recent.length ? `<ul class="results">${L.recent.slice(0, 12).map(resultItem).join("")}</ul>` : `<p class="empty">No results yet.</p>`}</section>
      <section class="section"><h2>${lg === "champions-league" ? "League phase table" : "Table"}</h2>${tableHtml(L.table, lg)}</section>`)}`;
}

/* ---------------------------------------------------------------- match */
function lineList(stat, s, result) {
  const res = result && result[stat];
  return `<ul class="lines">${Object.entries(s.over).map(([line, p]) => {
    const r = res && !res.excluded ? res.lines[line] : null;
    return `<li class="${r ? (r.hit ? "hit" : "miss") : ""}"><span>Over ${h(line)}</span><span class="bar"><span style="width:${p * 100}%"></span></span><span class="pct">${pct(p)}</span></li>`;
  }).join("")}</ul>`;
}
function accuracyLine(acc, lg, stat) {
  const live = acc && acc.live && acc.live.by_league && acc.live.by_league[lg] && acc.live.by_league[lg][stat];
  if (live && live.n >= 10) {
    return `Track record (${live.n} matches, frozen before kick-off): average miss ${fx(live.mae, 1)}, league averages miss by ${fx(live.baseline_mae, 1)}.`;
  }
  const bt = acc && acc.backtest && acc.backtest.test && acc.backtest.test[stat];
  const bb = acc && acc.backtest && acc.backtest.baseline && acc.backtest.baseline[stat];
  if (bt) return `No live results yet. Tested on 2025-26: average miss ${fx(bt.mae, 2)}, league averages miss by ${fx(bb.mae, 2)}.`;
  return "";
}
function statPanel(stat, P, m, acc) {
  const s = P.stats[stat];
  const res = m.prediction && m.prediction.result && m.prediction.result[stat];
  const actual = res && !res.excluded ? `<span class="actual">Actual ${res.actual_total}</span>` : "";
  const head = `<h3>${STAT[stat]} <span class="sub">${STAT_HELP[stat]}</span></h3>
    <div class="stat-row"><span class="stat-big">${fx(s.total)}</span><span class="range">likely ${s.range[0]}–${s.range[1]}</span>${actual}</div>
    <p class="small sub" style="margin:6px 0 0">${h(m.home.short)} ${fx(s.home)}, ${h(m.away.short)} ${fx(s.away)}</p>
    ${lineList(stat, s, m.prediction && m.prediction.result)}`;
  const why = `<details><summary>Why</summary><ul class="why">${(s.why || []).map(w => `<li>${h(w)}</li>`).join("")}</ul>
    <p class="small sub" style="margin-top:8px">${h(accuracyLine(acc, m.comp, stat))}</p></details>`;
  if (stat !== "goals") return `<section class="panel">${head}${why}</section>`;
  return `<section class="panel goals"><div>${head}${why}</div>
    <div><h3>Score</h3>
      <p class="small" style="margin:0 0 4px">Both teams score: <b>${pct(s.btts)}</b>. Clean sheet: ${h(m.home.short)} <b>${pct(s.clean_sheet_home)}</b>, ${h(m.away.short)} <b>${pct(s.clean_sheet_away)}</b>.</p>
      <p class="small sub" style="margin:10px 0 0">Most likely scores</p>
      <div class="scores">${s.likely_scores.map(x => `<span><b>${h(x.score.replace("-", "–"))}</b>${pct(x.p)}</span>`).join("")}</div>
    </div></section>`;
}

function buildSection(P, m) {
  const B = P.blend;
  if (!B || B.views_weight == null || !P.stats.goals.views) return "";
  const w = B.views_weight, W = B.weights || { form: 0.4, gap: 0.35, h2h: 0.25 };
  const parts = [["b", "Past statistics", 1 - w], ["v1", "Form", w * W.form], ["v2", "Team gap", w * W.gap], ["v3", "Head-to-head", w * W.h2h]];
  const tot = (s, k) => (s.views ? s.views[k][0] + s.views[k][1] : null);
  const rows = Object.keys(STAT).map(k => {
    const s = P.stats[k];
    return `<tr><td>${STAT[k]}</td><td class="n">${fx(s.base_home + s.base_away)}</td><td class="n">${fx(tot(s, "form"))}</td><td class="n">${fx(tot(s, "gap"))}</td><td class="n">${fx(tot(s, "h2h"))}</td><td class="n">${fx(s.blend_home + s.blend_away)}</td><td class="n final">${fx(s.total)}</td></tr>`;
  }).join("");
  const nm = k => (k === P.home ? m.home.short : k === P.away ? m.away.short : k);
  const meet = (B.h2h || []).map(x => `<li>${h(day(x.date))}: ${h(nm(x.home))} ${x.score[0]}–${x.score[1]} ${h(nm(x.away))}</li>`).join("");
  const gm = P.stats.goals.view_meta || {};
  return `<section class="section"><h2>How the numbers were built</h2>
    <div class="split" aria-label="Weights">${parts.map(([c, l, v]) => `<span class="${c}" style="flex:${v}" title="${h(l)} ${pct(v)}">${v >= 0.09 ? `${h(l)} ${pct(v)}` : pct(v)}</span>`).join("")}</div>
    <p class="sub small">60% comes from season-long statistics. 40% comes from three other views: form over the last 5 games, the quality gap between the teams (points per game), and past meetings. Each view leans back toward the statistics when it has little evidence.</p>
    <div class="tscroll build"><table><thead><tr><th>Total, both teams</th><th class="n">Past stats</th><th class="n">Form</th><th class="n">Team gap</th><th class="n">Head-to-head</th><th class="n">Mix</th><th class="n">Final</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="small" style="margin-top:12px">Points per game: ${h(m.home.short)} <b>${fx(B.ppg[0], 2)}</b>, ${h(m.away.short)} <b>${fx(B.ppg[1], 2)}</b> (gap ${sgn(B.gap, 2)}). Form uses the last ${gm.form_games ? Math.min(...gm.form_games) : 5} league games.
    ${meet ? ` Last ${(B.h2h || []).length} meetings:` : " No meetings in the last five seasons."}</p>
    ${meet ? `<ul class="h2h">${meet}</ul>` : ""}
    <p class="sub small" style="margin-top:10px">"Final" includes the adjustments below.</p></section>`;
}

function predictionCard(m, acc) {
  const pr = m.prediction, P = pr.prediction, conf = P.confidence, adjs = P.adjustments || [];
  const statusLabel = { measured: "applied", provisional: "applied, provisional", info: "context only" };
  const miss = pr.missing || pr.suspended || {}, doubt = pr.doubtful || {};
  const tag = side => x => ({ ...x, team: side === "home" ? m.home.short : m.away.short });
  const out = [...(miss.home || []).map(tag("home")), ...(miss.away || []).map(tag("away"))];
  const dbt = [...(doubt.home || []).map(tag("home")), ...(doubt.away || []).map(tag("away"))];
  const effCls = v => (v > 0 ? "up" : v < 0 ? "down" : "");
  return `
    <div class="grow">${strip(m.home, m.away, P.stats.goals)}</div>
    <p class="sub" style="margin-top:10px"><span class="pill ${h(conf.level)}">${h(conf.level)} confidence</span>
      ${conf.reasons.length ? ` ${h(conf.reasons.join("; "))}.` : ""}
      Based on ${P.sample.home_games} and ${P.sample.away_games} league games this season${P.sample.home_games < 10 || P.sample.away_games < 10 ? ", blended with last season" : ""}.
      ${m.status === "upcoming" ? `Updated ${h(ago(pr.made_at))}; frozen at kick-off.` : `Frozen before kick-off (last update ${h(kick(pr.made_at))}).`}</p>
    <section class="section"><h2>Expected numbers</h2>
    <div class="grid">${Object.keys(STAT).map(s => statPanel(s, P, m, acc)).join("")}</div></section>
    ${buildSection(P, m)}
    <section class="section"><h2>Adjustments</h2>
    ${adjs.length ? `<ul class="adj">${adjs.map(a => `<li><span class="eff ${effCls(a.effect_pct)}">${a.effect_pct > 0 ? "+" : ""}${fx(a.effect_pct, 1)}%</span><span>${h(STAT[a.stat] || a.stat)}, ${h(a.side === "both" ? "both teams" : a.side === "home" ? m.home.short : m.away.short)}: ${h(a.detail)}</span><span class="pill ${h(a.status)}" title="${a.status === "info" ? "Shown for context; not used in the numbers" : a.status === "provisional" ? "Used in the numbers; size not yet calibrated on data" : "Used in the numbers; size measured on past seasons"}">${h(statusLabel[a.status] || a.status)}</span></li>`).join("")}</ul>` : `<p class="empty">No adjustments for this match.</p>`}</section>
    <section class="section"><h2>Missing players</h2>
    ${out.length || dbt.length ? `<ul class="adj">${out.map(x => `<li><span class="eff">${h(x.team)}</span><span>${h(x.name)}: ${h(x.reason)}</span><span class="pill provisional" title="Counted in the numbers">out</span></li>`).join("")}${dbt.map(x => `<li><span class="eff">${h(x.team)}</span><span>${h(x.name)}: ${h(x.reason)}</span><span class="pill info" title="Not counted in the numbers">may play</span></li>`).join("")}</ul>` : `<p class="empty">${pr.team_news ? "No injuries or suspensions reported." : "No team news yet."}</p>`}
    <p class="note" style="margin-top:12px">${pr.team_news ? "Team news comes from FotMob in the last 4 days before kick-off and is refreshed every 3 hours. It can still change before the match." : "Team news appears 4 days before kick-off. Until then, only suspensions worked out from cards are counted, and they may miss appeals or cup bans."}</p></section>
    ${(P.analyst_view || []).length ? `<section class="section"><h2>Analyst view</h2><div class="panel">${P.analyst_view.map(x => `<p>${h(x)}</p>`).join("")}<p class="sub small">Opinion, not part of the numbers above.</p></div></section>` : ""}`;
}

function matchHero(m) {
  const [hc, ac] = teamColors(m.home, m.away);
  const mid = m.status === "finished"
    ? `<div class="score">${m.score[0]}–${m.score[1]}</div>`
    : `<div class="vs">${h(day(m.kickoff))}<b>${h(time(m.kickoff))}</b></div>`;
  return `<section class="mhero" style="background:linear-gradient(100deg, ${css(deep(hc))} 0 49.6%, ${css(deep(ac))} 50.4% 100%)"><div class="wrap">
    <div class="mhead">
      <div class="mteam">${disc(m.home, "lg")}<a href="#/team/${h(m.home.slug)}">${h(m.home.name)}</a></div>
      ${mid}
      <div class="mteam away">${disc(m.away, "lg")}<a href="#/team/${h(m.away.slug)}">${h(m.away.name)}</a></div></div>
    <p class="mmeta">${h(LEAGUES[m.comp])}${m.round ? `, ${h(m.round)}` : ""}${m.status === "finished" ? `, ${h(kick(m.kickoff || m.date))}` : ""}${m.venue ? `. ${h(m.venue)}` : ""}${m.referee ? `. Referee ${h(m.referee)}` : ""}</p>
  </div></section>`;
}

function cmpRow(label, a, b, colors, check, conflict) {
  if (a == null && b == null) return "";
  const flag = check === "conflict"
    ? `<span class="pill conflict" title="${h(JSON.stringify(conflict || {}))}">sources disagree</span>`
    : check === "single" ? `<span class="pill single">one source</span>` : check === "verified" ? `<span class="pill">checked</span>` : "";
  return `<li><div class="lab"><span>${h(label)}</span>${flag}</div>
    <span class="v">${a ?? "–"}</span>
    <span class="b"><span style="flex:${a || 0.0001};background:${css(colors[0])}"></span><span style="flex:${b || 0.0001};background:${css(colors[1])}"></span></span>
    <span class="v r">${b ?? "–"}</span></li>`;
}

async function renderMatch(id) {
  const [m, acc] = await Promise.all([get(`match/${id}.json`), get("accuracy.json").catch(() => null)]);
  title(`${m.home.short} v ${m.away.short}`);
  setNav("home");
  if (m.status === "upcoming") {
    app.innerHTML = matchHero(m) + wrap(m.prediction ? BANNER + predictionCard(m, acc) : `<p class="note">${h(m.note || "")}</p>`);
    return;
  }
  const colors = teamColors(m.home, m.away);
  const S = m.stats, C = m.checks || {}, conf = m.conflict_values || {};
  let body = `<section><h2>Match stats</h2><ul class="cmp">
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
  <p class="sub small" style="margin-top:10px">Sources: ${h((m.sources || []).join(" and "))}. "Checked" means both sources agree; when they disagree, the stat is left out of the model for this match${Object.keys(conf).length ? ": " + Object.entries(conf).map(([k, v]) => `${k} ${Object.entries(v).map(([s, x]) => `${s} ${x[0]}–${x[1]}`).join(" vs ")}`).join("; ") : ""}.</p></section>`;
  const events = [...(m.goals || []).map(g => ({ min: g.minute, team: g.team, html: `⚽ <b>${h(g.scorer || "Goal")}</b>${g.penalty ? " (pen)" : ""}${g.own_goal ? " (own goal)" : ""}${g.assist ? ` <span class="sub">assist ${h(g.assist)}</span>` : ""}` })),
    ...(m.cards || []).map(c => ({ min: c.minute, team: c.team, html: `${c.card === "red" ? "🟥" : "🟨"} ${h(c.player)}` }))]
    .sort((a, b) => (a.min ?? 0) - (b.min ?? 0));
  if (events.length) body += `<section class="section"><h2>Goals and cards</h2><ul class="timeline">${events.map(e => `<li class="${e.team === m.away.name ? "away" : ""}"><span class="min">${e.min ?? ""}'</span><span>${e.html}</span></li>`).join("")}</ul></section>`;
  if (m.prediction && m.prediction.result) {
    const P = m.prediction.prediction, R = m.prediction.result, g = R.goals || {};
    body += `<section class="section"><h2>Estimate vs result</h2>
      <p>Before kick-off the model gave ${h(m.home.short)} ${pct(P.stats.goals.home_win)}, draw ${pct(P.stats.goals.draw)}, ${h(m.away.short)} ${pct(P.stats.goals.away_win)}.
      The actual result had a ${pct(g.p_outcome)} chance. ${g.pick_correct ? "The most likely outcome happened." : "The most likely outcome did not happen."}</p>
      <div class="tscroll"><table><thead><tr><th>Stat</th><th class="n">Expected</th><th class="n">Likely range</th><th class="n">Actual</th><th>Lines</th></tr></thead><tbody>
      ${Object.keys(STAT).map(s => {
        const r = R[s], p = P.stats[s];
        if (!r || r.excluded) return `<tr><td>${STAT[s]}</td><td class="n">${fx(p.total)}</td><td class="n">${p.range[0]}–${p.range[1]}</td><td class="n">–</td><td class="sub">left out (sources disagree or missing)</td></tr>`;
        return `<tr><td>${STAT[s]}</td><td class="n">${fx(p.total)}</td><td class="n">${p.range[0]}–${p.range[1]}</td><td class="n">${r.actual_total}</td><td>${Object.entries(r.lines).map(([l, d]) => `over ${l} ${pct(d.p_over)} ${d.hit ? "✓" : "✗"}`).join(", ")}</td></tr>`;
      }).join("")}</tbody></table></div>
      <details><summary>Full estimate as it was frozen</summary>${predictionCard({ ...m, status: "finished" }, acc)}</details></section>`;
  } else if (m.comp !== "champions-league") {
    body += `<p class="note section">No frozen estimate for this match: it was played before estimates started on this site.</p>`;
  }
  if (m.lineups && m.lineups.home) {
    const lu = side => {
      const L = m.lineups[side];
      const ps = (L.players || []).filter(p => p.minutes > 0).sort((a, b) => b.starter - a.starter || b.minutes - a.minutes);
      return `<div class="tscroll"><table><thead><tr><th>${h(m[side].short)} ${L.formation ? `<span class="sub">${h(L.formation)}</span>` : ""}</th><th class="n">Min</th><th class="n">G</th><th class="n">A</th></tr></thead><tbody>
        ${ps.map(p => `<tr><td>${h(p.name)}${p.starter ? "" : ' <span class="sub">(sub)</span>'}</td><td class="n">${p.minutes}</td><td class="n">${p.goals || ""}</td><td class="n">${p.assists || ""}</td></tr>`).join("")}</tbody></table></div>`;
    };
    body += `<section class="section"><h2>Lineups</h2><div class="lineups">${lu("home")}${lu("away")}</div></section>`;
  }
  app.innerHTML = matchHero(m) + wrap(body);
}

/* ---------------------------------------------------------------- team */
async function renderTeam(slug) {
  const t = await get(`team/${slug}.json`);
  title(t.name);
  setNav("teams");
  const A = t.averages, R = t.record;
  const col = pick(t) || [15, 59, 44];
  const rows = Object.keys(STAT).map(s => {
    const a = A[s];
    return `<tr><td>${STAT[s]}</td>${["overall", "home", "away"].map(v => `<td class="n">${fx(a[v].for)}</td><td class="n">${fx(a[v].against)}</td>`).join("")}</tr>`;
  }).join("");
  const rate = (k, v) => (R[v].p ? `${R[v][k]} (${pct(R[v][k] / R[v].p)})` : "–");
  const f5 = t.form.last5, f10 = t.form.last10;
  const pts = R.overall.p ? (3 * R.overall.w + R.overall.d) / R.overall.p : null;
  const formCmp = f10 ? `<div class="tscroll"><table><thead><tr><th></th><th class="n">Last 5</th><th class="n">Last 10</th><th class="n">Season</th></tr></thead><tbody>
    <tr><td>Points per game</td><td class="n">${fx(f5.ppg, 2)}</td><td class="n">${fx(f10.ppg, 2)}</td><td class="n">${fx(pts, 2)}</td></tr>
    ${Object.keys(STAT).map(s => `<tr><td>${STAT[s]} for / against</td><td class="n">${fx(f5.averages[s].for)} / ${fx(f5.averages[s].against)}</td><td class="n">${fx(f10.averages[s].for)} / ${fx(f10.averages[s].against)}</td><td class="n">${fx(A[s].overall.for)} / ${fx(A[s].overall.against)}</td></tr>`).join("")}
    </tbody></table></div>` : "";
  app.innerHTML = `
    <section class="thero" style="background:${css(deep(col))}"><div class="wrap">
      ${disc(t, "lg")}
      <div><h1>${h(t.name)}</h1>
        <p class="meta">${h(LEAGUES[t.league])}, ${R.overall.p} league games</p>
        <div class="facts"><div><b>${R.overall.w}-${R.overall.d}-${R.overall.l}</b>won, drawn, lost</div><div><b>${fx(pts, 2)}</b>points a game</div>
          <div><b>${fx(A.goals.overall.for)}–${fx(A.goals.overall.against)}</b>goals a game</div>${f10 ? `<div><b>${formDots(f10.results, "")}</b>last ${f10.n}</div>` : ""}</div></div>
    </div></section>
    ${wrap(`
    ${t.upcoming.length ? `<section><h2>Next matches</h2><div class="cards">${t.upcoming.map(fixtureCard).join("")}</div></section>` : ""}
    <section class="section"><h2>Season averages per game</h2>
    <div class="tscroll"><table><thead><tr><th rowspan="2">Stat</th><th class="n" colspan="2">Overall</th><th class="n" colspan="2">Home</th><th class="n" colspan="2">Away</th></tr>
      <tr><th class="n">For</th><th class="n">Against</th><th class="n">For</th><th class="n">Against</th><th class="n">For</th><th class="n">Against</th></tr></thead>
      <tbody>${rows}
      <tr><td>Clean sheets</td><td class="n" colspan="2">${rate("clean_sheets", "overall")}</td><td class="n" colspan="2">${rate("clean_sheets", "home")}</td><td class="n" colspan="2">${rate("clean_sheets", "away")}</td></tr>
      <tr><td>Both teams scored</td><td class="n" colspan="2">${rate("btts", "overall")}</td><td class="n" colspan="2">${rate("btts", "home")}</td><td class="n" colspan="2">${rate("btts", "away")}</td></tr>
      <tr><td>Over 2.5 goals</td><td class="n" colspan="2">${rate("over25", "overall")}</td><td class="n" colspan="2">${rate("over25", "home")}</td><td class="n" colspan="2">${rate("over25", "away")}</td></tr>
      <tr><td>Won / drawn / lost</td><td class="n" colspan="2">${R.overall.w}/${R.overall.d}/${R.overall.l}</td><td class="n" colspan="2">${R.home.w}/${R.home.d}/${R.home.l}</td><td class="n" colspan="2">${R.away.w}/${R.away.d}/${R.away.l}</td></tr>
      </tbody></table></div>
    <p class="sub small" style="margin-top:8px">Cards count yellow and red cards the team received. League matches only.</p></section>
    ${formCmp ? `<section class="section"><h2>Form</h2>${formCmp}</section>` : ""}
    <section class="section"><h2>Goals and assists</h2>
    ${t.scorers.length ? `<div class="tscroll"><table><thead><tr><th>Player</th><th class="n">Goals</th><th class="n">Assists</th><th>Share of team goals</th><th class="n">Apps</th><th class="n">Min</th></tr></thead><tbody>
      ${t.scorers.map(p => `<tr><td>${h(p.name)}</td><td class="n">${p.goals}</td><td class="n">${p.assists}</td><td><span class="share"><span style="width:${Math.min(100, p.share_goals * 100)}%"></span></span>${pct(p.share_goals)} scored, ${pct(p.share_involvement)} involved</td><td class="n">${p.apps}</td><td class="n">${p.minutes}</td></tr>`).join("")}
      </tbody></table></div>` : `<p class="empty">No player data yet.</p>`}</section>
    <section class="section"><h2>Game by game</h2>
    <div class="tscroll"><table><thead><tr><th>Date</th><th>Comp</th><th>Opponent</th><th class="n">H/A</th><th class="n">Score</th><th class="n">Corners</th><th class="n">Cards</th><th class="n">Shots</th><th class="n">On target</th></tr></thead><tbody>
      ${[...t.log].reverse().map(r => `<tr><td><a href="#/match/${h(r.id)}">${h(day(r.kickoff || r.date))}</a></td><td class="sub">${r.comp === "champions-league" ? "UCL" : "League"}</td><td>${tlink(r.opp)}</td><td class="n">${r.venue}</td>
        <td class="n">${formDots(r.result)} ${r.goals[0]}–${r.goals[1]}</td>
        ${["corners", "cards", "shots", "shots_on_target"].map(s => `<td class="n">${r[s][0] ?? "–"}–${r[s][1] ?? "–"}</td>`).join("")}</tr>`).join("")}
    </tbody></table></div>
    <p class="sub small" style="margin-top:8px">Each pair is for–against.</p></section>`)}`;
}

async function renderTeams() {
  const teams = await get("teams.json");
  title("Teams");
  setNav("teams");
  const groups = Object.keys(LEAGUES).map(k => [k, teams.filter(t => t.league === k)]);
  const draw = q => groups.map(([k, ts]) => {
    const f = ts.filter(t => t.name.toLowerCase().includes(q));
    return f.length ? `<section class="section"><h2>${h(LEAGUES[k])}${k === "champions-league" ? ", other clubs" : ""}</h2><ul class="teamgrid">${f.map(t => `<li><a href="#/team/${h(t.slug)}">${disc(t, "sm")}${h(t.name)}</a></li>`).join("")}</ul></section>` : "";
  }).join("") || `<p class="empty">No team matches that name.</p>`;
  app.innerHTML = `<section class="hero turf"><div class="wrap"><h1>Teams</h1><p class="sub" style="margin-top:8px">Season averages, form, scorers and every game.</p></div></section>
    ${wrap(`<label class="sub small" for="q">Find a team</label><br><input id="q" class="search" type="search" placeholder="Real Madrid, Arsenal…" autocomplete="off"><div id="tl">${draw("")}</div>`)}`;
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
function duel(model, base, label = "league averages", note = "Error here is log loss across each stat's lines.") {
  // lower is better; bars show how much of the baseline's error remains
  return `<div class="duel">${Object.keys(STAT).filter(s => model[s] && base[s]).map(s => {
    const m = model[s], b = base[s], gain = (b - m) / b;
    return `<div class="row"><span>${STAT[s]}</span><span class="bars"><span class="m" style="width:${Math.min(100, (m / b) * 100)}%"></span><span class="bl" style="width:100%"></span></span><span class="d">${gain >= 0 ? "" : "−"}${fx(Math.abs(gain) * 100, 1)}%</span></div>`;
  }).join("")}<p class="sub small">Green: the model's error. Grey: ${h(label)}' error. Shorter green is better; the figure is how much smaller the model's error is. ${h(note)}</p></div>`;
}
function statTable(rows, base) {
  return `<div class="tscroll"><table><thead><tr><th>Stat</th><th class="n">Avg miss</th><th class="n">League avg miss</th><th>Calls right per line (Brier, lower is better; league average in brackets)</th></tr></thead><tbody>
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
  let body = "";
  if (!live.matches) {
    body += `<section><h2>Live estimates</h2><p class="empty">None scored yet. Estimates are frozen at kick-off and appear here after the final whistle.</p></section>`;
  } else {
    const all = live.by_league.all;
    body += `<section><h2>Live estimates: ${live.matches} matches</h2>`;
    if (all.goals) body += `<p>Most likely result (win/draw/loss) came true in <b>${pct(all.goals.pick_rate)}</b> of matches. Brier score ${fx(all.goals.brier_1x2, 3)} vs ${fx(all.goals.baseline_brier_1x2, 3)} for league averages (lower is better). Exact score right: ${pct(all.goals.score_rate)}.</p>`;
    const err = {}, berr = {};
    Object.entries(all).forEach(([s, v]) => { err[s] = v.mae; berr[s] = v.baseline_mae; });
    body += duel(err, berr, "league averages", "Error here is the average miss on totals.");
    for (const lg of ["la-liga", "premier-league"]) if (live.by_league[lg]) body += `<h3 style="margin-top:22px">${h(LEAGUES[lg])}</h3>${statTable(live.by_league[lg])}`;
    body += `<h3 style="margin-top:22px">Calibration</h3>${calibSvg(live.calibration)}<p class="sub small">Dots on the dashed line mean the probabilities are honest. Only groups with 20+ estimates are drawn.</p>`;
    body += `<h3 style="margin-top:22px">Latest scored</h3><ul class="results">${acc.recent.slice(0, 16).map(r => resultItem({ ...r, score: r.score || ["–", "–"], has_prediction: false })).join("")}</ul></section>`;
  }
  if (bt && bt.test) {
    const g = bt.test.goals, gb = bt.baseline.goals;
    const mo = bt.objective_x1000 || {}, bo = bt.baseline_objective_x1000 || {}, po = bt.pure_objective_x1000 || {};
    const better = Object.keys(po).filter(k => mo[k] < po[k]).map(k => STAT[k].toLowerCase());
    const worse = Object.keys(po).filter(k => mo[k] > po[k]).map(k => STAT[k].toLowerCase());
    body += `<section class="section"><h2>Tested on last season</h2>
      <p>Tuned on 2023-24 and 2024-25, then run once over all ${bt.matches} Premier League and La Liga matches of 2025-26, each estimated using only games played before it. This is a test, not a live record.</p>
      <p>Win/draw/loss Brier score <b>${fx(g.brier, 3)}</b> vs ${fx(gb.brier, 3)} for league averages, ${fx((1 - g.brier / gb.brier) * 100, 1)}% better.</p>
      ${Object.keys(mo).length ? duel(mo, bo) : ""}
      ${Object.keys(po).length ? `<h3 style="margin-top:22px">The 60/40 mix vs statistics alone</h3>
        <p class="small">Estimates use 60% past statistics and 40% form, team gap and head-to-head. On the test season, the mix compared with statistics alone like this (log loss, lower is better):</p>
        <div class="tscroll"><table><thead><tr><th>Stat</th><th class="n">60/40 mix</th><th class="n">Statistics alone</th><th class="n">Difference</th></tr></thead><tbody>
        ${Object.keys(STAT).map(s => po[s] != null ? `<tr><td>${STAT[s]}</td><td class="n">${fx(mo[s] / 1000, 4)}</td><td class="n">${fx(po[s] / 1000, 4)}</td><td class="n">${sgn((mo[s] - po[s]) / po[s] * 100, 2)}%</td></tr>` : "").join("")}
        </tbody></table></div><p class="sub small" style="margin-top:6px">Almost a tie. The mix is slightly better on ${h(better.join(", ") || "nothing")}${worse.length ? ` and slightly worse on ${h(worse.join(", "))}` : ""}.</p>` : ""}
      <h3 style="margin-top:22px">Lines in detail</h3>${statTable(bt.test, bt.baseline)}
      <h3 style="margin-top:22px">Calibration in testing</h3>${calibSvg(bt.calibration)}
      <p class="sub small">Referee history didn't improve accuracy in testing, so it's shown on cards for context only. Derby matches had ${fx((bt.tuning.derby_cards - 1) * 100, 0)}% more cards than expected, so that adjustment is applied.</p></section>`;
  }
  app.innerHTML = `<section class="hero turf"><div class="wrap"><h1>Track record</h1>
    <p class="sub" style="margin-top:8px;max-width:64ch">Every estimate is frozen at kick-off and compared with what happened, misses included. A good model should beat plain league averages, and its 70% calls should come true about 70% of the time.</p></div></section>${wrap(body)}`;
}

/* ---------------------------------------------------------------- about */
function renderAbout() {
  title("How it works");
  setNav("about");
  app.innerHTML = `<section class="hero turf"><div class="wrap"><h1>How it works</h1></div></section>${wrap(`<div class="prose">
  <p>Matchday Numbers shows past statistics and statistical estimates for upcoming La Liga and Premier League matches, plus full stats for the Champions League. It's an information tool: every estimate shows its inputs, its uncertainty and its track record, so you can decide how much to trust it.</p>
  <h2>Where the data comes from</h2>
  <ul><li><b>football-data.co.uk</b>: results, shots, corners and cards for both leagues, and referees for the Premier League.</li>
  <li><b>ESPN</b>: fixtures, kick-off times, Champions League matches, lineups, goals, assists and minutes.</li>
  <li><b>FotMob</b>: team news (injured and suspended players) for the next few days' matches.</li></ul>
  <p>The ESPN and FotMob feeds are public but unofficial, so they can change without notice. Where football-data.co.uk and ESPN both cover a match, they're compared stat by stat; if they disagree by more than a corner or card (two shots), that stat is shown with both values and left out of the model for that match. Data refreshes every three hours.</p>
  <h2>The model, in plain words</h2>
  <ol><li><b>Past statistics (60%).</b> For each stat, start from the league average for home or away teams, then multiply by the home side's attacking strength and the away side's defensive weakness, and the other way round. The last 6 games count double. With few games, numbers lean toward last season's level, or a typical promoted team's. Goals also borrow from shots on target, which measure the same thing with less luck.</li>
  <li><b>Form, team gap and head-to-head (40%).</b> Form looks only at the last 5 games. Team gap turns the difference in points per game into more or fewer goals, corners, shots and cards, using effects measured on past seasons. Head-to-head uses up to 6 past meetings. Each view leans back toward the statistics when it has little evidence.</li>
  <li><b>Adjustments</b>, each listed on the card with its effect: derby matches (more cards, measured on past seasons), missing players (provisional: a team's expected goals drop by 40% of the player's share of its goals and assists, and a missing regular keeper or defender adds 3% to the opponent), and short rest (provisional). Referee history is shown for context only.</li>
  <li><b>Probabilities.</b> Goals use a Dixon-Coles model to get win/draw/loss, likely scores and over/under chances. Corners, cards and shots use a negative binomial distribution, which allows for more spread than a simple average suggests.</li></ol>
  <p>Confidence is Low, Medium or High depending on how many games the numbers rest on, how much the adjustments moved them, and whether team news was available.</p>
  <h2>What it can't do</h2>
  <ul><li>Team news is only as good as FotMob's reports, and doubtful players aren't counted.</li>
  <li>Champions League estimates are left out: teams from different leagues can't be compared reliably yet.</li>
  <li>Corners and cards are hard to predict for anyone. The model beats league averages on them, but only slightly.</li>
  <li>Analyst views (new manager, motivation) are kept in a separate box and never mixed into the numbers.</li></ul>
  <p>Every estimate is saved in the project's public history before kick-off, so the track record can't be edited after the fact.</p></div>`)}`;
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
    app.innerHTML = wrap(`<h1 style="margin-top:28px">Page not found</h1><p>This page doesn't exist or its data hasn't been published yet. <a href="#/">Go to matches</a>.</p><p class="sub small">${h(e.message)}</p>`);
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
      `Data last updated ${kick(meta.updated_at)} (your time), refreshed every 3 hours. ` +
      `Latest football-data.co.uk match: ${Object.entries(fd).map(([k, v]) => `${LEAGUES[k]} ${v ? day(v) : "none"}`).join(", ")}.`;
  } catch (e) {
    document.getElementById("freshness").textContent = "Data freshness unknown.";
  }
  window.addEventListener("hashchange", route);
  route();
}
boot();
