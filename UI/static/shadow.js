/* SHADOW SELF — UI behaviour (served at /static/shadow.js). Plain JavaScript, no libraries.
   One shared selection (a system, optionally one of its measurements) drives the radar, system tiles, priority list,
   linked trend and the details drawer. Crew and day changes fetch the server-rendered page and swap it in place
   (the radar morphs between the two real days); history and the hash tab are kept.
   Also: tabs, 24 h trace readouts, report legend + tooltips, Systems navigation + filter, validated manual entry,
   CSV upload (click or drag-drop), log filter, busy overlay, collapsible / mobile navigation, print.
   Fallbacks: no JS -> every view is shown stacked (see <noscript> in page.py); a failed fetch -> normal navigation;
   reduced motion -> no movement, state changes are instant. */
(() => {
  "use strict";
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const root = document.documentElement;
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const vt = !!document.startViewTransition;
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt = (v, d = 2) => v == null ? "—" : (Math.round(v * 10 ** d) / 10 ** d).toLocaleString("en-US", { maximumFractionDigits: d });
  const pct = p => p == null ? "—" : (p > 0 ? "+" : "") + p.toFixed(1) + "%";
  const ICON = {
    ok: '<circle cx="12" cy="12" r="8.5"/><path d="M8.3 12.3l2.5 2.5 4.9-5.3"/>',
    watch: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.6v5.2M12 16.3v.01"/>',
    act: '<path d="M12 3.6 2.6 19.6h18.8z"/><path d="M12 9.8v4.4M12 17v.01"/>',
    urgent: '<path d="M8.3 2.8h7.4l5.5 5.5v7.4l-5.5 5.5H8.3l-5.5-5.5V8.3z"/><path d="M12 7.6v5.2M12 16.3v.01"/>',
    none: '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 12h7"/>',
  };
  const LABEL = { ok: "Nominal", info: "Info", watch: "Watch", act: "Act", urgent: "Urgent", "no-data": "No data", "no-baseline": "No baseline", ignored: "Ignored" };
  const RANK = { urgent: 4, act: 3, watch: 2, info: 1, ok: 0 };
  const sicon = s => `<svg class="si" viewBox="0 0 24 24" aria-hidden="true">${ICON[s === "info" ? "ok" : s] || ICON.none}</svg>`;
  const chip = (s, label) => `<span class="chip ${esc(s)}">${sicon(s)}${esc(label || LABEL[s] || s)}</span>`;
  const tri = k => `<svg class="tri" viewBox="0 0 12 12" aria-hidden="true"><path d="${{ up: "M6 2.5l4.5 7h-9z", down: "M6 9.5 1.5 2.5h9z", flat: "M2 5h8v2H2z" }[k]}"/></svg>`;
  function deltaHTML(cur, prev, pday) {
    if (cur == null || prev == null || pday == null) return '<span class="delta none">No earlier day to compare</span>';
    const dv = cur - prev, k = dv >= 0.5 ? "up" : dv <= -0.5 ? "down" : "flat";
    return `<span class="delta ${k}"><b>${tri(k)}<span class="sr">${{ up: "up", down: "down", flat: "no change" }[k]} </span>${Math.abs(dv).toFixed(0)}</b> vs day ${pday} (${prev.toFixed(0)})</span>`;
  }

  let D = readData();
  const state = { sel: null, metric: null };
  function readData() { try { return JSON.parse($("#sd-data")?.textContent || "null"); } catch (e) { return null; } }

  /* ========== tabs ========== */
  const VIEWS = () => $$(".view").map(v => v.dataset.view);
  function moveIndicator() {
    const ind = $(".tab-ind"), t = $('.tab[aria-selected="true"]');
    if (!ind || !t || !t.offsetHeight) return;
    ind.style.height = t.offsetHeight + "px";
    ind.style.setProperty("--y", t.offsetTop + "px");
  }
  function show(view) {
    const lost = document.activeElement?.closest(".view");
    $$(".view").forEach(v => { v.hidden = v.dataset.view !== view; });
    if (lost && lost.hidden) {                       // a link inside the old view: move focus to the new view's heading
      const h = $(`.view[data-view="${view}"] h2`);
      if (h) { h.tabIndex = -1; h.focus({ preventScroll: true }); }
    }
    $$(".tab").forEach(t => {
      const on = t.dataset.tab === view;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
    });
    $$('input[name="tab"]').forEach(i => { if (i.closest(".runform") || i.closest("[action='/run']")) i.value = view; });
    document.body.dataset.view = view;
    moveIndicator();
  }
  function route() {
    const [name, sub] = location.hash.slice(1).split("/");
    const view = VIEWS().includes(name) ? name : "overview";
    const kbd = route.kbd; route.kbd = false;
    $(".tab-ind")?.classList.toggle("instant", !!kbd);
    if (route.done && vt && !kbd && !reduced && document.body.dataset.view !== view) {
      const t = document.startViewTransition(() => show(view));
      [t.ready, t.finished, t.updateCallbackDone].forEach(p => p.catch(() => {}));
      setTimeout(() => { if (document.body.dataset.view !== view) { t.skipTransition?.(); show(view); } }, 300);
    } else show(view);
    if (view === "systems") showSystem(sub);
    if (route.done && !sub) window.scrollTo({ top: 0, behavior: "auto" });
    route.done = true;
  }
  addEventListener("hashchange", route);
  document.addEventListener("keydown", ev => {
    if (!ev.target.closest?.(".tabs") || !["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"].includes(ev.key)) return;
    const tabs = $$(".tab"), i = tabs.indexOf(document.activeElement);
    if (i < 0) return;
    ev.preventDefault();
    const next = tabs[(i + (ev.key === "ArrowDown" || ev.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    route.kbd = true; next.focus(); location.hash = next.dataset.tab;
  });

  /* ========== shared selection: radar, tiles, priority list, trend, drawer ========== */
  function select(dom, metric = null) {
    if (D && dom && !D.sys[dom] && dom !== "context") dom = null;
    state.sel = dom || null;
    state.metric = metric;
    applySelection(true);
  }
  function applySelection(animate = false) {
    const sel = state.sel;
    $$(".ax[data-select], .stile[data-select]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.select === sel)));
    const radar = $("[data-radar]");
    if (radar) {
      if (sel) radar.dataset.sel = sel; else delete radar.dataset.sel;
      $$(".vx", radar).forEach(v => v.classList.toggle("sel", v.dataset.dom === sel));
    }
    $$("[data-reset]").forEach(b => { b.hidden = !sel; });
    const read = $("[data-radar-read]");
    if (read && D) {
      read.dataset.def ??= read.textContent;
      if (sel && D.sys[sel]) {
        const s = D.sys[sel];
        read.innerHTML = `<b>${esc(s.name)}</b>: ${s.score == null ? "no data" : s.score.toFixed(0) + " of 100"}, ${esc(s.label)}` +
          (s.prev != null && s.score != null ? ` · ${s.score >= s.prev ? "up" : "down"} ${Math.abs(s.score - s.prev).toFixed(0)} from day ${D.prevDay} (${s.prev.toFixed(0)})` : "");
      } else read.textContent = read.dataset.def;
    }
    // priority: alerts for the chosen system only, the plan dims what isn't about it
    const prio = $(".t-prio");
    if (prio && D) {
      const note = $("[data-prio-filter]", prio);
      const name = sel && D.sys[sel] ? D.sys[sel].name : "";
      if (note) {
        note.hidden = !sel;
        if (sel) note.innerHTML = `Showing ${esc(name)} · <button class="link-btn" type="button" data-select="">Show all</button>`;
      }
      $$(".act-card", prio).forEach(c => c.classList.toggle("dim", !!sel && c.dataset.dom !== sel));
      renderAlerts(prio, animate);
    }
    $$("[data-open-drawer]").forEach(b => { b.hidden = !sel || !D?.sys[sel]; });
    renderTrend();
  }
  const alertsUI = { open: false };
  // rows rise in only when the person changed the list (a selection, Show more), never on page load or a day swap
  function renderAlerts(prio, animate = false) {
    const list = $("[data-alist]", prio), more = $("[data-more]", prio);
    if (!list) return;
    const items = $$(".al", list), was = new Set(items.filter(li => !li.hidden));
    const match = items.filter(li => !state.sel || li.dataset.dom === state.sel);
    const limit = alertsUI.open ? Infinity : 3;
    items.forEach(li => { li.hidden = true; li.classList.remove("in", "first"); });
    match.forEach((li, i) => {
      li.hidden = i >= limit;
      if (!li.hidden && animate && !was.has(li)) { void li.offsetWidth; li.classList.add("in"); li.style.setProperty("--i", Math.min(i, 8)); }
    });
    match.find(li => !li.hidden)?.classList.add("first");
    let empty = $(".al-empty", prio);
    if (!match.length && state.sel) {
      if (!empty) { empty = document.createElement("p"); empty.className = "quiet al-empty"; list.after(empty); }
      empty.innerHTML = `${sicon("ok")}No ${esc(D.sys[state.sel]?.name || "")} alerts today.`;
    } else empty?.remove();
    if (more) {
      const extra = match.length - 3;
      more.hidden = extra <= 0;
      more.textContent = alertsUI.open ? "Show fewer" : `Show ${extra} more`;
      more.setAttribute("aria-expanded", String(alertsUI.open));
    }
  }

  document.addEventListener("click", ev => {
    const s = ev.target.closest("[data-select]");
    if (s) {
      const dom = s.dataset.select;
      const toggleOff = dom && dom === state.sel && !s.dataset.metric && !s.hasAttribute("data-open-drawer-for") && s.matches(".ax, .stile");
      select(toggleOff ? null : dom, s.dataset.metric || null);
      if (s.hasAttribute("data-open-drawer-for")) openDrawer(dom, s);
      if (s.dataset.scrollTrend !== undefined) $("[data-trend]")?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "start" });
      return;
    }
    if (ev.target.closest("[data-more]")) { alertsUI.open = !alertsUI.open; renderAlerts($(".t-prio"), true); return; }
    const od = ev.target.closest("[data-open-drawer]");
    if (od && state.sel) openDrawer(state.sel, od);
    const m = ev.target.closest("[data-metric-pick]");
    if (m) { state.metric = m.dataset.metricPick || null; renderTrend(); }
  });

  /* ---------- charts (drawn from the same rows as the page) ---------- */
  function scoreChart(doms, focus) {
    const W = 680, H = 230, pl = 32, pr = 84, pt = 16, pb = 26;
    const days = D.days, lo = days[0], hi = days[days.length - 1];
    const x = d => pl + (hi > lo ? (d - lo) / (hi - lo) : 0.5) * (W - pl - pr), y = v => pt + (1 - v / 100) * (H - pt - pb);
    let s = `<rect class="c-zone watch" x="${pl}" y="${y(75)}" width="${W - pl - pr}" height="${y(50) - y(75)}"/>` +
      `<rect class="c-zone act" x="${pl}" y="${y(50)}" width="${W - pl - pr}" height="${y(0) - y(50)}"/>`;
    [0, 25, 50, 75, 100].forEach(v => { s += `<line class="gridline" x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${pl - 6}" y="${y(v) + 3.5}" text-anchor="end">${v}</text>`; });
    days.forEach(d => { s += `<text class="axis${d === D.day ? " on" : ""}" x="${x(d)}" y="${H - 7}" text-anchor="middle">Day ${d}</text>`; });
    s += `<text class="c-zl" x="${pl + 6}" y="${y(75) + 13}">Watch zone, under 75</text><text class="c-zl" x="${pl + 6}" y="${y(50) + 13}">Act zone, under 50</text>`;
    const ends = [];
    doms.forEach(dom => {
      const sys = D.sys[dom]; if (!sys) return;
      const cls = dom === focus ? "focus" : dom === "overall" ? "overall" : focus ? "ghost" : "";
      let path = "", prevDay = null;
      const pts = sys.series.filter(r => r[1] != null);
      pts.forEach(([d, v]) => { path += (prevDay != null && d === prevDay + 1 ? " L" : " M") + `${x(d).toFixed(1)},${y(v).toFixed(1)}`; prevDay = d; });
      let dots = "", vals = "";
      pts.forEach(([d, v, st]) => {
        dots += `<circle class="${st}" cx="${x(d).toFixed(1)}" cy="${y(v).toFixed(1)}" r="${cls === "focus" ? 4.5 : 3.5}" data-tip="${esc(sys.name)} · day ${d} · ${v.toFixed(0)}/100 · ${esc(LABEL[st] || st)}"/>`;
        if (cls === "focus") vals += `<text class="val" x="${x(d).toFixed(1)}" y="${(y(v) - 10).toFixed(1)}" text-anchor="middle">${v.toFixed(0)}</text>`;
      });
      const last = pts[pts.length - 1];
      if (last && cls !== "ghost") ends.push({ cls, name: sys.name, y: y(last[1]) });
      s += `<g class="ser ${cls}">${path ? `<path d="${path.trim()}"/>` : ""}${dots}${vals}</g>`;
    });
    ends.sort((a, b) => a.y - b.y).forEach((e, i, a) => { if (i) e.y = Math.max(e.y, a[i - 1].y + 13); });
    s += ends.map(e => `<g class="ser ${e.cls}"><text class="end" x="${W - pr + 8}" y="${(e.y + 4).toFixed(1)}">${esc(e.name)}</text></g>`).join("");
    const label = focus ? `${D.sys[focus].name} score by mission day` : "Score per system by mission day";
    return `<div class="chart-wrap" data-tipchart><div class="tip" hidden></div><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">${s}</svg></div>`;
  }
  function metricChart(c) {
    const rows = (c.hist || []).filter(r => r[1] != null);
    if (!rows.length) return '<div class="nodata">No recorded values for this measurement.</div>';
    const W = 680, H = 230, pl = 44, pr = 84, pt = 18, pb = 26;
    const days = D.days, lo = days[0], hi = days[days.length - 1];
    const b = c.baseline, m = c.mdc;
    const vals = rows.map(r => r[1]).concat(b != null ? [b] : [], b != null && m != null ? [b - m, b + m] : []);
    let vmin = Math.min(...vals), vmax = Math.max(...vals);
    const pad = Math.max((vmax - vmin) * 0.18, Math.abs(vmax) * 0.02, 0.5); vmin -= pad; vmax += pad;
    const x = d => pl + (hi > lo ? (d - lo) / (hi - lo) : 0.5) * (W - pl - pr), y = v => pt + (1 - (v - vmin) / (vmax - vmin)) * (H - pt - pb);
    let s = "";
    if (b != null && m != null) s += `<rect class="band" x="${pl}" y="${y(b + m)}" width="${W - pl - pr}" height="${Math.max(y(b - m) - y(b + m), 1)}"/>` +
      `<text class="band-l" x="${W - pr + 8}" y="${y(b) - 4}">Baseline</text><text class="band-l" x="${W - pr + 8}" y="${y(b) + 10}">± noise</text>`;
    const ticks = 4;
    for (let i = 0; i <= ticks; i++) { const v = vmin + (vmax - vmin) * i / ticks; s += `<line class="gridline" x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${pl - 6}" y="${y(v) + 3.5}" text-anchor="end">${fmt(v, Math.abs(vmax) < 10 ? 2 : 0)}</text>`; }
    if (b != null) s += `<line class="base-ln" x1="${pl}" x2="${W - pr}" y1="${y(b)}" y2="${y(b)}"/>`;
    days.forEach(d => { s += `<text class="axis${d === D.day ? " on" : ""}" x="${x(d)}" y="${H - 7}" text-anchor="middle">Day ${d}</text>`; });
    let path = "", prev = null, dots = "", labels = "";
    rows.forEach(([d, v, , , st]) => {
      path += (prev != null && d === prev + 1 ? " L" : " M") + `${x(d).toFixed(1)},${y(v).toFixed(1)}`; prev = d;
      dots += `<circle class="${st}" cx="${x(d).toFixed(1)}" cy="${y(v).toFixed(1)}" r="4.5" data-tip="${esc(c.label)} · day ${d} · ${fmt(v)} ${esc(c.unit)} · ${esc(LABEL[st] || st)}"/>`;
      labels += `<text class="val" x="${x(d).toFixed(1)}" y="${(y(v) - 10).toFixed(1)}" text-anchor="middle">${fmt(v)}</text>`;
    });
    s += `<g class="ser focus"><path d="${path.trim()}"/>${dots}${labels}</g>`;
    return `<div class="chart-wrap" data-tipchart><div class="tip" hidden></div><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(c.label)} by mission day with its pre-flight baseline and noise band">${s}</svg></div>`;
  }
  function mrow(c, dom, pressed, extra = "") {
    return `<li><button type="button" class="mrow" data-select="${esc(dom)}" data-metric="${esc(c.metric)}" aria-pressed="${pressed}"${extra}>` +
      `<span class="m-n">${esc(c.label)}</span><span class="m-sub">${pct(c.pct)} vs baseline ${fmt(c.baseline)}</span>` +
      `<span class="m-v">${fmt(c.value)} <span class="unit">${esc(c.unit)}</span></span>${chip(c.status, c.label_s)}</button></li>`;
  }
  function renderTrend() {
    const tile = $("[data-trend]");
    if (!tile || !D) return;
    const main = $("[data-trend-chart]", tile), side = $("[data-trend-side]", tile);
    const title = $("[data-trend-title]", tile), cap = $("[data-trend-cap]", tile);
    const sel = state.sel && D.sys[state.sel] ? state.sel : null;
    let mainHTML, sideHTML;
    if (!sel) {
      title.textContent = "All systems · score by day";
      cap.textContent = `Mission days ${D.days[0]} to ${D.days[D.days.length - 1]} · Overall is the lowest system`;
      mainHTML = scoreChart([...D.domains, "overall"], null);
      const flagged = Object.entries(D.checks).flatMap(([dom, cs]) => cs.filter(c => c.flagged).map(c => [dom, c]))
        .sort((a, b) => (RANK[b[1].status] || 0) - (RANK[a[1].status] || 0)).slice(0, 6);
      const total = Object.values(D.checks).flat().length;
      sideHTML = `<div class="side-h">Flagged measurements <span>${flagged.length ? `top ${flagged.length} of ${Object.values(D.checks).flat().filter(c => c.flagged).length} · ${total} checks` : `${total} checks`}</span></div>` +
        (flagged.length ? `<ul class="mlist">${flagged.map(([dom, c]) => mrow(c, dom, false, " data-scroll-trend")).join("")}</ul>`
          : `<p class="quiet">${sicon("ok")}No measurement is flagged today.</p>`);
    } else {
      const s = D.sys[sel], cs = D.checks[sel] || [];
      const c = cs.find(x => x.metric === state.metric);
      title.textContent = c ? `${s.name} · ${c.label}` : `${s.name} · score by day`;
      cap.innerHTML = c ? `Day ${D.day}: <b class="num">${fmt(c.value)} ${esc(c.unit)}</b> · baseline ${fmt(c.baseline)} ± ${fmt(c.mdc)} noise (MDC)`
        : `Day ${D.day}: <b class="num">${s.score == null ? "no data" : s.score.toFixed(0)}</b>/100 · ${esc(s.label)}`;
      mainHTML = (c ? metricChart(c) : scoreChart([...D.domains.filter(x => x !== sel), sel], sel)) +
        `<p class="fine" style="margin-top:8px">${esc(c ? c.reason : s.note)}</p>`;
      sideHTML = `<div class="side-h">${esc(s.name)} measurements <span>${cs.filter(x => x.flagged).length} of ${cs.length} flagged</span></div>` +
        `<ul class="mlist"><li><button type="button" class="mrow" data-metric-pick="" aria-pressed="${!c}"><span class="m-n">System score</span>` +
        `<span class="m-sub">${deltaHTML(s.score, s.prev, D.prevDay).replace(/<[^>]+>/g, "")}</span><span class="m-v">${s.score == null ? "—" : s.score.toFixed(0)}<span class="unit">/100</span></span>${chip(s.status, s.label)}</button></li>` +
        (cs.length ? cs.map(x => mrow(x, sel, x.metric === state.metric)).join("") : "") + `</ul>` +
        (cs.length ? "" : `<p class="quiet">No checks for ${esc(s.name)} today.</p>`);
    }
    main.innerHTML = mainHTML; side.innerHTML = sideHTML;
    if (renderTrend.done && !reduced) { main.classList.remove("swap-in"); void main.offsetWidth; main.classList.add("swap-in"); }
    renderTrend.done = true;
  }

  /* chart tooltips: hover a point (report, trend, drawer) */
  document.addEventListener("pointerover", ev => {
    const p = ev.target.closest?.("[data-tip]"), wrap = p?.closest("[data-tipchart]");
    if (!p || !wrap) return;
    const tip = $(".tip", wrap), r = wrap.getBoundingClientRect(), b = p.getBoundingClientRect();
    tip.textContent = p.dataset.tip; tip.hidden = false;
    const px = b.left - r.left + b.width / 2, flip = px > r.width - 180;
    tip.style.transform = `translate(${flip ? px - tip.offsetWidth - 10 : px + 10}px, ${Math.max(0, b.top - r.top - 34)}px)`;
  });
  document.addEventListener("pointerout", ev => {
    const p = ev.target.closest?.("[data-tip]");
    if (p) { const t = p.closest("[data-tipchart]") && $(".tip", p.closest("[data-tipchart]")); if (t) t.hidden = true; }
  });

  /* ========== drawer: one system, every measurement ========== */
  const drawer = $("#drawer");
  let opener = null;
  function openDrawer(dom, from) {
    if (!drawer || !D?.sys[dom]) return;
    opener = from || document.activeElement;
    const s = D.sys[dom], cs = D.checks[dom] || [];
    const alerts = D.alerts.filter(a => a.domain === dom), plans = D.plans.filter(p => p.domain === dom);
    const rows = cs.map(c => `<tr class="${c.flagged ? "flagged " : ""}${c.status}"><th scope="row"><b>${esc(c.label)}</b><span class="reason">${esc(c.reason)}</span></th>` +
      `<td class="n"><b>${fmt(c.value)}</b> <span class="unit">${esc(c.unit)}</span></td><td class="n">${fmt(c.baseline)}</td><td class="n">${pct(c.pct)}</td>` +
      `<td class="n">${fmt(c.mdc)}</td><td class="n">${c.pred == null ? "—" : fmt(c.pred) + (c.unexp ? '<span class="unexp">unexpected</span>' : "")}</td><td>${chip(c.status, c.label_s)}</td></tr>`).join("");
    $("[data-drawer-body]", drawer).innerHTML = `
      <header class="dr-h ${s.status}"><div><p class="cap">${esc(D.astronaut)} · mission day ${D.day}</p><h2 id="drawer-h">${esc(s.name)}</h2></div>
        <button class="x" type="button" data-close aria-label="Close details">${'<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>'}</button></header>
      <section class="dr-sec"><div class="dr-kpi"><b class="num">${s.score == null ? "—" : s.score.toFixed(0)}</b><span class="unit">/100</span>${chip(s.status, s.label)}${deltaHTML(s.score, s.prev, D.prevDay)}</div>
        <p class="dr-note">${esc(s.note)}</p></section>
      <section class="dr-sec"><h3>Score by mission day</h3>${scoreChart([dom], dom)}</section>
      <section class="dr-sec"><h3>Measurements today <span class="muted">(${cs.filter(c => c.flagged).length} of ${cs.length} flagged)</span></h3>
        ${cs.length ? `<div class="scroll"><table class="mtable"><thead><tr><th scope="col">Measurement</th><th scope="col" class="n">Today</th><th scope="col" class="n">Baseline</th><th scope="col" class="n">Change</th><th scope="col" class="n">Noise (MDC)</th><th scope="col" class="n">Shadow expected</th><th scope="col">Status</th></tr></thead><tbody>${rows}</tbody></table></div>`
          : '<p class="quiet">No checks for this system today.</p>'}</section>
      <section class="dr-sec"><h3>Alerts</h3>${alerts.length ? `<ol class="alist">${alerts.map((a, i) => `<li class="al ${a.tier}${i ? "" : " first"}">${chip(a.tier, a.label)}<span class="al-dom">${esc(a.dname)}</span><span class="al-t">${esc(a.time)}</span><p style="-webkit-line-clamp:unset">${esc(a.msg)}</p></li>`).join("")}</ol>` : `<p class="quiet">${sicon("ok")}No ${esc(s.name)} alerts today.</p>`}</section>
      <section class="dr-sec"><h3>Planned by the engine</h3>${plans.length ? `<ul class="plan">${plans.map(p => `<li><span class="when">Day ${p.day}</span><b>${esc(p.action)}</b>${p.note ? `<span class="muted">${esc(p.note)}</span>` : ""}</li>`).join("")}</ul>` : '<p class="quiet">No countermeasure planned for this system.</p>'}</section>
      <section class="dr-sec dr-foot"><a class="btn primary" href="#systems/${esc(dom)}" data-close>Open in Systems</a><a class="btn" href="#report" data-close>Open report</a></section>`;
    clearTimeout(closeT);                              // reopened mid-close: keep it open
    drawer.classList.remove("closing");
    if (!drawer.open) drawer.showModal();
    $("[data-close]", drawer)?.focus();
  }
  let closeT;
  function closeDrawer() {
    if (!drawer?.open || drawer.classList.contains("closing")) return;
    if (reduced) { drawer.close(); return; }
    drawer.classList.add("closing");
    closeT = setTimeout(() => { drawer.classList.remove("closing"); drawer.close(); }, 160);
  }
  drawer?.addEventListener("close", () => { if (opener && document.contains(opener)) opener.focus({ preventScroll: true }); opener = null; });
  drawer?.addEventListener("cancel", ev => { ev.preventDefault(); closeDrawer(); });
  drawer?.addEventListener("click", ev => {
    if (ev.target === drawer) { closeDrawer(); return; }           // backdrop
    const c = ev.target.closest("[data-close]");
    if (c) { if (c.tagName === "A") { opener = null; drawer.close(); } else closeDrawer(); }
  });

  /* ========== Systems: list + one focused system ========== */
  function showSystem(sub) {
    const arts = $$(".sys-art");
    if (!arts.length) return;
    const pick = arts.find(a => a.dataset.sys === sub) ||
      arts.find(a => a.dataset.sys === state.sel) ||
      arts.slice().sort((a, b) => (D?.sys[a.dataset.sys]?.score ?? 101) - (D?.sys[b.dataset.sys]?.score ?? 101))[0];
    arts.forEach(a => a.classList.toggle("on", a === pick));
    $$(".sn").forEach(n => n.setAttribute("aria-current", String(n.dataset.sys === pick.dataset.sys)));
  }
  document.addEventListener("click", ev => {
    const b = ev.target.closest(".seg [data-filter]");
    if (!b) return;
    const seg = b.closest(".seg"), view = document.getElementById(seg.dataset.filterFor);
    $$("button", seg).forEach(x => x.setAttribute("aria-pressed", String(x === b)));
    view.dataset.filter = b.dataset.filter;
  });

  /* ========== crew + day: swap the page in place ========== */
  // Only the newest request may swap the page: a quick run of clicks or held ← / → aborts the older fetches,
  // so a slow earlier answer can never land on top of a later one.
  let navSeq = 0, navCtl = null, navTarget = null;
  async function navigate(href, push = true) {
    const url = new URL(href, location.href);
    url.hash = location.hash;
    const seq = ++navSeq;
    navCtl?.abort();
    const ctl = navCtl = new AbortController();
    navTarget = url;
    const content = $(".content");
    content?.setAttribute("aria-busy", "true");
    const old = radarGeometry();
    try {
      const r = await fetch(url.pathname + url.search, { headers: { Accept: "text/html" }, signal: ctl.signal, cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const text = await r.text();
      if (seq !== navSeq) return;                        // a newer navigation started meanwhile
      const doc = new DOMParser().parseFromString(text, "text/html");
      // the server restarted with new code or new CSS / JS: load the page normally so everything matches
      if (doc.documentElement.dataset.build !== root.dataset.build || !$(".content", doc)) throw new Error("new build");
      const swap = () => {
        [".side", ".top", ".content"].forEach(s => { const n = $(s, doc), o = $(s); if (n && o) o.replaceWith(n); });
        $("#sd-data").textContent = $("#sd-data", doc)?.textContent || "null";
        document.title = doc.title;
        D = readData();
        initDynamic();
        route.done = false; route(); route.done = true;
        applySelection();
        morphRadar(old);
      };
      swap();
      if (push) history.pushState({ sd: 1 }, "", url.pathname + url.search + url.hash);
      $(".day.on")?.scrollIntoView({ block: "nearest", inline: "nearest" });
    } catch (err) {
      if (err?.name === "AbortError" || seq !== navSeq) return;   // replaced by a newer navigation
      location.href = url.href;                          // fallback: a normal page load
    } finally {
      if (seq === navSeq) { navTarget = null; $(".content")?.removeAttribute("aria-busy"); }
    }
  }
  // ← / → step from the day already on its way, so pressing → three times moves three days, not one
  function stepDay(dir) {
    const days = $$(".days a.day[data-day]");
    if (!days.length) return;
    const from = navTarget ? navTarget.searchParams.get("day") : $(".days a.day.on")?.dataset.day;
    const i = days.findIndex(a => a.dataset.day === from);
    const next = days[i < 0 ? -1 : i + dir];
    if (next) navigate(next.href);
  }
  function radarGeometry() {
    const r = $("[data-radar]");
    if (!r) return null;
    return { d: $(".cur-s", r)?.getAttribute("d"), v: $$(".vx", r).map(c => [c.dataset.dom, c.getAttribute("cx"), c.getAttribute("cy")]) };
  }
  function morphRadar(old) {
    // the two shapes are both real days; the 320ms tween only bridges them, it is not shown as data
    const r = $("[data-radar]");
    if (!old || !r || reduced) return;
    const paths = $$(".cur-s, .cur-f", r), dNew = paths[0]?.getAttribute("d");
    const sameShape = old.d && dNew && old.d.split(" ").length === dNew.split(" ").length;
    const vx = $$(".vx", r);
    const targets = vx.map(c => [c, c.getAttribute("cx"), c.getAttribute("cy")]);
    if (sameShape) paths.forEach(p => { p.style.transition = "none"; p.setAttribute("d", old.d); p.style.d = `path("${old.d}")`; });
    targets.forEach(([c]) => { const o = old.v.find(x => x[0] === c.dataset.dom); if (o) { c.style.transition = "none"; c.setAttribute("cx", o[1]); c.setAttribute("cy", o[2]); } });
    void r.offsetWidth;
    requestAnimationFrame(() => {
      if (sameShape) paths.forEach(p => { p.style.transition = ""; p.style.d = `path("${dNew}")`; p.setAttribute("d", dNew); });
      targets.forEach(([c, x, y]) => { c.style.transition = ""; c.setAttribute("cx", x); c.setAttribute("cy", y); });
    });
  }
  document.addEventListener("click", ev => {
    const a = ev.target.closest("a[data-nav]");
    if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button) return;
    ev.preventDefault();
    root.classList.remove("nav-open"); $("[data-scrim]").hidden = true;
    if (a.classList.contains("day-step")) stepDay(a.classList.contains("prev") ? -1 : 1);
    else navigate(a.href);
  });
  addEventListener("popstate", () => navigate(location.href, false));
  document.addEventListener("keydown", ev => {
    if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
    if (ev.altKey || ev.metaKey || ev.ctrlKey || drawer?.open) return;
    const t = ev.target;
    if (t.closest?.("input, select, textarea, .tabs, .trace-wrap, [contenteditable]")) return;
    ev.preventDefault();
    stepDay(ev.key === "ArrowLeft" ? -1 : 1);
  });

  /* ========== sidebar: collapse (desktop) + drawer (phone) ========== */
  document.addEventListener("click", ev => {
    if (ev.target.closest("[data-collapse]")) {
      const c = root.classList.toggle("side-collapsed");
      try { localStorage.setItem("shadow-side", c ? "collapsed" : "open"); } catch (e) { /* not remembered */ }
      $("[data-collapse]").setAttribute("aria-expanded", String(!c));
      setTimeout(moveIndicator, 220);
      return;
    }
    if (ev.target.closest("[data-menu]")) { setMenu(true); return; }
    if (ev.target.closest("[data-scrim]")) setMenu(false);
  });
  let navMove;
  function setMenu(open) {
    root.classList.add("nav-moving");                 // the slide runs only for this open / close
    clearTimeout(navMove); navMove = setTimeout(() => root.classList.remove("nav-moving"), 300);
    root.classList.toggle("nav-open", open);
    $("[data-scrim]").hidden = !open;
    $("[data-menu]")?.setAttribute("aria-expanded", String(open));
    if (open) ($(".side .crew.on") || $(".side a"))?.focus(); else $("[data-menu]")?.focus();
  }
  document.addEventListener("keydown", ev => { if (ev.key === "Escape" && root.classList.contains("nav-open")) setMenu(false); });
  // window widened past the phone layout with the menu open -> drop the menu state so no backdrop is left behind
  matchMedia("(max-width: 900px)").addEventListener("change", mq => {
    if (mq.matches || !root.classList.contains("nav-open")) return;
    root.classList.remove("nav-open", "nav-moving"); $("[data-scrim]").hidden = true;
    $("[data-menu]")?.setAttribute("aria-expanded", "false");
  });
  document.addEventListener("click", ev => { if (ev.target.closest(".side .tab") && root.classList.contains("nav-open")) setMenu(false); });

  /* ========== per-render bits (run again after every swap) ========== */
  function initDynamic() {
    if ($("[data-collapse]")) $("[data-collapse]").setAttribute("aria-expanded", String(!root.classList.contains("side-collapsed")));
    alertsUI.open = false;
    traces(); reportChart(); uploads(); manualEntry(); logFilter(); toastBox();
    if (!$(".tab-ind")) root.classList.add("no-ind");
  }

  function traces() {
    $$(".trace-wrap").forEach(wrap => {
      const pts = JSON.parse(wrap.dataset.pts || "[]"), unit = wrap.dataset.unit, W = +wrap.dataset.w, H = +wrap.dataset.h;
      const svg = $("svg", wrap), scan = $(".scan", svg), probe = $(".probe", svg), box = $(".readout", wrap);
      if (!pts.length) return;
      let cur = -1;
      const at = i => {
        cur = Math.max(0, Math.min(pts.length - 1, i));
        const [hr, v, x, y] = pts[cur];
        scan.setAttribute("x1", x); scan.setAttribute("x2", x); probe.setAttribute("cx", x); probe.setAttribute("cy", y);
        $("b", box).textContent = `${fmt(v, v < 10 ? 2 : 1)} ${unit}`;
        $("span", box).textContent = `${String(hr).padStart(2, "0")}:00 to ${String(hr + 1).padStart(2, "0")}:00`;
        box.hidden = false;
        const r = svg.getBoundingClientRect(), px = x / W * r.width, py = y / H * r.height;
        box.style.transform = `translate(${px > r.width - 140 ? px - box.offsetWidth - 12 : px + 12}px, ${Math.max(0, py - 44)}px)`;
        wrap.classList.add("probing");
      };
      const off = () => { wrap.classList.remove("probing"); box.hidden = true; cur = -1; };
      wrap.addEventListener("pointermove", ev => {
        const r = svg.getBoundingClientRect(), x = (ev.clientX - r.left) / r.width * W;
        let best = 0; pts.forEach((p, i) => { if (Math.abs(p[2] - x) < Math.abs(pts[best][2] - x)) best = i; });
        if (best !== cur) at(best);
      });
      wrap.addEventListener("pointerleave", () => { if (document.activeElement !== wrap) off(); });
      wrap.addEventListener("focus", () => at(cur < 0 ? pts.length - 1 : cur));
      wrap.addEventListener("blur", off);
      wrap.addEventListener("keydown", ev => {
        const step = { ArrowLeft: -1, ArrowRight: 1, Home: -1e9, End: 1e9 }[ev.key];
        if (step === undefined) { if (ev.key === "Escape") off(); return; }
        ev.preventDefault(); ev.stopPropagation();
        at(Math.abs(step) > 1 ? (step < 0 ? 0 : pts.length - 1) : cur + step);
      });
    });
  }

  function reportChart() {
    $$(".trend-legend").forEach(leg => {
      const chart = leg.nextElementSibling?.querySelector(".trend-chart");
      if (!chart) return;
      $$("[data-series-toggle]", leg).forEach(b => {
        const g = $(`[data-series="${b.dataset.seriesToggle}"]`, chart), lab = $(`[data-series-label="${b.dataset.seriesToggle}"]`, chart);
        b.addEventListener("click", () => {
          const on = b.getAttribute("aria-pressed") !== "true";
          b.setAttribute("aria-pressed", String(on)); g?.classList.toggle("off", !on); lab?.classList.toggle("off", !on);
        });
        const hot = on => { chart.classList.toggle("hl", on); g?.classList.toggle("hot", on); lab?.classList.toggle("hot", on); };
        b.addEventListener("pointerenter", () => hot(true)); b.addEventListener("pointerleave", () => hot(false));
        b.addEventListener("focus", () => hot(true)); b.addEventListener("blur", () => hot(false));
      });
    });
  }

  function manualEntry() {
    const form = $("form[data-validate]");
    if (!form) return;
    const metric = $("[data-metric]", form), input = $('input[name="value"]', form);
    const unit = $("[data-unit-label]", form), hint = $("[data-range]", form), err = $("#val-err", form);
    const opt = () => metric.selectedOptions[0];
    const sync = () => { const o = opt(); unit.textContent = o?.dataset.unit || ""; hint.textContent = o ? `Accepted range ${o.dataset.lo} to ${o.dataset.hi} ${o.dataset.unit}` : ""; };
    const check = () => {
      const raw = input.value.trim().replace(",", "."), o = opt();
      let msg = "";
      if (!raw) msg = "Enter a value.";
      else if (!/^-?\d*\.?\d+$/.test(raw)) msg = "The value must be a number, for example 2.4.";
      else if (o && (+raw < +o.dataset.lo || +raw > +o.dataset.hi)) msg = `Outside the accepted range (${o.dataset.lo} to ${o.dataset.hi} ${o.dataset.unit}). The engine would mark it bad quality.`;
      err.hidden = !msg; err.innerHTML = msg ? sicon("urgent") + esc(msg) : "";
      input.setAttribute("aria-invalid", msg ? "true" : "false");
      return !msg;
    };
    sync();
    metric.addEventListener("change", () => { sync(); if (input.value) check(); });
    input.addEventListener("blur", () => { if (input.value) check(); });
    input.addEventListener("input", () => { if (input.getAttribute("aria-invalid") === "true") check(); });
    form.addEventListener("submit", ev => { if (!check()) { ev.preventDefault(); ev.stopImmediatePropagation(); input.focus(); } }, true);
  }

  function logFilter() {
    const box = $("[data-log-filter]");
    if (!box) return;
    const lines = $$("[data-log-lines] .ln"), count = $("[data-log-count]");
    const run = () => {
      const q = box.value.trim().toLowerCase(); let n = 0;
      lines.forEach(l => { const hit = !q || l.textContent.toLowerCase().includes(q); l.hidden = !hit; n += hit; });
      count.textContent = q ? `${n} of ${lines.length} lines` : "";
    };
    box.addEventListener("input", run);
  }

  /* ---------- toast: dismiss, drop ?msg=, and show upload results inside their box ---------- */
  function toastBox() {
    const url = new URL(location.href);
    const box = url.searchParams.get("box");
    if (url.searchParams.has("msg")) {
      url.searchParams.delete("msg"); url.searchParams.delete("kind"); url.searchParams.delete("box");
      history.replaceState(history.state, "", url.pathname + (url.search || "") + url.hash);
      const t = $(".toast");
      if (t && box && $(`#box-${box} [data-upresult]`)) $(`#box-${box} [data-upresult]`).appendChild(t);
      else if (t && t.classList.contains("ok")) setTimeout(() => { t.style.transition = "opacity .25s"; t.style.opacity = "0"; setTimeout(() => t.remove(), 260); }, 7000);
    }
  }
  document.addEventListener("click", ev => { if (ev.target.closest("[data-dismiss]")) ev.target.closest(".toast")?.remove(); });

  /* ---------- busy overlay + confirms on every engine-running form (no duplicate runs) ---------- */
  const busy = $("#busy");
  function showBusy(text) { if (!busy) return; $("#busy-t").textContent = (text || "Working") + "…"; busy.hidden = false; }
  document.addEventListener("submit", ev => {
    const f = ev.target;
    if (f.classList.contains("upform") || ev.defaultPrevented) return;
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) { ev.preventDefault(); return; }
    const b = f.querySelector("button[data-busy]");
    showBusy(b ? b.dataset.busy : "Working");
    $$("button").forEach(x => { x.disabled = true; });
  });
  addEventListener("pageshow", ev => { if (ev.persisted && busy) { busy.hidden = true; $$("button").forEach(b => { b.disabled = false; }); } });

  /* ---------- CSV upload: one box per phase (click or drag-drop) ---------- */
  function uploads() {
    $$(".upform").forEach(form => {
      const input = $(".file", form), drop = $(".drop", form), nameEl = $(".dropname", form);
      const box = form.closest(".upbox"), st = $(".upstatus", box), btn = $(".upbtn", form);
      const empty = nameEl.textContent;
      const showName = () => {
        const f = input.files[0];
        nameEl.textContent = f ? `${f.name} · ${(f.size / 1024).toFixed(1)} KB` : empty;
        drop.classList.toggle("has", !!f);
      };
      input.addEventListener("change", showName);
      ["dragenter", "dragover"].forEach(t => drop.addEventListener(t, ev => { ev.preventDefault(); drop.classList.add("over"); }));
      ["dragleave", "drop"].forEach(t => drop.addEventListener(t, () => drop.classList.remove("over")));
      drop.addEventListener("drop", ev => { ev.preventDefault(); if (ev.dataTransfer?.files?.length) { input.files = ev.dataTransfer.files; showName(); } });
      form.addEventListener("submit", async ev => {
        ev.preventDefault();
        const f = input.files[0];
        if (!f) { st.textContent = "Choose a CSV file first."; drop.focus?.(); return; }
        if (!/\.csv$/i.test(f.name) && f.type !== "text/csv") { st.textContent = f.name + " is not a .csv file."; return; }
        btn.disabled = true; st.textContent = "Uploading " + f.name + "…";
        showBusy("Uploading " + f.name + " + re-running engine");
        try {
          const q = new URLSearchParams({ mode: $(".mode", form).value, name: f.name, section: form.dataset.section });
          const r = await fetch("/upload?" + q, { method: "POST", headers: { "Content-Type": "text/csv" }, body: await f.text() });
          const j = await r.json();
          const back = new URLSearchParams({ a: form.dataset.astronaut || "", day: new URL(location.href).searchParams.get("day") || "", kind: j.ok ? "ok" : "error", msg: j.msg, box: form.dataset.section });
          location.href = "/app?" + back + "#data";
        } catch (err) {
          if (busy) busy.hidden = true;
          st.textContent = "Upload failed: " + err; btn.disabled = false;
        }
      });
    });
  }

  /* ---------- print ---------- */
  document.addEventListener("click", ev => {
    if (!ev.target.closest("[data-print]")) return;
    if (location.hash.split("/")[0] !== "#report") location.hash = "report";
    setTimeout(() => print(), 60);
  });

  let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(moveIndicator, 120); });
  history.replaceState({ sd: 1 }, "", location.href);
  initDynamic();
  route();
  applySelection();
  document.fonts?.ready.then(moveIndicator);
})();
