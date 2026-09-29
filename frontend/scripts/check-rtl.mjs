#!/usr/bin/env node
/**
 * RTL guard. Persian is the RTL locale, so a physical `left:` in a base rule
 * is a bug that only shows up for one language — exactly the kind that ships.
 *
 * The house rule: base rules use LOGICAL properties (`inset-inline-start`,
 * `margin-inline`, `text-align: start`), so direction flips for free.
 *
 * Two things are allowed:
 *   - physical properties inside an `html[dir="rtl"]` rule — that is what
 *     those blocks are for, when no logical equivalent exists (e.g. a
 *     direction-specific `transform`).
 *   - an `rtl-ok: <reason>` marker on the line or the line above, for a
 *     decoration that genuinely must not flip.
 *
 * A marker forces the reason to be written down, so an exception is a
 * decision rather than an oversight.
 *
 * Exit code 1 on any failure.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { join, dirname, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const srcDir = join(root, 'src');

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)],
  );
}

// Physical properties that have a logical counterpart. One-sided borders are
// excluded: those are usually a visual rule (an accent stripe), not a
// directional one.
const PHYSICAL = /(^|[;{\s])(left|right|margin-left|margin-right|padding-left|padding-right)\s*:/;
const TEXT_ALIGN = /text-align\s*:\s*(left|right)\b/;

const files = walk(srcDir).filter((f) => f.endsWith('.css'));
const problems = [];

for (const file of files) {
  const lines = readFileSync(file, 'utf8').split('\n');
  let inRtlRule = false;
  let depth = 0;

  lines.forEach((line, i) => {
    const trimmed = line.trim();

    // Track whether we are inside an html[dir="rtl"] rule. Brace counting is
    // enough: these blocks hold flat declarations, not nested rules.
    if (!inRtlRule && /html\[dir=["']?rtl["']?\]/.test(line) && line.includes('{')) {
      inRtlRule = true;
      depth = 0;
    }
    if (inRtlRule) {
      depth += (line.match(/\{/g) || []).length;
      depth -= (line.match(/\}/g) || []).length;
      if (depth <= 0) inRtlRule = false;
      return; // physical properties are this block's whole purpose
    }

    if (trimmed.startsWith('/*') || trimmed.startsWith('*')) return;
    if (!PHYSICAL.test(line) && !TEXT_ALIGN.test(line)) return;

    const previous = i > 0 ? lines[i - 1] : '';
    if (line.includes('rtl-ok:') || previous.includes('rtl-ok:')) return;

    problems.push({ where: `${relative(root, file)}:${i + 1}`, line: trimmed });
  });
}

if (problems.length) {
  console.error(`\nPhysical CSS in ${problems.length} place(s) — use logical properties:`);
  for (const p of problems) console.error(`  ${p.where}  ${p.line}`);
  console.error(
    '\nUse inset-inline-start/end, margin-inline, padding-inline, text-align: start.' +
      '\nIf the rule genuinely must not flip, add a /* rtl-ok: <reason> */ marker.',
  );
  process.exit(1);
}

console.log(`RTL guard: ${files.length} stylesheet(s) clean.`);
