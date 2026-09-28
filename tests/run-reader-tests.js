#!/usr/bin/env node
"use strict";
/*
 * Slide-reader regression test.
 *
 *   node tests/run-reader-tests.js                                  (reads app/index.html)
 *   node tests/run-reader-tests.js --html legacy/drill-study-app.html  (any other HTML file)
 *
 * The default is the app as it ships (app/index.html). legacy/ is the frozen reference; it
 * still counts full-slide background images as pictures, so it fails the Module 3 fixture.
 *
 * The reader is read out of the HTML file at runtime (see lib/extract-reader.js) and run on
 * the saved pdf.js text layers in tests/fixtures/, in the app's own order:
 *   slidesFromUpload -> setAsideActivities -> auditSlides
 * (the last two are the opening statements of the app's resolveSlides). The terms left
 * after activity slides are set aside — what the student actually gets — must equal
 * tests/golden/ exactly: term names, topics, items, steps and pages. The slides set aside
 * as activities must equal the golden file's "setAside" list exactly (page, title, reason,
 * terms, in order); a golden file without "setAside" expects none. The self-check must
 * flag no slides. No network, no npm packages.
 *
 * Fixtures: Modules 2 and 3 are real text layers. synthetic-activity-text.json is hand-built
 * (invented text, see tests/fixtures/README.md) because neither module has an activity slide.
 *
 * Exit code: 0 = pass, 1 = the reader's output differs from golden, 2 = could not run.
 * A difference is a failure. Never "fix" it by editing the golden files; report it.
 */
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const {extractReader} = require("./lib/extract-reader");

const ROOT = path.resolve(__dirname, "..");
const DEFAULT_HTML = path.join(ROOT, "app", "index.html");
const MODULES = [
  {label: "Module 2", fixture: "module2-text.json", golden: "module2.expected.json"},
  {label: "Module 3", fixture: "module3-text.json", golden: "module3.expected.json"},
  {label: "Synthetic activity slide", fixture: "synthetic-activity-text.json", golden: "synthetic-activity.expected.json"},
];
const TERM_FIELDS = ["name", "topic", "items", "steps", "pages"];

// the pdf.js operator codes slidesFromUpload reads (values as in pdf.js 3.x)
const OPS = {save: 10, restore: 11, transform: 12, paintFormXObjectBegin: 74, paintFormXObjectEnd: 75,
             paintJpegXObject: 82, paintImageXObject: 85, paintInlineImageXObject: 86};

function parseArgs(argv){
  let html = DEFAULT_HTML;
  for(let i = 0; i < argv.length; i++){
    if(argv[i] === "--html" && argv[i + 1]){ html = path.resolve(argv[++i]); }
    else if(argv[i].startsWith("--html=")){ html = path.resolve(argv[i].slice(7)); }
    else { console.error("Unknown argument: " + argv[i] + "\nUsage: node tests/run-reader-tests.js [--html <path>]"); process.exit(2); }
  }
  return {html};
}

/* A saved page comes in one of these shapes:
     {items:[{str,transform}], imgs, view, images}   (modules 2 and 3, captured from the PDFs:
        imgs = number of image paint operations, view = page box [x0,y0,x1,y1],
        images = the drawing transform [a,b,c,d,e,f] in force at each image paint)
     {items:[{str,transform}], imgs}                 (synthetic: pictures without size)
     [{str,transform}, ...]                          (text only; imgs taken as 0) */
function pageOf(raw, n){
  if(Array.isArray(raw)) return {items: raw, imgs: 0};
  if(raw && Array.isArray(raw.items)){
    if(raw.images && raw.images.length !== raw.imgs)
      throw new Error("page " + n + " of the fixture: imgs is " + raw.imgs + " but " + raw.images.length + " image transforms are saved");
    return {items: raw.items, imgs: raw.imgs || 0, view: raw.view, images: raw.images};
  }
  throw new Error("page " + n + " of the fixture is neither {items, imgs} nor an items array");
}

/* A stand-in for a pdf.js document, built from a saved fixture. */
function fakeUpload(name, fixture){
  const nums = Object.keys(fixture).map(Number).sort((a, b) => a - b);
  const count = nums[nums.length - 1] || 0;
  return {
    name, size: 0, kind: "pdfpages", pages: count, range: "1-" + count,
    doc: {
      numPages: count,
      getPage: async n => {
        if(!(String(n) in fixture)) throw new Error("page " + n + " is not in the fixture");
        const pg = pageOf(fixture[String(n)], n);
        return {
          getTextContent: async () => ({items: pg.items}),
          view: pg.view,
          getOperatorList: async () => {
            // each saved image is replayed as save, transform, paint, restore, so the app's
            // own transform tracking decides whether it covers the whole page
            if(!pg.images){
              const n = pg.imgs || 0;
              return {fnArray: new Array(n).fill(OPS.paintImageXObject), argsArray: new Array(n).fill(null)};
            }
            const fnArray = [], argsArray = [];
            pg.images.forEach(m => { fnArray.push(OPS.save, OPS.transform, OPS.paintImageXObject, OPS.restore);
                                     argsArray.push(null, m, null, null); });
            return {fnArray, argsArray};
          },
        };
      },
    },
  };
}

