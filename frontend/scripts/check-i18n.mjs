// Check the translations against the source: `npm run i18n:check`.
//
// Finds every t("..."), msg("...") and translate("...") with a literal string in
// src/, then reports, per language: keys with no translation, translations no
// code uses any more, translations whose {placeholders} differ from the key, and
// keys defined in more than one file (shared words belong in common.json).
// Exits 1 when something is missing, mismatched or duplicated, so it can gate CI.
// A key must be one string literal: t("a" + "b") is only seen as "a".

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const src = join(root, "src");
const CALL = /\b(?:t|msg|translate)\(\s*(["'`])((?:\\.|(?!\1)[^\\])*)\1/g;
const PLACEHOLDER = /\{(\w+)\}/g;

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* files(path);
    // i18n.tsx itself only shows t() in its docs.
    else if (/\.tsx?$/.test(name) && name !== "i18n.tsx") yield path;
  }
}

function unescape(text, quote) {
  if (quote === "`" && text.includes("${")) return null; // not a fixed key
  return text.replace(/\\(.)/g, (_, char) => (char === "n" ? "\n" : char));
}

const used = new Map(); // key -> first file using it
for (const file of files(src)) {
  const code = readFileSync(file, "utf8");
  for (const match of code.matchAll(CALL)) {
    const key = unescape(match[2], match[1]);
    if (key !== null && !used.has(key)) used.set(key, relative(root, file));
  }
}

const placeholders = (text) => [...text.matchAll(PLACEHOLDER)].map((m) => m[1]).sort().join(",");

let failed = false;
const i18nDir = join(src, "i18n");
for (const language of readdirSync(i18nDir)) {
  const dir = join(i18nDir, language);
  if (!statSync(dir).isDirectory()) continue;
  const dictionary = {};
  const definedIn = {}; // key -> files defining it; the last file read wins at runtime
  for (const name of readdirSync(dir).filter((name) => name.endsWith(".json"))) {
    for (const [key, value] of Object.entries(JSON.parse(readFileSync(join(dir, name), "utf8")))) {
      dictionary[key] = value;
      (definedIn[key] ??= []).push(name);
    }
  }
  // One key in two files: the same English with two meanings, or a word for common.json.
  const duplicated = Object.entries(definedIn).filter(([, names]) => names.length > 1);
  const missing = [...used].filter(([key]) => !(key in dictionary));
  const unused = Object.keys(dictionary).filter((key) => !used.has(key));
  const mismatched = Object.entries(dictionary).filter(
    ([key, value]) => used.has(key) && placeholders(key) !== placeholders(value),
  );
  console.log(
    `${language}: ${used.size} keys, ${missing.length} missing, ${unused.length} unused, ` +
      `${mismatched.length} with other placeholders, ${duplicated.length} in several files`,
  );
  for (const [key, file] of missing) console.log(`  missing   ${JSON.stringify(key)}  (${file})`);
  for (const key of unused) console.log(`  unused    ${JSON.stringify(key)}`);
  for (const [key] of mismatched) console.log(`  mismatch  ${JSON.stringify(key)}`);
  for (const [key, names] of duplicated) {
    console.log(`  duplicate ${JSON.stringify(key)}  (${names.join(", ")})`);
  }
  if (missing.length || mismatched.length || duplicated.length) failed = true;
}
process.exit(failed ? 1 : 0);
