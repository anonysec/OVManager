// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

// Settings.css ships as a lazy route chunk, so it is appended to <head> AFTER
// index.css/styles.css. A bare `.btn` rule in there therefore re-skins every
// button in the app (modals, empty states, section error bars) the moment a
// user opens Settings — and it never unloads. The rules must stay scoped.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const raw = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), 'Settings.css'),
  'utf8',
);

// Strip comments first: an assertion satisfied by a comment is not an
// assertion (this repo has shipped exactly that before).
const code = raw.replace(/\/\*[\s\S]*?\*\//g, '');

const selectors = [];
const blocks = /(^|\})([^{}]*)\{/g;
let m;
while ((m = blocks.exec(code))) selectors.push(m[2]);

const buttonSelectors = selectors
  .flatMap((s) => s.split(','))
  .map((s) => s.trim())
  .filter((s) => /(^|\s)\.btn/.test(s));

describe('Settings.css button scope', () => {
  it('finds the button rules it is meant to guard', () => {
    // Guards the guard: if the selector extraction silently stops matching,
    // the scope assertion below would pass on an empty list.
    expect(buttonSelectors.length).toBeGreaterThan(3);
  });

  it('scopes every button selector to .sp-page', () => {
    const leaked = buttonSelectors.filter((s) => !/^\.sp-page\s/.test(s));
    expect(leaked).toEqual([]);
  });
});