const plain = v => JSON.parse(JSON.stringify(v));   // out of the sandbox, undefined fields dropped
const show = v => v === undefined ? "(none)" : JSON.stringify(v);
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function termView(c){
  const t = {};
  TERM_FIELDS.forEach(f => { if(c[f] !== undefined) t[f] = c[f]; });   // compared exactly, no tidying
  return t;
}

function compare(label, golden, got){
  const diffs = [];
  const top = (field, exp, act) => { if(!same(exp, act)) diffs.push(field + ": expected " + show(exp) + ", got " + show(act)); };
  top("pages", golden.pages, got.pages);
  top("contentSlides", golden.contentSlides, got.contentSlides);
  top("imageSlides", golden.imageSlides, got.imageSlides);
  top("skippedSlides", golden.skippedSlides, got.skippedSlides);
  top("term count", golden.terms.length, got.terms.length);

  const expNames = golden.terms.map(t => t.name), gotNames = got.terms.map(t => t.name);
  const missing = expNames.filter(n => !gotNames.includes(n));
  const extra = gotNames.filter(n => !expNames.includes(n));
  missing.forEach(n => diffs.push("missing term: " + show(n) + " (in golden, not produced)"));
  extra.forEach(n => {
    const t = got.terms.find(x => x.name === n);
    diffs.push("extra term: " + show(n) + " on page(s) " + show(t.pages) + " (produced, not in golden)");
  });

  golden.terms.forEach(exp => {
    const act = got.terms.find(t => t.name === exp.name);
    if(!act) return;
    TERM_FIELDS.forEach(f => {
      if(!same(exp[f], act[f])) diffs.push("term " + show(exp.name) + " -> " + f + ": expected " + show(exp[f]) + ", got " + show(act[f]));
    });
  });

  if(!missing.length && !extra.length && !same(expNames, gotNames)){
    const i = expNames.findIndex((n, k) => n !== gotNames[k]);
    diffs.push("term order differs at position " + (i + 1) + ": expected " + show(expNames[i]) + ", got " + show(gotNames[i]));
  }

  // the slides set aside as activities, exactly; no "setAside" in golden means none
  const expAside = golden.setAside || [];
  const asideKey = s => JSON.stringify([s.page, s.title, s.reason, s.terms]);
  const expKeys = expAside.map(asideKey), gotKeys = got.setAside.map(asideKey);
  let asideDiff = false;
  expAside.forEach((s, i) => { if(!gotKeys.includes(expKeys[i])){ asideDiff = true;
    diffs.push("slide " + s.page + " (" + show(s.title) + ") not set aside as expected: " + show(s.reason) + " — terms " + show(s.terms)); } });
  got.setAside.forEach((s, i) => { if(!expKeys.includes(gotKeys[i])){ asideDiff = true;
    diffs.push("slide " + s.page + " (" + show(s.title) + ") set aside, not in golden: " + show(s.reason) + " — terms " + show(s.terms)); } });
  if(!asideDiff && !same(expKeys, gotKeys))
    diffs.push("set-aside list differs (order or repeats): expected pages " + show(expAside.map(s => s.page)) + ", got " + show(got.setAside.map(s => s.page)));

  got.flags.forEach(f => diffs.push("self-check flagged slide " + f.page + " (" + show(f.title) + "): " + f.why.join("; ")));
  return diffs;
}

async function runModule(api, mod){
  const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", mod.fixture), "utf8"));
  const golden = JSON.parse(fs.readFileSync(path.join(__dirname, "golden", mod.golden), "utf8"));
  const u = fakeUpload(golden.source || mod.fixture, fixture);

  // the app's own path (see its upload handlers):
  //   let r = await slidesFromUpload(u, say);
  //   const res = await resolveSlides(u, r.pages, r, notes, say);
  // and resolveSlides opens with exactly these two statements (checked in main()):
  //   const early = [];
  //   setAsideActivities(pages, first, early);      // removes activity slides' terms from first.concepts
  //   const flags = auditSlides(pages, first).filter(f => !early.some(e => e.page === f.page));
  // With no flags, resolveSlides returns `first` as it now stands — those are the terms the
  // student gets. (With flags it would go on to ask the AI; the test fails before that.)
  const out = await api.slidesFromUpload(u);
  const early = [];
  api.setAsideActivities(out.pages, out, early);
  const flags = api.auditSlides(out.pages, out).filter(f => !early.some(e => e.page === f.page));

  const report = plain(out.report);
  const setAside = plain(early).map(e => ({page: e.page, title: e.title, reason: e.reason,
                                           terms: (e.concepts || []).map(c => c.name)}));
  const got = {
    pages: u.pages,
    contentSlides: report.filter(r => r.kind === "content").length,
    imageSlides: plain(out.textless),
    skippedSlides: report.filter(r => r.kind === "skipped").map(r => r.page),
    terms: plain(out.concepts).map(termView),      // after setAsideActivities
    setAside,
    setAsideTerms: setAside.reduce((n, s) => n + s.terms.length, 0),
    flags: plain(flags),
  };
  return {golden, got, diffs: compare(mod.label, golden, got)};
}

