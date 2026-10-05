import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';


const here = dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(join(here, p), 'utf8');

const PHONE_MAX = 767.98; // must equal the JS threshold minus a subpixel

describe('responsive breakpoints', () => {
  it('DashboardLayout switches to mobile at the documented threshold', () => {
    const src = read('pages/DashboardLayout.tsx');
    const m = /window\.innerWidth\s*<\s*(\d+)/.exec(src);
    expect(m, 'expected an `innerWidth < N` mobile test').toBeTruthy();
    expect(Number(m[1])).toBe(Math.ceil(PHONE_MAX));
  });

  it('Sidebar closes its drawer at the same threshold', () => {
    const src = read('components/Sidebar.tsx');
    const m = /window\.innerWidth\s*>=\s*(\d+)/.exec(src);
    expect(m, 'expected an `innerWidth >= N` reset').toBeTruthy();
    expect(Number(m[1])).toBe(Math.ceil(PHONE_MAX));
  });

  it('no stylesheet keeps a stale phone breakpoint', () => {
    for (const file of ['index.css', 'styles.css']) {
      const css = read(file);
      expect(css, `${file} still uses max-width: 760px`).not.toMatch(/max-width:\s*760px/);
      expect(css, `${file} still uses max-width: 768px`).not.toMatch(/max-width:\s*768px/);
      expect(css, `${file} still uses min-width: 761px`).not.toMatch(/min-width:\s*761px/);
    }
  });

  it('phone blocks all use the single shared value', () => {
    for (const file of ['index.css', 'styles.css']) {
      const css = read(file);
      const phone = [...css.matchAll(/@media[^{]*?max-width:\s*([\d.]+)px/g)]
        .map((m) => Number(m[1]))
        .filter((v) => v > 700 && v < 800);
      expect(phone.length, `${file} has no phone-band query`).toBeGreaterThan(0);
      for (const v of phone) expect(v).toBe(PHONE_MAX);
    }
  });
});
