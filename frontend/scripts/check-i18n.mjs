#!/usr/bin/env node
/**
 * i18n drift guard. `en.json` is the source of truth.
 *
 * Fails when a locale is missing MORE keys than its budget (new strings
 * must be translated or explicitly budgeted) or carries EXTRA keys not in
 * `en` (dead weight / renamed-key leftovers).
 *
 * Budgets (missing keys tolerated today):
 *   frontend fa/ru/cn: 23 each (nodeBundle* + onboardStep* strings)
 *   bot      fa/ru/cn: 0  (currently fully in sync)
 *
 * Lower a budget to zero once translations land — never raise one without
 * noting why in PROJECT_PLAN.md.
 *
 * Exit code 1 on any failure.
 */
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const GROUPS = [
  { dir: join(root, 'src', 'lang'), locales: ['fa', 'ru', 'cn'], budget: 23 },
  { dir: join(root, '..', 'bot', 'locales'), locales: ['fa', 'ru', 'cn'], budget: 0 },
];

let failures = 0;
for (const { dir, locales, budget } of GROUPS) {
  const en = JSON.parse(readFileSync(join(dir, 'en.json'), 'utf8'));
  const enKeys = new Set(Object.keys(en));
  for (const lng of locales) {
    const cur = JSON.parse(readFileSync(join(dir, `${lng}.json`), 'utf8'));
    const keys = new Set(Object.keys(cur));
    const missing = [...enKeys].filter((k) => !keys.has(k));
    const extra = [...keys].filter((k) => !enKeys.has(k));
    const missOk = missing.length <= budget;
    const extraOk = extra.length === 0;
    if (!missOk || !extraOk) failures++;
    console.log(
      `${dir.endsWith('locales') ? 'bot' : 'frontend'}/${lng}: ` +
      `missing ${missing.length}/${budget} ${missOk ? 'pass' : 'FAIL'}; ` +
      `extra ${extra.length} ${extraOk ? 'pass' : 'FAIL'}`,
    );
    if (!missOk) console.log(`  missing: ${missing.slice(0, 10).join(', ')}${missing.length > 10 ? '…' : ''}`);
    if (!extraOk) console.log(`  extra: ${extra.slice(0, 10).join(', ')}${extra.length > 10 ? '…' : ''}`);
  }
}
console.log(failures === 0 ? 'All i18n checks passed.' : `${failures} locale(s) drifted.`);
process.exit(failures === 0 ? 0 : 1);
