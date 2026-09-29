#!/usr/bin/env node
/**
 * Design-token guard. Run after `npm run build`.
 *
 * Parses the BUILT stylesheet (not the sources) so it sees exactly what ships,
 * resolves every var() chain, and asserts three things:
 *
 *   1. no token is unresolved or self-referential (the old `--bg: var(--bg)`),
 *   2. every text/background pair we care about clears WCAG AA (4.5:1) in
 *      BOTH themes,
 *   3. tokens.css stays the only place declaring :root / html[data-theme].
 *
 * jsdom cannot compute custom properties, and headless browsers are not
 * available in CI here, so this static resolver is the substitute.
 *
 * Exit code 1 on any failure.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const assets = join(root, 'dist', 'assets');

let cssFile;
try {
  cssFile = readdirSync(assets).find((f) => /^index-.*\.css$/.test(f));
} catch {
  console.error('No dist/ found. Run `npm run build` first.');
  process.exit(1);
}
if (!cssFile) {
  console.error('No built index-*.css in dist/assets. Run `npm run build` first.');
  process.exit(1);
}
const css = readFileSync(join(assets, cssFile), 'utf8');

/* ---------- collect token blocks ---------- */
const dark = {};
const light = {};
const blockRe = /(:root|html\[data-theme=["']?light["']?\])\s*\{([^}]*)\}/g;
for (const m of css.matchAll(blockRe)) {
  const target = m[1] === ':root' ? dark : light;
  for (const d of m[2].matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+)/g)) {
    target[d[1]] = d[2].trim();
  }
}
const merged = { ...dark, ...light };

/* ---------- resolve var() chains ---------- */
function resolve(map, name, seen = new Set(), depth = 0) {
  if (seen.has(name) || depth > 12) return null; // cycle
  const v = map[name];
  if (v === undefined) return null;
  const m = /^var\((--[a-z0-9-]+)\)$/.exec(v.trim());
  return m ? resolve(map, m[1], new Set([...seen, name]), depth + 1) : v;
}

/* ---------- contrast ---------- */
const lin = (c) => {
  c /= 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
function luminance(hex) {
  let h = String(hex).trim().replace('#', '');
  if (h.length === 3) h = [...h].map((c) => c + c).join('');
  if (!/^[0-9a-f]{6}$/i.test(h)) return null;
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
function ratio(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  if (la === null || lb === null) return null;
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/* ---------- assertions ---------- */
const PAIRS = [
  ['--text-primary', '--surface-1'],
  ['--text-secondary', '--surface-1'],
  ['--text-muted', '--surface-1'],
  ['--text-muted', '--surface-2'],
  ['--text-secondary', '--bg'],
  ['--text-muted', '--bg'],
  ['--accent-text', '--surface-1'],
  ['--success-text', '--surface-1'],
  ['--danger-text', '--surface-1'],
  ['--warning-text', '--surface-1'],
  ['--info-text', '--surface-1'],
  ['--accent-contrast', '--accent'],
];
const AA = 4.5;
let failures = 0;

for (const [label, map] of [['DARK', dark], ['LIGHT', merged]]) {
  console.log(`\n${label} — WCAG AA (${AA}:1)`);
  for (const [fg, bg] of PAIRS) {
    const f = resolve(map, fg);
    const b = resolve(map, bg);
    const r = f && b ? ratio(f, b) : null;
    if (r === null) {
      console.log(`  UNRESOLVED  ${fg} on ${bg}`);
      failures++;
      continue;
    }
    const ok = r >= AA;
    if (!ok) failures++;
    console.log(
      `  ${ok ? 'pass' : 'FAIL'}  ${fg.padEnd(18)} on ${bg.padEnd(12)} ${r.toFixed(2).padStart(5)}  (${f} / ${b})`,
    );
  }
}

const broken = Object.keys(merged).filter((k) => resolve(merged, k) === null);
console.log(`\nUnresolved / cyclic tokens: ${broken.length ? broken.join(', ') : 'none'}`);
failures += broken.length;

/* ---------- single source of truth ---------- */
const srcDir = join(root, 'src');
function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)],
  );
}
// Only flag blocks that DECLARE custom properties. Theme-scoped component
// rules like `html[data-theme="light"] .sp-card { background: #fff }` are
// legitimate styling, not a competing palette.
const declaresTokens = (text) => {
  // Anchor on the selector itself. Requiring a preceding '}' is unsafe: the
  // global regex consumes it in an earlier match and silently skips blocks.
  const re = /(^|[};])[^{};]*?(:root|html\[data-theme=["']?\w+["']?\])\s*\{([^}]*)\}/g;
  for (const m of text.matchAll(re)) {
    const prefix = m[0].slice(0, m[0].indexOf(m[2])).replace(/^[};]/, '').trim();
    if (prefix) continue;            // compound selector -> component styling
    const body = m[3];
    const after = m[0].slice(m[0].indexOf(m[2]) + m[2].length, m[0].indexOf('{')).trim();
    if (after) continue;             // e.g. `html[data-theme="light"] .sp-card`
    if (/--[a-z0-9-]+\s*:/i.test(body)) return true;
  }
  return false;
};
const strays = walk(srcDir)
  .filter((f) => f.endsWith('.css') && !f.endsWith('tokens.css'))
  .filter((f) => declaresTokens(readFileSync(f, 'utf8')));
if (strays.length) {
  console.log(`\nFAIL token blocks outside tokens.css:\n  ${strays.join('\n  ')}`);
  failures += strays.length;
} else {
  console.log('Token blocks live only in tokens.css: pass');
}

console.log(failures === 0 ? '\nAll token checks passed.' : `\n${failures} check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
