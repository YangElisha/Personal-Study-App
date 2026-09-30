#!/usr/bin/env node
/* Every inline <script> in app/index.html must parse. The reader tests only load the reader's
   functions, so a syntax error anywhere else (which leaves the whole app blank) would slip past
   them. Usage: node tests/check-app-syntax.js [path/to/index.html] */
"use strict";
const fs = require("fs");
const vm = require("vm");
const file = process.argv[2] || "app/index.html";
const html = fs.readFileSync(file, "utf8");
const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
let bad = 0;
blocks.forEach((code, i) => {
  try { new vm.Script(code, {filename: file + " <script> #" + (i + 1)}); }
  catch (e) { bad++; console.error("FAIL " + file + " script #" + (i + 1) + ": " + e.message + "\n" + String(e.stack).split("\n").slice(0, 3).join("\n")); }
});
if (bad) process.exit(1);
console.log("PASS " + file + ": " + blocks.length + " inline scripts parse");
