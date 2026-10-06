/* MonoSpace loading screen (redesign 2.0, 2026-10-06).
 *
 * The logo builds itself: "M" and the accent cursor appear together (the app icon), the cursor
 * blinks once, then "onoSpace" comes out of the cursor while the M slides left — ending on the
 * wordmark "MonoSpace▌" from the header. The tagline and a status line follow.
 *
 * Load with <script src="splash.js"></script> early in <body> (styles: splash.css in <head>).
 * The overlay appears at once; call window.MonoSplash.done() when the app has booted (and on boot
 * errors). It stays at least MIN_MS so the animation is seen, hides by itself after MAX_MS, fades
 * out in OUT_MS, then removes itself.
 *
 *   MonoSplash.done()          hide (idempotent)
 *   MonoSplash.setStatus(txt)  change the status text
 *
 * Colours: the last theme the app used (saved by Theme.apply as localStorage "ms-splash"), else
 * the paper theme. No external resources. prefers-reduced-motion: the finished wordmark, no motion.
 */
(function () {
  "use strict";
  if (window.MonoSplash) return;

  var MIN_MS = 4800, MAX_MS = 12000, OUT_MS = 520;     // a click or any key skips it
  var T0 = performance.now();
  var mq = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var still = !!(mq && mq.matches);
  var html = document.documentElement;

  // ---- colours: the theme you last used ------------------------------------------------------
  var col = { bg: "#F2EDE4", ink: "#1B1916", ink2: "#6B645B", live: "#A35A2C" };
  try {
    var saved = JSON.parse(localStorage.getItem("ms-splash") || "null");
    if (saved && saved.bg && saved.ink && saved.live) col = saved;
  } catch (e) { /* storage blocked: paper colours */ }
  html.style.setProperty("--ms-bg", col.bg);
  html.style.setProperty("--ms-ink", col.ink);
  html.style.setProperty("--ms-ink2", col.ink2 || col.ink);
  html.style.setProperty("--ms-live", col.live);

  // ---- markup -------------------------------------------------------------------------------
  var root = document.createElement("div");
  root.id = "ms-splash";
  root.setAttribute("aria-busy", "true");
  root.innerHTML =
    '<div class="ms-stage">' +
      '<p class="ms-mark" aria-label="MonoSpace">' +
        '<span class="ms-m" aria-hidden="true">M</span>' +
        '<span class="ms-rest" aria-hidden="true"><span class="ms-rest-in"></span></span>' +
        '<span class="ms-caret" aria-hidden="true"></span>' +
      '</p>' +
      '<p class="ms-sub">Study smarter. Remember longer.</p>' +
      '<p class="ms-msg" role="status" aria-live="polite">Loading your decks…</p>' +
    '</div>';
  var restIn = root.querySelector(".ms-rest-in");
  "onoSpace".split("").forEach(function (ch) {
    var s = document.createElement("span");
    s.className = "ms-ch";
    s.textContent = ch;
    restIn.appendChild(s);
  });
  var mark = root.querySelector(".ms-mark"), m = root.querySelector(".ms-m"),
      rest = root.querySelector(".ms-rest"), caret = root.querySelector(".ms-caret"),
      sub = root.querySelector(".ms-sub"), msg = root.querySelector(".ms-msg"),
      chars = Array.prototype.slice.call(root.querySelectorAll(".ms-ch"));
  html.classList.add("ms-splashing");
  (document.body || html).appendChild(root);

  var anims = [], gone = false, hiding = false, doneAt = 0, doneTimer = 0, safety = 0, blink = 0;
  function play(el, frames, opts) {
    if (!el.animate) return null;
    var a = el.animate(frames, Object.assign({ fill: "both" }, opts));
    anims.push(a);
    return a;
  }
  var EASE = "cubic-bezier(.65,0,.35,1)", OUT = "cubic-bezier(.2,.7,.3,1)";

  function finished() {                       // the end state, without motion
    root.classList.add("ms-static");
    rest.style.width = "auto";
  }

  function run() {
    if (gone) return;
    var w = restIn.getBoundingClientRect().width;          // "onoSpace" in the real font
    if (still || !mark.animate || !w) { finished(); return; }
    // 1. the icon: M and the cursor arrive together, centred
    play(mark, [{ opacity: 0, transform: "translateY(10px) scale(.96)" },
                { opacity: 1, transform: "none" }], { duration: 520, easing: OUT });
    // 2. the cursor blinks once, as if about to type
    play(caret, [{ opacity: 1 }, { opacity: 1, offset: .3 }, { opacity: 0, offset: .32 },
                 { opacity: 0, offset: .66 }, { opacity: 1, offset: .68 }, { opacity: 1 }],
         { duration: 620, delay: 520 });
    // 3. "onoSpace" comes out of the cursor: the gap opens (the M moves left, the cursor right,
    //    the word stays centred) and each letter slides out from the cursor's side
    var at = 1180, dur = 1050;
    play(rest, [{ width: "0px" }, { width: w + "px" }], { duration: dur, delay: at, easing: EASE });
    // a soft edge where the letters come into view next to the M, only while they move
    rest.style.webkitMaskImage = rest.style.maskImage = "linear-gradient(to right, transparent 0, #000 .3em)";
    setTimeout(function () { if (!gone) rest.style.webkitMaskImage = rest.style.maskImage = ""; }, at + dur);
    chars.forEach(function (c, i) {
      var k = chars.length - 1 - i;                        // nearest the cursor first
      play(c, [{ opacity: 0, transform: "translateX(.55em)" }, { opacity: 1, transform: "none" }],
           { duration: 520, delay: at + 140 + k * 55, easing: OUT });
    });
    play(m, [{ transform: "none" }, { transform: "translateX(-.02em)" }, { transform: "none" }],
         { duration: dur, delay: at, easing: EASE });
    // 4. the tagline and the status, then the cursor keeps blinking like a terminal
    play(sub, [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }],
         { duration: 600, delay: at + dur - 120, easing: OUT });
    play(msg, [{ opacity: 0 }, { opacity: 1 }], { duration: 500, delay: at + dur + 250 });
    blink = setTimeout(function () {
      if (gone) return;
      play(caret, [{ opacity: 1 }, { opacity: 1, offset: .5 }, { opacity: 0, offset: .52 },
                   { opacity: 0, offset: .98 }, { opacity: 1 }], { duration: 1060, iterations: Infinity });
    }, at + dur + 400);
  }

  // wait for the wordmark's font (Schibsted Grotesk) so the word is measured in it; at most 700 ms
  var started = false;
  function go() { if (!started) { started = true; run(); } }
  try {
    if (document.fonts && document.fonts.load) {
      document.fonts.load('800 64px "Schibsted Grotesk"').then(go, go);
      setTimeout(go, 700);
    } else go();
  } catch (e) { go(); }

  // ---- leaving --------------------------------------------------------------------------------
  function teardown() {
    if (gone) return;
    gone = true;
    clearTimeout(safety); clearTimeout(doneTimer); clearTimeout(blink);
    anims.forEach(function (a) { try { a.cancel(); } catch (e) {} });
    if (mq) { if (mq.removeEventListener) mq.removeEventListener("change", onMotion); else if (mq.removeListener) mq.removeListener(onMotion); }
    if (root.parentNode) root.parentNode.removeChild(root);
    html.classList.remove("ms-splashing");
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
  function onMotion() {
    still = !!(mq && mq.matches);
    if (still) { anims.forEach(function (a) { try { a.finish(); } catch (e) {} }); finished(); }
  }

  window.MonoSplash = {
    done: done,
    setStatus: function (text) { if (!gone) msg.textContent = String(text); },
    get visible() { return !gone; }
  };

  if (mq) { if (mq.addEventListener) mq.addEventListener("change", onMotion); else if (mq.addListener) mq.addListener(onMotion); }
  safety = setTimeout(hide, MAX_MS);
  root.addEventListener("click", skip);
  document.addEventListener("keydown", skip, true);
})();