async function main(){
  const {html} = parseArgs(process.argv.slice(2));
  if(!fs.existsSync(html)){ console.error("HTML not found: " + html); process.exit(2); }
  const sha = crypto.createHash("sha256").update(fs.readFileSync(html)).digest("hex");
  console.log("Slide reader regression test");
  const rel = path.relative(ROOT, html);
  const shown = rel.startsWith("..") || path.isAbsolute(rel) ? html : rel;
  console.log("  HTML:    " + shown.replace(/\\/g, "/") + "  (sha256 " + sha.slice(0, 16) + "…)");

  const window = {pdfjsLib: {OPS}};
  const roots = ["toLines", "columnOrder", "parseSlides", "linkUmbrellas", "setAsideActivities", "auditSlides", "slidesFromUpload"];
  let ex;
  try { ex = extractReader(html, roots, {window}); }
  catch(e){ console.error("\nCould not extract the reader: " + e.message); process.exit(2); }
  console.log("  Reader:  " + ex.names.length + " declarations extracted: " + ex.names.join(", "));

  // runModule() reproduces the opening of the app's resolveSlides by hand (resolveSlides
  // itself goes on to the AI, so it is not run). Make sure the app still opens that way;
  // if it has changed, the test must be updated to match before it can be trusted.
  const squash = s => s.replace(/\s+/g, "");
  const OPENING = "async function resolveSlides(u, pages, first, notes, say){" +
    "const early = [];" +
    "setAsideActivities(pages, first, early);" +
    "const flags = auditSlides(pages, first).filter(f => !early.some(e => e.page === f.page));";
  const resolve = ex.sourceOf("resolveSlides");
  if(!resolve || !squash(resolve).startsWith(squash(OPENING))){
    console.error("\nThe app's resolveSlides no longer opens with setAsideActivities then auditSlides as this test");
    console.error("reproduces it. Update runModule() to match the app's new order, then re-run.");
    process.exit(2);
  }
  const calls = fs.readFileSync(html, "utf8").match(/resolveSlides\([^)]*\)/g) || [];
  const odd = calls.filter(c => !/^resolveSlides\(u, pages, first, notes, say\)$/.test(c) && !/^resolveSlides\(u, r\.pages, r,/.test(c));
  if(!calls.length || odd.length){
    console.error("\nThe app calls resolveSlides differently from what this test reproduces (" +
      "expected resolveSlides(u, r.pages, r, ...) on slidesFromUpload's result): " + odd.join(" | "));
    process.exit(2);
  }
  const sites = calls.filter(c => /^resolveSlides\(u, r\.pages, r,/.test(c)).length;
  if(!sites){ console.error("\nNo call to resolveSlides(u, r.pages, r, ...) found in the app."); process.exit(2); }
  console.log("  Order:   slidesFromUpload -> setAsideActivities -> auditSlides  (as in resolveSlides; " +
    sites + " call sites checked)");
  console.log("");

  let failed = 0;
  for(const mod of MODULES){
    let res;
    try { res = await runModule(ex.api, mod); }
    catch(e){ console.log("FAIL " + mod.label + ": the reader threw an error\n     " + (e.stack || e).toString().split("\n").slice(0, 4).join("\n     ")); failed++; continue; }
    const {golden, got, diffs} = res;
    const summary = got.terms.length + "/" + golden.terms.length + " terms after activity slides set aside (" +
      got.setAside.length + " slides, " + got.setAsideTerms + " terms set aside), " +
      got.contentSlides + " content slides, self-check flags: " + got.flags.length;
    if(diffs.length){
      failed++;
      console.log("FAIL " + mod.label + " (" + mod.fixture + " vs " + mod.golden + "): " + summary);
      diffs.forEach(d => console.log("     - " + d));
    } else {
      console.log("PASS " + mod.label + ": " + summary + "; names, topics, items, steps, pages and set-aside identical");
    }
    // what was set aside (asserted against golden "setAside" above; listed here for reading)
    got.setAside.forEach(s => console.log("     set aside: slide " + s.page + " (" + show(s.title) + "): " +
      s.reason + " — terms " + show(s.terms)));
  }
  console.log("");
  if(failed){
    console.log(failed + " of " + MODULES.length + " fixtures FAILED. Do not update tests/golden/ to make this pass;");
    console.log("report the difference and let Elisha decide whether the new reading is better.");
    process.exit(1);
  }
  console.log("All " + MODULES.length + " fixtures passed.");
}

main().catch(e => { console.error(e && e.stack || e); process.exit(2); });
