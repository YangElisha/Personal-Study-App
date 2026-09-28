"use strict";
/*
 * Pulls the slide reader out of the app's HTML at runtime and loads it into an
 * isolated JavaScript context (no DOM, no network, no Node globals).
 *
 * Nothing is copied into the tests: the functions are read from the HTML file every
 * run, so the tests always check the code the app actually ships.
 *
 * How it works:
 *   1. Take every inline <script> block from the HTML.
 *   2. Index the top-level declarations (`function x(`, `async function x(`,
 *      `const|let|var x =`). In this app every top-level statement starts at column 0
 *      and everything inside a block is indented.
 *   3. For each declaration, take the shortest run of lines starting at it that
 *      compiles on its own and is not continued on the next (indented) line.
 *   4. Starting from the requested roots, follow every identifier that names another
 *      top-level declaration, until nothing new is found.
 *   5. Evaluate the collected declarations, in their original order, in a fresh
 *      vm context and hand back the requested functions.
 */
const fs = require("fs");
const vm = require("vm");

const DECL = /^(?:async\s+function\s*\*?|function\s*\*?)\s*([A-Za-z_$][\w$]*)\s*\(|^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=/;
// a line that carries on the statement above it
const CONTINUES = /^(?:\s|[.?:+\-*\/&|,=)\]}])/;

function inlineScripts(html){
  const out = [];
  const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
  let m;
  while((m = re.exec(html))){
    if(/\bsrc\s*=/.test(m[1])) continue;
    out.push(m[2]);
  }
  return out;
}

function compiles(code){
  try { new vm.Script(code); return true; }
  catch(e){ if(e instanceof SyntaxError) return false; throw e; }
}

function indexDeclarations(scripts){
  const decls = new Map();    // name -> {name, code, script, line}
  const dupes = new Set();
  let order = 0;
  scripts.forEach((src, si) => {
    const lines = src.split("\n");
    for(let i = 0; i < lines.length; i++){
      const m = lines[i].match(DECL);
      if(!m) continue;
      const name = m[1] || m[2];
      let end = -1;
      for(let j = i; j < lines.length; j++){
        const next = lines.slice(j + 1).find(l => l.trim() !== "");
        if(next !== undefined && CONTINUES.test(next)) continue;
        if(compiles(lines.slice(i, j + 1).join("\n"))){ end = j; break; }
      }
      if(end < 0) continue;   // not a real declaration (e.g. text inside a template string)
      if(decls.has(name)) dupes.add(name);
      decls.set(name, {name, code: lines.slice(i, end + 1).join("\n"), script: si, line: i, order: order++});
      i = end;
    }
  });
  return {decls, dupes};
}

function identifiersIn(code){
  // strip comments and string/template contents so words in text are not mistaken for code
  const stripped = code
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/(^|[^:\\])\/\/[^\n]*/g, "$1 ")
    .replace(/"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'/g, '""')
    .replace(/`(?:[^`\\$]|\\.|\$(?!\{))*`/g, '""');
  const ids = new Set();
  const re = /(^|[^.\w$])([A-Za-z_$][\w$]*)(?!\s*:(?!:))/g;
  let m;
  while((m = re.exec(stripped))) ids.add(m[2]);
  // Names the code declares for itself (locals, parameters) are not dependencies.
  // The first line is skipped so the declaration's own name is not counted.
  // If this ever hides a real dependency, the run fails with a ReferenceError —
  // it can never make the test pass by mistake.
  const body = stripped.split("\n").slice(1).join("\n");
  const own = new Set();
  const add = list => list.split(",").forEach(p => {
    const n = p.replace(/=.*$/s, "").replace(/[{}\[\].\s]/g, "").split(":").pop();
    if(/^[A-Za-z_$][\w$]*$/.test(n)) own.add(n);
  });
  let d;
  const declRe = /\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)/g;
  while((d = declRe.exec(body))) own.add(d[1]);
  const destructRe = /\b(?:const|let|var)\s*[{\[]([^}\]]*)[}\]]/g;
  while((d = destructRe.exec(body))) add(d[1]);
  const fnRe = /\bfunction\s*[\w$]*\s*\(([^)]*)\)/g;
  while((d = fnRe.exec(stripped))) add(d[1]);
  const arrow1 = /([A-Za-z_$][\w$]*)\s*=>/g;
  while((d = arrow1.exec(stripped))) own.add(d[1]);
  const arrowN = /\(([^()]*)\)\s*=>/g;
  while((d = arrowN.exec(stripped))) add(d[1]);
  const commaRe = /,\s*([A-Za-z_$][\w$]*)\s*=(?![=>])/g;      // const a = 1, b = 2
  while((d = commaRe.exec(body))) own.add(d[1]);
  const catchRe = /\bcatch\s*\(\s*([A-Za-z_$][\w$]*)/g;
  while((d = catchRe.exec(stripped))) own.add(d[1]);
  own.forEach(n => ids.delete(n));
  // a bare "$" is almost always a regex end-anchor; count it only when it is called
  if(ids.has("$") && !/(^|[^\w$.])\$\s*\(/.test(stripped)) ids.delete("$");
  return ids;
}

/**
 * @param {string} htmlPath  the app HTML to read
 * @param {string[]} roots   top-level names the caller needs
 * @param {object} globals   extra globals for the sandbox (e.g. a fake `window`)
 */
function extractReader(htmlPath, roots, globals){
  const html = fs.readFileSync(htmlPath, "utf8");
  const scripts = inlineScripts(html);
  if(!scripts.length) throw new Error("no inline <script> blocks found in " + htmlPath);
  const {decls, dupes} = indexDeclarations(scripts);

  const missing = roots.filter(r => !decls.has(r));
  if(missing.length) throw new Error("not found in " + htmlPath + ": " + missing.join(", "));

  const want = new Set(), queue = roots.slice();
  while(queue.length){
    const n = queue.shift();
    if(want.has(n)) continue;
    want.add(n);
    identifiersIn(decls.get(n).code).forEach(id => {
      if(id !== n && decls.has(id) && !want.has(id)) queue.push(id);
    });
  }
  const clash = [...want].filter(n => dupes.has(n));
  if(clash.length) throw new Error("declared more than once in " + htmlPath + ": " + clash.join(", "));

  const chosen = [...want].map(n => decls.get(n)).sort((a, b) => a.order - b.order);
  const code = chosen.map(d => d.code).join("\n\n") +
    "\n;({" + roots.map(r => JSON.stringify(r) + ":" + r).join(",") + "})";
  const ctx = vm.createContext(Object.assign({}, globals || {}));
  const api = vm.runInContext(code, ctx, {filename: htmlPath + " [extracted reader]"});
  // the source text of any top-level declaration, as written in the HTML (not evaluated)
  const sourceOf = name => decls.has(name) ? decls.get(name).code : null;
  return {api, names: chosen.map(d => d.name), scriptCount: scripts.length, declCount: decls.size, sourceOf};
}

module.exports = {extractReader};
