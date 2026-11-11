/* SHADOW SELF — landing page behaviour (served at /static/landing.js).
   Motion stack (vendored in static/vendor, pinned: GSAP 3.12.5 + ScrollTrigger, Lenis 1.1.13, Three.js r160 loaded on
   demand): Lenis is the one smooth-scroll engine.
   Hero: the featured crew member's five real system scores as a radar inside their "usual self" pentagon (100 on every
   system). Scrolling steps through the real mission days (each day snaps; the tween between two days is a transition,
   never shown as data), then tilts the camera to stack the days in time.
   Demo: the real dashboard in an iframe, read-only; a guided cursor plays one pass, then hands over the controls.
   Fallbacks: no JS -> server-drawn radar, everything visible. No WebGL / reduced motion -> the same static radar,
   no pinning, no smooth scroll, every section in its final state. CDN scripts missing -> the page still works. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const LD = (() => { try { return JSON.parse($("#ld-data").textContent); } catch (e) { return null; } })();
  const ORDER = ["radiation", "muscle", "bone", "sans", "cardio"];
  const LABEL = { ok: "Nominal", watch: "Watch", act: "Act", urgent: "Urgent" };
  const STATUS_HEX = { ok: 0x4FBF8A, watch: 0xE5AA42, act: 0xF07B47, urgent: 0xF2625F };
  const gsap = window.gsap, ST = window.ScrollTrigger;
  const motion = !reduced && !!gsap && !!ST;
  if (!LD) return;
  const A = LD.featured, CREW = LD.crew[A], DAYS = CREW.days;
  const dayData = d => CREW.by_day[d];
  const lowest = d => ORDER.filter(k => dayData(d).sys[k]).reduce((m, k) => (dayData(d).sys[k][0] < dayData(d).sys[m][0] ? k : m), ORDER[0]);

  /* ---------- headings: words rise; the heading keeps its full text as its accessible name ---------- */
  function split(el) {
    const text = el.textContent.trim();
    el.setAttribute("aria-label", text);
    el.innerHTML = text.split(/\s+/).map(w => `<span class="w" aria-hidden="true"><i>${w.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]))}</i></span>`).join(" ");
    return $$(".w > i", el);
  }

  /* ---------- smooth scroll (Lenis) wired to ScrollTrigger ---------- */
  let lenis = null;
  if (motion) gsap.registerPlugin(ST);
  if (motion && window.Lenis) {
    lenis = new window.Lenis({ duration: 1.1, smoothWheel: true });
    lenis.on("scroll", ST.update);
    gsap.ticker.add(t => lenis.raf(t * 1000));
    gsap.ticker.lagSmoothing(0);
  }
  document.addEventListener("click", ev => {
    const a = ev.target.closest('a[href^="#"]');
    if (!a) return;
    const target = a.getAttribute("href") === "#top" ? 0 : $(a.getAttribute("href"));
    if (target == null) return;
    ev.preventDefault();
    if (lenis) lenis.scrollTo(target, { offset: target === 0 ? 0 : -64 });
    else if (target === 0) scrollTo({ top: 0 });
    else target.scrollIntoView();
    if (target !== 0) { target.setAttribute("tabindex", "-1"); target.focus({ preventScroll: true }); }
  });

  /* ---------- nav: hairline once scrolled, current section marked ---------- */
  const nav = $("[data-nav]");
  const onScroll = () => nav.classList.toggle("scrolled", scrollY > 8);
  addEventListener("scroll", onScroll, { passive: true }); onScroll();
  const links = $$(".nav nav a");
  const io = new IntersectionObserver(es => es.forEach(en => {
    if (en.isIntersecting) links.forEach(l => l.classList.toggle("on", l.getAttribute("href") === "#" + en.target.id));
  }), { rootMargin: "-45% 0px -50% 0px" });
  links.forEach(l => { const s = $(l.getAttribute("href")); if (s) io.observe(s); });

  /* ---------- hero readout ---------- */
  const R = { day: $("[data-r-day]"), score: $("[data-r-score]"), status: $("[data-r-status]"), low: $("[data-r-low]"), marks: $$("[data-daymarks] li") };
  let shownDay = DAYS[DAYS.length - 1];
  function readout(d) {
    const x = dayData(d);
    R.day.textContent = d;
    R.status.className = "st " + (x.status || "none");
    R.status.textContent = LABEL[x.status] || "No data";
    R.low.textContent = "Lowest: " + LD.names[lowest(d)];
    R.marks.forEach(li => li.classList.toggle("on", +li.dataset.day === d));
    const from = +R.score.textContent || 0, to = x.overall ?? 0;
    if (motion) { const o = { v: from }; gsap.to(o, { v: to, duration: .45, ease: "power3.out", onUpdate: () => { R.score.textContent = Math.round(o.v); } }); }
    else R.score.textContent = Math.round(to);
  }

  /* ---------- hero WebGL (one job: the radar and its shadow) ---------- */
  const glBox = $("[data-gl]"), labelsBox = $("[data-axlabels]");
  const hero = { setDay: () => {}, setStack: () => {}, ready: false };
  async function startGL() {
    let THREE;
    try { THREE = await import("/static/vendor/three.module.min.js"); } catch (e) { return; }
    const canvas = document.createElement("canvas");
    let renderer;
    try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" }); } catch (e) { return; }
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    glBox.prepend(canvas);
    const scene = new THREE.Scene();
    const cam = new THREE.PerspectiveCamera(32, 1, .1, 200);
    const RAD = 2.6, GAP = 1.6;                              // world radius of 100; space between stacked days
    const root = new THREE.Group(); scene.add(root);
    const radarG = new THREE.Group(); root.add(radarG);
    const angle = i => -Math.PI / 2 + i * 2 * Math.PI / 5;
    const P = (i, r, z = 0) => new THREE.Vector3(Math.cos(angle(i)) * r, -Math.sin(angle(i)) * r, z);

    // stars: static field, far behind the radar
    { const n = 1400, pos = new Float32Array(n * 3);
      let s = 7; const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
      for (let i = 0; i < n; i++) { const th = rnd() * Math.PI * 2, ph = Math.acos(2 * rnd() - 1), r = 40 + rnd() * 60;
        pos.set([r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th), -Math.abs(r * Math.cos(ph)) - 10], i * 3); }
      const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0x9AA6BD, size: 1.4, sizeAttenuation: false, transparent: true, opacity: .55 }))); }

    const lineMat = (color, opacity, dashed) => dashed
      ? new THREE.LineDashedMaterial({ color, transparent: true, opacity, dashSize: .09, gapSize: .1 })
      : new THREE.LineBasicMaterial({ color, transparent: true, opacity });
    const loop = (pts, mat) => { const g = new THREE.BufferGeometry().setFromPoints(pts); const l = new THREE.LineLoop(g, mat); if (mat.isLineDashedMaterial) l.computeLineDistances(); return l; };

    // the shadow: usual self (100) dashed, zone rings at 75 / 50, spokes
    const shadow = loop([0, 1, 2, 3, 4].map(i => P(i, RAD)), lineMat(0x8C9AB4, .9, true)); radarG.add(shadow);
    [.75, .5].forEach(f => radarG.add(loop([0, 1, 2, 3, 4].map(i => P(i, RAD * f)), lineMat(0xE2EAF8, .12))));
    [0, 1, 2, 3, 4].forEach(i => { const g = new THREE.BufferGeometry().setFromPoints([P(i, 0), P(i, RAD)]); radarG.add(new THREE.Line(g, lineMat(0xE2EAF8, .08))); });

    // the live shape (morphs between real days)
    const vals = ORDER.map(k => (dayData(DAYS[0]).sys[k]?.[0] ?? 0) / 100);
    const fillGeo = new THREE.BufferGeometry(); fillGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(18 * 3), 3));
    const fill = new THREE.Mesh(fillGeo, new THREE.MeshBasicMaterial({ color: 0x3459E6, transparent: true, opacity: .2, side: THREE.DoubleSide, depthWrite: false }));
    const outGeo = new THREE.BufferGeometry(); outGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(5 * 3), 3));
    const outline = new THREE.LineLoop(outGeo, lineMat(0x9DB1FF, 1));
    const gapGeo = new THREE.BufferGeometry(); gapGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(10 * 3), 3));
    const gaps = new THREE.LineSegments(gapGeo, lineMat(0xE2EAF8, .35));
    const dotGeo = new THREE.CircleGeometry(.07, 24);
    const dots = ORDER.map(() => { const m = new THREE.Mesh(dotGeo, new THREE.MeshBasicMaterial({ color: 0x4FBF8A })); radarG.add(m); return m; });
    const live = new THREE.Group(); live.add(fill, outline, gaps); radarG.add(live);
    function shape(v) {
      const f = fillGeo.attributes.position.array, o = outGeo.attributes.position.array, gp = gapGeo.attributes.position.array;
      for (let i = 0; i < 5; i++) {
        const p = P(i, RAD * v[i], .002), q = P((i + 1) % 5, RAD * v[(i + 1) % 5], .002), s = P(i, RAD);
        f.set([0, 0, 0, p.x, p.y, p.z, q.x, q.y, q.z], i * 9);
        o.set([p.x, p.y, p.z], i * 3);
        gp.set([p.x, p.y, 0, s.x, s.y, 0], i * 6);
        dots[i].position.set(p.x, p.y, .004);
      }
      fillGeo.attributes.position.needsUpdate = outGeo.attributes.position.needsUpdate = gapGeo.attributes.position.needsUpdate = true;
      fillGeo.computeBoundingSphere();
    }
    shape(vals);

    // the stack: one layer per real day, separated in z once the camera tilts
    const stack = new THREE.Group(); radarG.add(stack);
    const layers = DAYS.map((d, j) => {
      const v = ORDER.map(k => (dayData(d).sys[k]?.[0] ?? 0) / 100);
      const g = new THREE.Group();
      const sh = new THREE.Shape(v.map((x, i) => { const p = P(i, RAD * x); return new THREE.Vector2(p.x, p.y); }));
      g.add(new THREE.Mesh(new THREE.ShapeGeometry(sh), new THREE.MeshBasicMaterial({ color: 0x3459E6, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false })));
      g.add(loop(v.map((x, i) => P(i, RAD * x)), lineMat(0x9DB1FF, 0)));
      g.add(loop([0, 1, 2, 3, 4].map(i => P(i, RAD)), lineMat(0x8C9AB4, 0, true)));
      stack.add(g); return g;
    });
    const pillarGeo = new THREE.BufferGeometry().setFromPoints([0, 1, 2, 3, 4].flatMap(i => [P(i, RAD, 0), P(i, RAD, 1)]));
    const pillars = new THREE.LineSegments(pillarGeo, lineMat(0x8C9AB4, 0)); stack.add(pillars);

    // labels: HTML, projected from the shadow's vertices
    labelsBox.innerHTML = ORDER.map(k => `<div class="ax-l" data-k="${k}"><b></b><span class="st"></span></div>`).join("");
    const labelEls = $$(".ax-l", labelsBox);
    const stackBox = document.createElement("div"); stackBox.className = "ax-labels stack-labels"; stackBox.setAttribute("aria-hidden", "true");
    stackBox.innerHTML = DAYS.map(d => { const x = dayData(d);
      return `<div class="ax-l day-l"><b>Day ${d} · ${Math.round(x.overall ?? 0)}</b><span class="st ${x.status || "none"}">${LABEL[x.status] || "No data"}</span></div>`; }).join("");
    labelsBox.after(stackBox);
    const dayEls = $$(".day-l", stackBox);
    function labelText(d) {
      ORDER.forEach((k, i) => { const s = dayData(d).sys[k]; const el = labelEls[i];
        $("b", el).textContent = `${LD.names[k]} ${s ? Math.round(s[0]) : "—"}`;
        const st = $(".st", el); st.className = "st " + (s?.[1] || "none"); st.textContent = LABEL[s?.[1]] || "No data"; });
    }

    // state, sizing, pointer
    const st = { morph: vals.slice(), stack: 0, px: 0, py: 0, tx: 0, ty: 0, dirty: true };
    let W = 0, H = 0, offX = 0, offY = 0, dist = 13.5;
    function size() {
      const r = glBox.getBoundingClientRect(); W = r.width; H = r.height;
      renderer.setSize(W, H, false); cam.aspect = W / H; cam.updateProjectionMatrix();
      const tanH = Math.tan(cam.fov * Math.PI / 360);
      if (W > 860) { dist = 13.5; offX = RAD * 1.05; offY = 0; }
      else {                                       // narrow: the radar fills the box reserved above the copy
        const box = Math.min(W * .86, 420), wpp = (RAD * 2.3) / box;        // world units per pixel
        dist = wpp * H / (2 * tanH); offX = 0;
        offY = (H / 2 - (76 + box / 2)) * wpp;
      }
      st.dirty = true;
    }
    size(); addEventListener("resize", size);
    const coarse = matchMedia("(pointer: coarse)").matches;
    let pRaf = 0;
    if (!coarse) addEventListener("pointermove", ev => {
      if (pRaf) return;
      pRaf = requestAnimationFrame(() => { pRaf = 0; st.tx = (ev.clientX / innerWidth - .5); st.ty = (ev.clientY / innerHeight - .5); });
    }, { passive: true });
    addEventListener("blur", () => { st.tx = st.ty = 0; });

    function colorDots(d) { ORDER.forEach((k, i) => dots[i].material.color.setHex(STATUS_HEX[dayData(d).sys[k]?.[1]] || 0x8D99AA)); }
    colorDots(DAYS[0]); labelText(DAYS[0]);

    const v3 = new THREE.Vector3();
    function frame() {
      st.px += (st.tx - st.px) * .06; st.py += (st.ty - st.py) * .06;
      const s = st.stack, e = s * s * (3 - 2 * s);
      // camera: top-down (the dashboard's radar) -> oblique (the days stacked in time)
      const tilt = e * 1.08, mid = (layers.length - 1) * GAP / 2;
      cam.position.set(st.px * .6, -dist * 1.04 * Math.sin(tilt) + st.py * .4, dist * Math.cos(tilt) + mid * e);
      cam.lookAt(0, 0, mid * e);
      root.position.x = offX * (1 - e * .35); root.position.y = offY;
      radarG.rotation.z = st.px * .06 * (1 - e) + e * .5;
      shape(st.morph);
      live.visible = dots[0].visible = e < .98;
      dots.forEach(d => { d.visible = e < .98; d.material.opacity = 1 - e; d.material.transparent = true; });
      fill.material.opacity = .2 * (1 - e); outline.material.opacity = 1 - e; gaps.material.opacity = .35 * (1 - e);
      layers.forEach((g, j) => {
        const n = layers.length, age = (n - 1 - j) / Math.max(1, n - 1);
        g.position.z = e * j * GAP;
        g.children[0].material.opacity = e * (.06 + .16 * (1 - age));
        g.children[1].material.opacity = e * (.45 + .55 * (1 - age));
        g.children[2].material.opacity = e * .35;
      });
      pillars.scale.z = Math.max(.001, (layers.length - 1) * GAP * e);
      pillars.material.opacity = e * .3;
      renderer.render(scene, cam);
      // labels follow the shadow vertices while the view is top-down
      const rect = glBox.getBoundingClientRect();
      stackBox.style.opacity = W > 560 ? String(Math.max(0, (e - .6) / .4)) : "0";
      if (e > .6 && W > 560) layers.forEach((g, j) => {
        v3.copy(P(1, RAD * 1.08, 0)); v3.applyMatrix4(g.matrixWorld); v3.project(cam);
        dayEls[j].style.transform = `translate(${(v3.x * .5 + .5) * rect.width + 16}px, ${(-v3.y * .5 + .5) * rect.height}px) translate(0, -50%)`;
      });
      const show = e < .5 && W > 560;
      labelsBox.style.opacity = show ? String(1 - e * 2) : "0";
      if (show) {
        ORDER.forEach((k, i) => {
          v3.copy(P(i, RAD * 1.2)); v3.applyMatrix4(radarG.matrixWorld); v3.project(cam);
          labelEls[i].style.transform = `translate(${(v3.x * .5 + .5) * rect.width}px, ${(-v3.y * .5 + .5) * rect.height}px) translate(-50%, -50%)`;
        });
      }
    }
    // render only while the hero is on screen and the tab is visible
    let on = true, raf = 0;
    const tick = () => { raf = 0; if (!on || document.hidden) return; frame(); raf = requestAnimationFrame(tick); };
    const start = () => { if (!raf) raf = requestAnimationFrame(tick); };
    new IntersectionObserver(([en]) => { on = en.isIntersecting; if (on) start(); }).observe(glBox);
    document.addEventListener("visibilitychange", start);
    canvas.addEventListener("webglcontextlost", ev => { ev.preventDefault(); on = false; canvas.remove(); glBox.classList.remove("live"); labelsBox.innerHTML = ""; });
    glBox.classList.add("live");
    start();

    hero.setDay = d => {
      const to = ORDER.map(k => (dayData(d).sys[k]?.[0] ?? 0) / 100);
      gsap.to(st.morph, { ...to, duration: .7, ease: "power3.inOut", overwrite: true });
      colorDots(d); labelText(d);
    };
    hero.setStack = v => { st.stack = v; };
    hero.ready = true;
    hero.setDay(shownDay);
  }

  /* ---------- hero scroll: real days, then the stack ---------- */
  const heroStage = $("[data-hero]");
  if (motion) {
    shownDay = DAYS[0]; readout(shownDay);
    const words = split($("#hero-h"));
    gsap.from(words, { yPercent: 70, opacity: 0, duration: .9, ease: "power3.out", stagger: .045, delay: .1 });
    gsap.from(".readout, .hero-key", { opacity: 0, y: 8, duration: .8, ease: "power2.out", delay: .5 });
    startGL();
    const DAYS_END = .62;
    ST.create({
      trigger: heroStage, start: "top top", end: () => "+=" + innerHeight * (DAYS.length * .6 + 1.1), pin: true, scrub: true,
      onUpdate(self) {
        const p = self.progress;
        const idx = Math.min(DAYS.length - 1, Math.floor((p / DAYS_END) * DAYS.length));
        const d = DAYS[idx];
        if (d !== shownDay) { shownDay = d; readout(d); hero.setDay(d); }
        hero.setStack(Math.max(0, Math.min(1, (p - DAYS_END) / (1 - DAYS_END - .06))));
      },
    });
    gsap.to(".hero-copy, .readout, .hero-key, .scroll-cue", { opacity: 0, ease: "none",
      scrollTrigger: { trigger: heroStage, start: () => "top+=" + innerHeight * (DAYS.length * .6 + .7) + " top", end: () => "+=" + innerHeight * .4, scrub: true } });
  }

  /* ---------- section headings + drawn graphics ---------- */
  if (motion) {
    $$("main section:not(.hero) [data-split]").forEach(h => {
      const w = split(h);
      gsap.from(w, { yPercent: 60, opacity: 0, duration: .8, ease: "power3.out", stagger: .04, scrollTrigger: { trigger: h, start: "top 85%", once: true } });
    });
    const fig = $("[data-draw]");
    if (fig) {
      fig.classList.add("armed");
      const tl = gsap.timeline({ scrollTrigger: { trigger: fig, start: "top 75%", once: true } });
      tl.to($(".line", fig), { strokeDashoffset: 0, duration: 1.4, ease: "power2.inOut" })
        .to($$(".pt", fig), { opacity: 1, duration: .35, stagger: .45, ease: "power2.out" }, .1);
    }
    const sheet = $("[data-sheet]");
    if (sheet) {
      sheet.classList.add("armed");
      const tl = gsap.timeline({ scrollTrigger: { trigger: sheet, start: "top 80%", end: "center 55%", scrub: .6 } });
      tl.to($$(".d", sheet), { strokeDashoffset: 0, ease: "none", stagger: .02, duration: .5 })
        .to($$("text, .hatch, .pin, .dot", sheet), { opacity: 1, ease: "none", stagger: .005, duration: .2 }, ">-0.3");
    }
    $$(".steps li").forEach((li, i) => gsap.fromTo(li, { "--p": 0 }, { "--p": 1, ease: "none",
      scrollTrigger: { trigger: ".steps", start: `top ${78 - i * 6}%`, end: `top ${58 - i * 6}%`, scrub: true } }));
    addEventListener("load", () => ST.refresh());
    document.fonts?.ready.then(() => ST.refresh());
  } else {
    readout(shownDay);
  }

  /* ---------- the live demo ---------- */
  const vp = $("[data-viewport]"), frameEl = $("iframe", vp), shield = $("[data-shield]"), cursor = $("[data-cursor]"), caption = $("[data-caption]");
  const beats = $$("[data-beat]");
  let scale = 1, tourId = 0, played = false;
  function fit() {
    const cw = vp.clientWidth;
    if (cw >= 900) { scale = cw / 1440; vp.style.setProperty("--fw", "1440px"); vp.style.setProperty("--fh", "900px"); vp.style.setProperty("--vh", 900 * scale + "px"); }
    else { scale = 1; vp.style.setProperty("--fw", cw + "px"); vp.style.setProperty("--fh", "760px"); vp.style.setProperty("--vh", "760px"); }
    vp.style.setProperty("--s", scale);
  }
  fit(); addEventListener("resize", fit);
  const startUrl = frameEl.dataset.src;
  const doc = () => { try { return frameEl.contentDocument; } catch (e) { return null; } };
  function guard() {
    // read-only demo: forms (add, undo, upload, run, reset) never leave the iframe
    const w = frameEl.contentWindow; if (!w || w.__sdGuard) return; w.__sdGuard = true;
    w.addEventListener("submit", ev => { ev.preventDefault(); ev.stopImmediatePropagation(); say("Read-only in the demo. Open the full dashboard to change data.", 2600); }, true);
  }
  let sayT;
  function say(text, ms) { caption.textContent = text; caption.classList.add("on"); clearTimeout(sayT); if (ms) sayT = setTimeout(() => caption.classList.remove("on"), ms); }
  function beat(i) { beats.forEach((b, j) => { b.classList.toggle("on", j === i); b.classList.toggle("done", j < i); }); }
  const sleep = (ms, id) => new Promise((res, rej) => setTimeout(() => (id === tourId ? res() : rej("stopped")), ms));
  async function waitFor(sel, id, ms = 5000) {
    const t0 = performance.now();
    while (performance.now() - t0 < ms) { const el = doc()?.querySelector(sel); if (el) return el; await sleep(80, id); }
    throw "missing " + sel;
  }
  let cx = 40, cy = 40;
  function place(x, y) { cx = x; cy = y; cursor.style.transform = `translate(${x}px, ${y}px)`; }
  async function moveTo(el, id) {
    const r = el.getBoundingClientRect();
    const x = (r.left + r.width / 2) * scale, y = (r.top + r.height / 2) * scale;
    if (!motion) { place(x, y); return; }
    await new Promise(res => { const o = { x: cx, y: cy }; gsap.to(o, { x, y, duration: .9, ease: "power2.inOut", onUpdate: () => place(o.x, o.y), onComplete: res }); });
    if (id !== tourId) throw "stopped";
  }
  async function press(el, id) { cursor.classList.add("press"); await sleep(120, id); el.click(); cursor.classList.remove("press"); }
  function handOver(text = "Your turn. Everything in the window is live: click, select, switch days.") {
    tourId++;
    shield.hidden = true; cursor.hidden = true; beat(4); say(text, 4200);
    try { doc()?.querySelector("#drawer[open]") && doc().querySelector("#drawer [data-close]")?.click(); } catch (e) { /* closed already */ }
  }
  async function tour() {
    const id = ++tourId; played = true;
    shield.hidden = false; cursor.hidden = false; place(vp.clientWidth * .5, vp.clientHeight * .6);
    const first = DAYS[0], last = DAYS[DAYS.length - 1], low = lowest(last);
    const fx = dayData(first), lx = dayData(last), ls = lx.sys[low];
    try {
      const d = doc(); if (!d) throw "no doc";
      if (d.querySelector(".days a.day.on")?.dataset.day !== String(first)) { frameEl.contentWindow.location.href = startUrl; await sleep(900, id); await waitFor(".days a.day.on", id); }
      beat(0); say(`${A} on mission day ${first}: Shadow Score ${Math.round(fx.overall)}, ${LABEL[fx.status] || ""}.`); await sleep(2200, id);
      beat(1);
      const pill = await waitFor(`.days a.day[data-day="${last}"]`, id); await moveTo(pill, id); await press(pill, id);
      await waitFor(`.days a.day.on[data-day="${last}"]`, id);
      say(`Day ${last}: the shape folds in. ${LD.names[low]} is down to ${Math.round(ls[0])}.`); await sleep(2600, id);
      beat(2);
      const tile = await waitFor(`.stile[data-select="${low}"]`, id); await moveTo(tile, id); await press(tile, id);
      say(`Selecting ${LD.names[low]} filters the alerts, the activities and the trend to it.`); await sleep(2600, id);
      beat(3);
      const det = await waitFor("[data-open-drawer]:not([hidden])", id); await moveTo(det, id); await press(det, id);
      say("Every check behind the score: today's value, its baseline, its noise and what the shadow expected."); await sleep(3400, id);
      const close = doc()?.querySelector("#drawer [data-close]"); if (close) { await moveTo(close, id); await press(close, id); }
      await sleep(500, id);
      handOver();
    } catch (err) { if (err !== "stopped" && id === tourId) handOver("Your turn. The window is live."); }
  }
  shield.addEventListener("pointerdown", () => handOver());
  $("[data-tour-skip]").addEventListener("click", () => handOver());
  $("[data-tour-replay]").addEventListener("click", () => { if (frameEl.src) tour(); });
  frameEl.addEventListener("load", () => { guard(); fit(); if (!played && inView && !reduced) tour(); });
  let inView = false;
  new IntersectionObserver(([en]) => {
    if (en.isIntersecting && !frameEl.src) frameEl.src = startUrl;
  }, { rootMargin: "800px 0px" }).observe(vp);
  new IntersectionObserver(([en]) => {
    inView = en.isIntersecting;
    if (inView && !played && !reduced && doc()?.readyState === "complete" && doc()?.querySelector(".days")) tour();
  }, { threshold: .55 }).observe(vp);
  if (reduced) { beat(4); }
})();
