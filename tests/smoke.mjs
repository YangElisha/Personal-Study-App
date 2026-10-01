#!/usr/bin/env node
/* Smoke test: the whole app in a real browser, every screen once.
     npm run smoke            (needs the Python .venv and Microsoft Edge or Chrome)
   Starts MonoSpace on a temporary, empty data folder with every AI switched off (nothing is sent
   anywhere), adds one small deck through the app itself, then opens every screen, starts every
   study mode and game, answers a question, and opens the panels. It fails on any error thrown in
   the page, any "Something went wrong" message, or a screen that doesn't show. Your real data
   folder is never touched. Set BROWSER=<path to msedge/chrome> if it isn't found. */
import { spawn } from "node:child_process";
import { mkdtempSync, mkdirSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import net from "node:net";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const sleep = ms => new Promise(r => setTimeout(r, ms));
const freePort = () => new Promise(res => { const s = net.createServer().listen(0, "127.0.0.1", () => { const p = s.address().port; s.close(() => res(p)); }); });
const python = [join(ROOT, ".venv", "Scripts", "python.exe"), join(ROOT, ".venv", "bin", "python")].find(existsSync) || "python";
const browser = [process.env.BROWSER, "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome", "/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].find(p => p && existsSync(p));
if (!browser) { console.error("No Edge or Chrome found — set BROWSER=<path>"); process.exit(2); }

const tmp = mkdtempSync(join(tmpdir(), "monospace-smoke-"));
mkdirSync(join(tmp, "data"));
const [port, debug] = [await freePort(), await freePort()];
const env = { ...process.env, DATA_DIR: join(tmp, "data"), PORT: String(port), CLAUDE_CLI: "off", ONLINE_AI: "off",
              LOCAL_AI: "off", OLLAMA_URL: "http://127.0.0.1:9", MONOSPACE_UPDATE_REPO: "" };
const server = spawn(python, ["-m", "server"], { cwd: ROOT, env, stdio: "ignore" });
const browserProc = spawn(browser, ["--headless=new", `--remote-debugging-port=${debug}`, `--user-data-dir=${join(tmp, "browser")}`,
  "--no-first-run", "--disable-extensions", "--window-size=1300,900", "about:blank"], { stdio: "ignore" });
let failures = 0;
const done = code => { try { server.kill(); browserProc.kill(); } catch {} setTimeout(() => { try { rmSync(tmp, { recursive: true, force: true }); } catch {} process.exit(code); }, 800); };

try {
  const base = `http://127.0.0.1:${port}/`;
  for (let i = 0; ; i++) { try { if ((await fetch(base + "api/health")).ok) break; } catch {} if (i > 100) throw new Error("server did not start"); await sleep(200); }
  let targets;
  for (let i = 0; ; i++) { try { targets = await (await fetch(`http://127.0.0.1:${debug}/json/list`)).json(); break; } catch {} if (i > 100) throw new Error("browser did not start"); await sleep(200); }
  const ws = new WebSocket(targets.find(t => t.type === "page").webSocketDebuggerUrl);
  await new Promise(r => ws.onopen = r);
  let id = 0; const pend = new Map(), errors = [];
  ws.onmessage = m => { const d = JSON.parse(m.data);
    if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); }
    else if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text); };
  const send = (method, params = {}) => new Promise(r => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async x => { const r = (await send("Runtime.evaluate", { expression: x, returnByValue: true, awaitPromise: true })).result;
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || "evaluation failed"); return r.result.value; };
  await send("Page.enable"); await send("Runtime.enable");
  const load = async () => {
    await send("Page.navigate", { url: base });
    for (let i = 0; i < 150; i++) { if (await ev('typeof LIB !== "undefined" && !!LIB').catch(() => false)) break; await sleep(200); }
    await ev('window.MonoSplash && MonoSplash.done(); document.getElementById("ms-splash")?.remove(); window.__toasts = []; const _t = toast; toast = m => { __toasts.push(String(m)); _t(m); }; true');
    await sleep(600);
  };
  const shown = () => ev('[...document.querySelectorAll("main section[id^=v-]")].filter(s => !s.classList.contains("hide")).map(s => s.id).join(",")');
  const step = async (name, js, expect) => {
    const before = errors.length;
    let problem = "";
    try { await ev(js); await sleep(700); } catch (e) { problem = e.message.split("\n")[0]; }
    const page = await shown().catch(() => "?");
    const bad = (await ev('__toasts.filter(t => /went wrong/i.test(t))').catch(() => [])).concat(errors.slice(before));
    await ev('__toasts.length = 0; true').catch(() => {});
    if (!problem && expect && !new RegExp(expect).test(page)) problem = `expected screen ${expect}, showing ${page || "none"}`;
    if (!problem && bad.length) problem = bad.join(" | ").slice(0, 300);
    console.log((problem ? "FAIL " : "ok   ") + name + (problem ? " — " + problem : ""));
    if (problem) failures++;
  };

  await load();
  // one small deck, made through the app's own storage, the way a build saves one
  await ev(`(async () => {
    const terms = [["Waterfall model","A plan-driven process where each phase finishes before the next starts."],
      ["Incremental development","Building the system in increments, each adding functionality, with feedback between them."],
      ["Software validation","Checking that the software is what the customer requires."],
      ["Software evolution","Changing the software to reflect changing customer and market requirements."],
      ["Prototyping","Building an initial version of a system to try out ideas and check requirements."],
      ["Requirements engineering","Finding out, analysing, documenting and checking the services a system must provide."]];
    const pairs = terms.map(([term, def]) => ({term, def}));
    const concepts = terms.map(([name, fact], i) => ({id:"c" + i, name, fact, topic:"Software processes", star:false,
      guide:"A plain-language explanation of " + name + ".", qs:questionsFromTerms(pairs, i)}));
    concepts[0].steps = ["Requirements", "Design", "Implementation", "Testing", "Maintenance"];
    const deck = {id:"smoke1", name:"Smoke test deck", concepts, cards:concepts.map(c => ({id:"k" + c.id, front:c.name, back:c.fact}))};
    await store.set("deck:smoke1", deck);
    LIB.folders.push({id:"f1", name:"Smoke subject", color:PALETTE[0]});
    LIB.decks.push({id:"smoke1", name:deck.name, folderId:"f1", created:Date.now(), nCon:concepts.length,
                    nQ:concepts.reduce((a, c) => a + c.qs.length, 0)});
    await store.set("library", LIB); return true; })()`);
  await load();

  await step("home", 'document.getElementById("nav-home").click()', "v-home");
  await step("library", 'document.getElementById("nav-library").click()', "v-library");
  await step("review", 'document.getElementById("nav-review").click()', "v-review");
  await step("new deck", 'document.getElementById("nav-new").click()', "v-new");
  await step("new deck: term list", 'document.querySelector("[data-src=terms]")?.click()', "v-new");
  await step("new deck: no-AI warning, cancelled", `(async () => { document.querySelector("[data-src=ai]")?.click();
    document.getElementById("n-name").value = "x"; document.getElementById("n-text").value = "Some notes.";
    const p = enqueueBuild(); await new Promise(r => setTimeout(r, 2500));
    if(!document.getElementById("modal").classList.contains("on")) throw new Error("no warning before building without AI");
    document.getElementById("m-cancel").click(); await p; if(QUEUE.length) throw new Error("built anyway"); })()`, "v-new");
  await step("settings", 'document.getElementById("nav-settings").click()', "v-settings");
  await step("settings: connect-AI panel", 'document.querySelector(".aiconnect").open = true', "v-settings");
  await step("appearance panel", 'document.getElementById("btn-custom").click()', "");
  await step("appearance closed", 'document.getElementById("btn-closecustom").click()', "");
  await step("backups", 'document.getElementById("nav-backups").click()', "v-backups");
  await step("deck", 'openDeck("smoke1")', "v-deck");
  for (const t of ["guide", "concepts", "cards", "manage", "overview"])
    await step("deck tab: " + t, `document.querySelector('[data-tab="${t}"]').click()`, "v-deck");
  await step("study: answer one question", `(async () => { viewMode = "focus"; document.getElementById("btn-study").click();
    await new Promise(r => setTimeout(r, 800));
    const card = S.cards.find(c => c.open); if(!card) throw new Error("no question shown");
    if(card.input){ card.input.value = "waterfall model"; card.btn.click(); }
    else (card.el.querySelector(".opts button") || card.el.querySelector(".ostep") || card.el.querySelector(".mm")).click();
    await new Promise(r => setTimeout(r, 300));
    const n = card.el.querySelector(".nextrow .btn"); if(n) n.click(); })()`, "v-study|v-report");
  await step("study: end", 'document.getElementById("btn-end")?.click()', "");
  await step("flashcards", 'openDeck("smoke1"); setTimeout(() => startCards(), 300)', "v-cards");
  await step("teach me", 'openDeck("smoke1"); setTimeout(() => openTeach(), 300)', "v-teach");
  await step("lesson", 'startLesson(lessons()[0])', "v-lesson");
  await step("lesson: next", 'document.getElementById("lesson-next").click()', "v-lesson");
  await step("sprint", 'openDeck("smoke1"); setTimeout(() => startSprint(), 300)', "v-sprint");
  await step("sprint: answer", 'document.querySelector("#sp-opts button")?.click()', "");
  await step("sprint: end", 'endSprint()', "");
  await step("matching", 'openDeck("smoke1"); setTimeout(() => startMatch(), 300)', "v-match");
  await step("defence game", 'openDeck("smoke1"); setTimeout(() => startShooter(), 300)', "v-shoot");
  await step("test paper setup", 'openDeck("smoke1"); setTimeout(() => openExamSetup(), 300)', "");
  await step("test paper", 'startExam()', "v-exam");
  await step("activity log", 'document.getElementById("nav-home").click(); openLog()', "v-home");
  await step("activity log closed", 'closeLog()', "v-home");
  await step("ask the teacher (opened, not sent)", 'openDeck("smoke1"); setTimeout(() => openChat(), 300)', "v-deck");
  await step("home again", 'closeChat(); document.getElementById("nav-home").click()', "v-home");
  ws.close();
} catch (e) {
  console.log("FAIL setup — " + e.message);
  failures++;
}
console.log(failures ? `\n${failures} problem(s)` : "\nAll screens fine");
done(failures ? 1 : 0);
