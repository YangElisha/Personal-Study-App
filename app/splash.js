/* MonoSpace loading screen.
 *
 * Load with <script src="splash.js"></script> early in <body> (styles: splash.css in <head>).
 * The overlay appears at once; call window.MonoSplash.done() when the app has booted (and on
 * boot errors). It stays at least MIN_MS so it never flashes, hides by itself after MAX_MS,
 * fades out in OUT_MS, then stops its animation loop and removes itself from the page.
 *
 *   MonoSplash.done()          hide (idempotent)
 *   MonoSplash.setStatus(txt)  change the pill text
 *
 * Canvas only; no external resources. Honours prefers-reduced-motion (one still frame).
 */
(function () {
  "use strict";
  if (window.MonoSplash) return;

  var MIN_MS = 10000, MAX_MS = 15000, OUT_MS = 600;   // shown ~10 s; a click or any key skips it
  var T0 = performance.now();
  var mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var still = !!(mq && mq.matches);
  var html = document.documentElement;

  // ---- markup ----------------------------------------------------------------------------
  var root = document.createElement("div");
  root.id = "ms-splash";
  root.setAttribute("aria-busy", "true");
  root.innerHTML =
    '<canvas class="ms-sky" aria-hidden="true"></canvas>' +
    '<div class="ms-stage">' +
      '<div class="ms-head">' +
        '<p class="ms-title" aria-label="MonoSpace">MONOSPACE</p>' +
        '<p class="ms-sub">Study smarter. Remember longer.</p>' +
      '</div>' +
      '<div class="ms-pill" role="status" aria-live="polite">' +
        '<span class="ms-dot" aria-hidden="true"></span><span class="ms-msg"></span>' +
      '</div>' +
    '</div>';
  root.querySelector(".ms-sub").textContent = "STUDY SMARTER. REMEMBER LONGER.";
  var msg = root.querySelector(".ms-msg");
  msg.textContent = "Loading your decks…";
  html.classList.add("ms-splashing");
  (document.body || html).appendChild(root);

  var canvas = root.querySelector("canvas");
  var ctx = canvas.getContext("2d");

  // ---- geometry: icosphere, 2 subdivisions (162 vertices, 480 edges) ----------------------
  var verts = [], edges = [];
  (function build() {
    var p = (1 + Math.sqrt(5)) / 2, mid = {}, i, j;
    var v = [[-1, p, 0], [1, p, 0], [-1, -p, 0], [1, -p, 0], [0, -1, p], [0, 1, p], [0, -1, -p],
             [0, 1, -p], [p, 0, -1], [p, 0, 1], [-p, 0, -1], [-p, 0, 1]];
    var f = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4],
             [11, 10, 2], [10, 7, 6], [7, 1, 8], [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8],
             [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
    function norm(a) { var l = Math.hypot(a[0], a[1], a[2]); return [a[0] / l, a[1] / l, a[2] / l]; }
    for (i = 0; i < v.length; i++) verts.push(norm(v[i]));
    function half(a, b) {
      var k = a < b ? a + "_" + b : b + "_" + a;
      if (mid[k] === undefined) {
        var A = verts[a], B = verts[b];
        verts.push(norm([(A[0] + B[0]) / 2, (A[1] + B[1]) / 2, (A[2] + B[2]) / 2]));
        mid[k] = verts.length - 1;
      }
      return mid[k];
    }
    for (j = 0; j < 2; j++) {
      var nf = [];
      for (i = 0; i < f.length; i++) {
        var a = f[i][0], b = f[i][1], c = f[i][2];
        var ab = half(a, b), bc = half(b, c), ca = half(c, a);
        nf.push([a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]);
      }
      f = nf;
    }
    var seen = {};
    for (i = 0; i < f.length; i++) {
      for (j = 0; j < 3; j++) {
        var s = f[i][j], t = f[i][(j + 1) % 3], key = s < t ? s + "_" + t : t + "_" + s;
        if (!seen[key]) { seen[key] = 1; edges.push(s, t); }
      }
    }
  })();
  var NV = verts.length, NE = edges.length / 2;
  var px = new Float32Array(NV), py = new Float32Array(NV), pz = new Float32Array(NV);

  // moons: orbit radius and size (x sphere radius), speed (rad/s), tilt, node, phase
  var moons = [
    { r: 0.62, s: 0.040, w: 0.42, tilt: 1.18, node: -0.35, ph: 0.8 },
    { r: 0.97, s: 0.047, w: 0.24, tilt: 1.32, node: 0.55, ph: 2.6 },
    { r: 0.80, s: 0.028, w: 0.33, tilt: 0.95, node: 2.30, ph: 4.4 },
    { r: 1.12, s: 0.036, w: 0.16, tilt: 1.42, node: -1.10, ph: 1.4 }
  ];
  var mbuf = moons.map(function () { return { x: 0, y: 0, z: 0, k: 1 }; });

  // ---- sizing, static background layer, sprites ------------------------------------------
  var W = 0, H = 0, DPR = 1, CX = 0, CY = 0, R = 0;
  var bg = null, halo = null, core = null, moonImg = null;

  function layer(w, h) {
    var c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(w)); c.height = Math.max(1, Math.round(h));
    return c;
  }

  function rng(seed) {
    return function () { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  }

  function resize() {
    W = window.innerWidth || html.clientWidth || 1024;
    H = window.innerHeight || html.clientHeight || 768;
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
    CX = W / 2; CY = H * 0.53; R = Math.min(W * 0.36, H * 0.45);

    // background: deep space, indigo glow behind the sphere, nebula haze, stars, horizon arc
    bg = layer(W * DPR, H * DPR);
    var g = bg.getContext("2d"), gr, i;
    g.scale(DPR, DPR);
    g.fillStyle = "#030306"; g.fillRect(0, 0, W, H);
    gr = g.createRadialGradient(CX, CY, 0, CX, CY, R * 1.25);
    gr.addColorStop(0, "rgba(34,32,86,.55)"); gr.addColorStop(0.55, "rgba(18,17,48,.45)");
    gr.addColorStop(1, "rgba(6,6,14,0)");
    g.fillStyle = gr; g.fillRect(0, 0, W, H);
    var rand = rng(20260929);
    var haze = [[0.73, 0.36, 0.26, "rgba(120,110,190,.07)"], [0.24, 0.72, 0.18, "rgba(128,70,190,.08)"],
                [0.57, 0.64, 0.2, "rgba(70,90,190,.06)"]];
    for (i = 0; i < haze.length; i++) {
      var hx = W * haze[i][0], hy = H * haze[i][1], hr = Math.max(W, H) * haze[i][2];
      gr = g.createRadialGradient(hx, hy, 0, hx, hy, hr);
      gr.addColorStop(0, haze[i][3]); gr.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = gr; g.fillRect(0, 0, W, H);
    }
    var nStars = Math.round(W * H / 5200);
    for (i = 0; i < nStars; i++) {
      var sx = rand() * W, sy = rand() * H, sr = rand() < 0.9 ? 0.5 + rand() * 0.5 : 0.9 + rand() * 0.5;
      g.fillStyle = "rgba(210,212,240," + (0.12 + rand() * 0.45).toFixed(2) + ")";
      g.beginPath(); g.arc(sx, sy, sr, 0, 6.2832); g.fill();
    }
    var AR = Math.max(W * 0.51, H * 0.62), ACY = AR + H * 0.012;
    g.lineWidth = 7; g.strokeStyle = "rgba(170,170,230,.045)";
    g.beginPath(); g.arc(CX, ACY, AR, 0, 6.2832); g.stroke();
    g.lineWidth = 1.3; g.strokeStyle = "rgba(196,196,228,.30)";
    g.beginPath(); g.arc(CX, ACY, AR, 0, 6.2832); g.stroke();
    gr = g.createRadialGradient(CX, H * 0.5, Math.min(W, H) * 0.45, CX, H * 0.5, Math.hypot(W, H) * 0.62);
    gr.addColorStop(0, "rgba(0,0,0,0)"); gr.addColorStop(1, "rgba(0,0,0,.55)");
    g.fillStyle = gr; g.fillRect(0, 0, W, H);

    // halo and core orb (drawn once, blitted each frame)
    var rc = R * 0.19, hr2 = rc * 1.9;
    halo = layer(hr2 * 2.4 * DPR, hr2 * 2.4 * DPR);
    g = halo.getContext("2d"); g.scale(DPR, DPR);
    var hc = hr2 * 1.2;
    gr = g.createRadialGradient(hc, hc, rc * 0.8, hc, hc, hr2 * 1.2);
    gr.addColorStop(0, "rgba(72,70,170,.50)"); gr.addColorStop(0.62, "rgba(52,50,140,.30)");
    gr.addColorStop(0.82, "rgba(40,38,110,.10)"); gr.addColorStop(1, "rgba(30,30,90,0)");
    g.fillStyle = gr; g.fillRect(0, 0, hc * 2, hc * 2);
    core = layer(rc * 3 * DPR, rc * 3 * DPR);
    g = core.getContext("2d"); g.scale(DPR, DPR);
    var cc = rc * 1.5;
    gr = g.createRadialGradient(cc, cc, rc * 0.9, cc, cc, rc * 1.5);
    gr.addColorStop(0, "rgba(186,182,250,.24)"); gr.addColorStop(1, "rgba(186,182,250,0)");
    g.fillStyle = gr; g.fillRect(0, 0, cc * 2, cc * 2);
    gr = g.createRadialGradient(cc - rc * 0.35, cc - rc * 0.4, rc * 0.05, cc, cc, rc);
    gr.addColorStop(0, "#cdcaf6"); gr.addColorStop(0.55, "#9c99d0"); gr.addColorStop(1, "#7a76b4");
    g.fillStyle = gr; g.beginPath(); g.arc(cc, cc, rc, 0, 6.2832); g.fill();

    // one silver moon sprite, scaled per moon
    var ms = 64;
    moonImg = layer(ms, ms);
    g = moonImg.getContext("2d");
    gr = g.createRadialGradient(ms * 0.4, ms * 0.36, ms * 0.04, ms / 2, ms / 2, ms / 2);
    gr.addColorStop(0, "#f1f1f6"); gr.addColorStop(0.6, "#c3c4cf"); gr.addColorStop(1, "#9d9eae");
    g.fillStyle = gr; g.beginPath(); g.arc(ms / 2, ms / 2, ms / 2 - 1, 0, 6.2832); g.fill();

    if (still) frame(T0 + 4000);
  }

  // ---- one frame -------------------------------------------------------------------------
  var BUCKETS = 9, paths = [];
  function frame(now) {
    var t = (now - T0) / 1000;
    var intro = still ? 1 : Math.min(1, t / 1.1);
    intro = 1 - Math.pow(1 - intro, 3);
    var rad = R * (0.93 + 0.07 * intro);
    var yaw = still ? 0.6 : 0.6 + t * 0.12;
    var pitch = 0.36 + (still ? 0 : 0.05 * Math.sin(t * 0.3));
    var cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
    var D = 3.4, i, k;

    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    ctx.globalAlpha = 1;
    ctx.drawImage(bg, 0, 0, W, H);

    for (i = 0; i < NV; i++) {
      var v = verts[i];
      var x = v[0] * cy + v[2] * sy, z = -v[0] * sy + v[2] * cy;
      var y = v[1] * cp - z * sp; z = v[1] * sp + z * cp;
      k = D / (D - z);
      px[i] = CX + x * rad * k; py[i] = CY + y * rad * k; pz[i] = z;
    }
    for (i = 0; i < moons.length; i++) {
      var m = moons[i], a = m.ph + (still ? 0 : t * m.w);
      var mx = Math.cos(a) * m.r, my = 0, mz = Math.sin(a) * m.r;
      var ct = Math.cos(m.tilt), st = Math.sin(m.tilt);
      var ty = my * ct - mz * st, tz = my * st + mz * ct;
      var cn = Math.cos(m.node), sn = Math.sin(m.node);
      var fx = mx * cn - ty * sn, fy = mx * sn + ty * cn;
      k = D / (D - tz);
      mbuf[i].x = CX + fx * rad * k; mbuf[i].y = CY + fy * rad * k; mbuf[i].z = tz; mbuf[i].k = k;
    }

    // moons behind the sphere
    drawMoons(false, rad, intro);
    // halo (slow pulse) and core
    var pulse = still ? 0 : Math.sin(t * 1.9);
    var hs = (1 + 0.045 * pulse) * (0.9 + 0.1 * intro);
    ctx.globalAlpha = (0.86 + 0.14 * pulse) * intro;
    var hw = halo.width / DPR * hs, hh = halo.height / DPR * hs;
    ctx.drawImage(halo, CX - hw / 2, CY - hh / 2, hw, hh);
    ctx.globalAlpha = intro;
    var cw = core.width / DPR * (0.94 + 0.06 * intro);
    ctx.drawImage(core, CX - cw / 2, CY - cw / 2, cw, cw);

    // wireframe: edges bucketed by depth, one path per opacity step
    for (i = 0; i < BUCKETS; i++) paths[i] = null;
    ctx.lineWidth = 0.9;
    for (i = 0; i < NE; i++) {
      var p = edges[2 * i], q = edges[2 * i + 1];
      var d = (pz[p] + pz[q]) * 0.25 + 0.5;               // 0 back .. 1 front
      var b = Math.min(BUCKETS - 1, Math.max(0, Math.floor(d * BUCKETS)));
      if (!paths[b]) paths[b] = [];
      paths[b].push(p, q);
    }
    for (b = 0; b < BUCKETS; b++) {
      var list = paths[b];
      if (!list) continue;
      var dd = (b + 0.5) / BUCKETS;
      ctx.globalAlpha = (0.07 + 0.5 * Math.pow(dd, 1.6)) * intro;
      ctx.strokeStyle = dd > 0.5 ? "#a9a8ee" : "#7d7cc8";
      ctx.beginPath();
      for (i = 0; i < list.length; i += 2) {
        ctx.moveTo(px[list[i]], py[list[i]]); ctx.lineTo(px[list[i + 1]], py[list[i + 1]]);
      }
      ctx.stroke();
    }
    // moons in front
    drawMoons(true, rad, intro);
    ctx.globalAlpha = 1;
  }

  function drawMoons(front, rad, intro) {
    for (var i = 0; i < moons.length; i++) {
      var o = mbuf[i];
      if ((o.z >= 0) !== front) continue;
      var r = moons[i].s * rad * o.k;
      ctx.globalAlpha = (front ? 0.95 : 0.55 + 0.4 * (1 + o.z / moons[i].r) / 2) * intro;
      ctx.drawImage(moonImg, o.x - r, o.y - r, r * 2, r * 2);
    }
  }

  // ---- loop, visibility, hide ------------------------------------------------------------
  var raf = 0, running = false, gone = false, hiding = false, doneAt = 0, safety = 0, doneTimer = 0;
  function loop(now) {
    if (!running) return;
    frame(now);
    raf = requestAnimationFrame(loop);
  }
  function start() {
    if (still || running || gone || document.hidden) return;
    running = true; raf = requestAnimationFrame(loop);
  }
  function stop() { running = false; if (raf) cancelAnimationFrame(raf); raf = 0; }
  function onVis() { if (document.hidden) stop(); else start(); }
  var resizeTimer = 0;
  function onResize() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (!gone) resize(); }, 60);
  }
  function onMotion() { still = !!(mq && mq.matches); if (still) { stop(); frame(T0 + 4000); } else start(); }

  function teardown() {
    if (gone) return;
    gone = true;
    stop();
    clearTimeout(safety); clearTimeout(doneTimer); clearTimeout(resizeTimer);
    window.removeEventListener("resize", onResize);
    document.removeEventListener("visibilitychange", onVis);
    if (mq) { if (mq.removeEventListener) mq.removeEventListener("change", onMotion); else if (mq.removeListener) mq.removeListener(onMotion); }
    if (root.parentNode) root.parentNode.removeChild(root);
    html.classList.remove("ms-splashing");
    canvas.width = canvas.height = 0;                       // free the backing stores
    bg = halo = core = moonImg = null;
  }
  function hide() {
    if (hiding) return;
    hiding = true;
    clearTimeout(safety);
    root.setAttribute("aria-busy", "false");
    root.classList.add("ms-out");
    root.addEventListener("transitionend", function (e) { if (e.target === root) teardown(); });
    setTimeout(teardown, OUT_MS + 150);                     // in case transitionend never fires
  }
  function skip() {
    root.removeEventListener("click", skip);
    document.removeEventListener("keydown", skip, true);
    hide();
  }
  function done() {
    if (doneAt || hiding) return;
    doneAt = performance.now();
    doneTimer = setTimeout(hide, Math.max(0, MIN_MS - (doneAt - T0)));
  }

  window.MonoSplash = {
    done: done,
    setStatus: function (text) { if (!gone) msg.textContent = String(text); },
    get visible() { return !gone; }
  };

  window.addEventListener("resize", onResize);
  document.addEventListener("visibilitychange", onVis);
  if (mq) { if (mq.addEventListener) mq.addEventListener("change", onMotion); else if (mq.addListener) mq.addListener(onMotion); }
  safety = setTimeout(hide, MAX_MS);
  root.addEventListener("click", skip);
  document.addEventListener("keydown", skip, true);
  resize();
  if (!still) { frame(T0); start(); }
})();
