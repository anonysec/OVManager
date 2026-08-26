#!/usr/bin/env node
/**
 * Real-browser verification of the CSS refactor.
 *
 * Everything else in this repo verifies tokens by parsing the built stylesheet
 * and resolving var() chains by hand. That proves the declared values, but it
 * cannot prove what the browser actually computes after the cascade runs.
 * This script does, using the login page (the only route reachable without a
 * backend) plus a synthetic harness that mounts real component markup.
 *
 * Checks, per theme: every visible text run against the background actually
 * painted behind it (walking up for the first opaque ancestor, and flattening
 * alpha), horizontal overflow, and any var() that leaked through unresolved.
 * Then sweeps viewport widths across the phone/tablet boundary.
 *
 * Requires a Chromium binary. playwright-core does not download one, and
 * cdn.playwright.dev is unreachable from this sandbox, so the browser is
 * obtained from npm instead:
 *
 *   npm i @sparticuz/chromium          # ships a real binary + its NSS libs
 *   node -e "import('@sparticuz/chromium').then(m=>m.default.executablePath())"
 *   # extract bin/al2023.tar.br -> provides libnspr4/libnss3/libnssutil3
 *
 * Usage:
 *   npm run dev &
 *   LD_LIBRARY_PATH=/path/to/nss/libs CHROMIUM=/path/to/chromium \
 *     npm run check:visual -- http://127.0.0.1:5173
 */
import { chromium } from 'playwright-core';
import { mkdirSync } from 'node:fs';

const BASE = process.argv[2] || 'http://127.0.0.1:2095';
let pageErrors = 0;
const EXEC = process.env.CHROMIUM || '/tmp/chromium';
const SHOTS = 'screenshots';
mkdirSync(SHOTS, { recursive: true });

/* ---------- WCAG ---------- */
const lin = (c) => {
  c /= 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
function parseRGB(s) {
  const m = /rgba?\(([^)]+)\)/.exec(s);
  if (!m) return null;
  const p = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
  return { r: p[0], g: p[1], b: p[2], a: p[3] === undefined ? 1 : p[3] };
}
const lum = ({ r, g, b }) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
function over(fg, bg) {
  // flatten a translucent foreground onto its backdrop
  const a = fg.a;
  return { r: fg.r * a + bg.r * (1 - a), g: fg.g * a + bg.g * (1 - a), b: fg.b * a + bg.b * (1 - a), a: 1 };
}
function contrast(fgStr, bgStr) {
  const fg = parseRGB(fgStr);
  const bg = parseRGB(bgStr);
  if (!fg || !bg) return null;
  const f = lum(over(fg, bg));
  const b = lum(bg);
  const hi = Math.max(f, b);
  const lo = Math.min(f, b);
  return (hi + 0.05) / (lo + 0.05);
}

let failures = 0;
const log = (ok, msg) => {
  if (!ok) failures++;
  console.log(`  ${ok ? 'pass' : 'FAIL'}  ${msg}`);
};

const browser = await chromium.launch({
  executablePath: EXEC,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'],
});

/* Resolve the effective background actually painted behind an element. */
const EFFECTIVE_BG = `(el) => {
  let n = el;
  while (n) {
    const bg = getComputedStyle(n).backgroundColor;
    const m = /rgba?\\(([^)]+)\\)/.exec(bg);
    if (m) {
      const p = m[1].split(/[,\\s/]+/).filter(Boolean).map(Number);
      const a = p[3] === undefined ? 1 : p[3];
      if (a > 0.95) return bg;
    }
    n = n.parentElement;
  }
  return getComputedStyle(document.body).backgroundColor;
}`;

async function auditPage(page, label, { expectAuthed = false } = {}) {
  console.log(`\n── ${label} ─────────────────────────────`);

  if (expectAuthed) {
    // A logged-out shell has almost no text and trivially "passes" every
    // check below. Treat a bounce to /login as a hard failure.
    const onLogin = /\/login(\?|$)/.test(page.url())
      || (await page.locator('#login-container').count()) > 0;
    log(!onLogin, `session held (not bounced to /login)`);
    if (onLogin) return;
  }

  // 1. every visible text node must clear AA against what is really behind it
  const bad = await page.evaluate(`(() => {
    const effBg = ${EFFECTIVE_BG};
    const lin = (c) => { c/=255; return c<=0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4); };
    const parse = (s) => { const m=/rgba?\\(([^)]+)\\)/.exec(s); if(!m) return null;
      const p=m[1].split(/[,\\s/]+/).filter(Boolean).map(Number);
      return {r:p[0],g:p[1],b:p[2],a:p[3]===undefined?1:p[3]}; };
    const lum = (c) => 0.2126*lin(c.r)+0.7152*lin(c.g)+0.0722*lin(c.b);
    const over = (f,b) => ({r:f.r*f.a+b.r*(1-f.a), g:f.g*f.a+b.g*(1-f.a), b:f.b*f.a+b.b*(1-f.a)});
    const out = [];
    for (const el of document.querySelectorAll('*')) {
      const direct = [...el.childNodes].some(n => n.nodeType===3 && n.textContent.trim().length>1);
      if (!direct) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility==='hidden' || cs.display==='none' || Number(cs.opacity)<0.3) continue;
      const r = el.getBoundingClientRect();
      if (r.width<2 || r.height<2) continue;
      const fg = parse(cs.color); const bg = parse(effBg(el));
      if (!fg || !bg) continue;
      const L1 = lum(over(fg,bg)), L2 = lum(bg);
      const ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
      const size = parseFloat(cs.fontSize);
      const largeText = size >= 24 || (size >= 18.66 && Number(cs.fontWeight) >= 700);
      const need = largeText ? 3.0 : 4.5;
      if (ratio < need) {
        out.push({ tag: el.tagName.toLowerCase(), cls: (el.className||'').toString().slice(0,40),
                   text: el.textContent.trim().slice(0,32), color: cs.color,
                   bg: effBg(el), ratio: +ratio.toFixed(2), need });
      }
    }
    return out;
  })()`);
  log(bad.length === 0, `text contrast: ${bad.length} element(s) below AA`);
  for (const b of bad.slice(0, 12)) {
    console.log(`         <${b.tag} class="${b.cls}"> "${b.text}" ${b.ratio}:1 (needs ${b.need}) ${b.color} on ${b.bg}`);
  }

  // 2. nothing may overflow horizontally (the responsive dead-zone class of bug)
  const oflow = await page.evaluate(`(() => {
    const de = document.documentElement;
    return { scroll: de.scrollWidth, client: de.clientWidth };
  })()`);
  log(oflow.scroll <= oflow.client + 1, `no horizontal overflow (${oflow.scroll} <= ${oflow.client})`);

  // 3. no token may leak through unresolved
  const unresolved = await page.evaluate(`(() => {
    const out=[];
    for (const el of document.querySelectorAll('*')) {
      const cs = getComputedStyle(el);
      for (const p of ['color','background-color','border-color']) {
        const v = cs.getPropertyValue(p);
        if (v.includes('var(') || v === '') out.push(el.tagName+' '+p+' = '+v);
      }
    }
    return out.slice(0,10);
  })()`);
  log(unresolved.length === 0, `no unresolved var() in computed styles`);
  unresolved.forEach((u) => console.log('         ', u));
}

/* ── authentication ──────────────────────────────────────────────────────
   Log in through the real API so the token in localStorage is one the
   backend actually issued, then let the SPA boot as an authenticated user. */
const CREDS = {
  username: process.env.OV_USER || 'admin',
  password: process.env.OV_PASS || 'LocalDevOnly!2026',
};

async function login() {
  const res = await fetch(`${BASE}/api/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Requested-With': 'XMLHttpRequest' },
    body: new URLSearchParams(CREDS),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status} ${await res.text()}`);
  const j = await res.json();
  if (!j.access_token) throw new Error('login returned no access_token');
  if (!j.role) throw new Error('login returned no role — the panel cannot authenticate');
  return j;
}

const { access_token: TOKEN, role: ROLE, username: USERNAME } = await login();
console.log(`authenticated as ${USERNAME} (${ROLE})`);

const ROUTES = [
  ['/', 'dashboard'],
  ['/users', 'users'],
  ['/nodes', 'nodes'],
  ['/settings', 'settings'],
  ['/audit', 'audit'],
  ['/admins', 'admins'],
];

async function newAuthedPage(browser, { theme = 'dark', rtl = false, width = 1440, height = 1000 } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height } });
  const page = await ctx.newPage();
  // Seed the same keys a real login writes. userRole/username matter: the
  // sidebar and owner-only routes read them, and an authToken alone renders
  // a logged-out shell that would make every audit below vacuously pass.
  await page.addInitScript(`(() => {
    localStorage.setItem('authToken', ${JSON.stringify(TOKEN)});
    localStorage.setItem('userRole', ${JSON.stringify(ROLE)});
    localStorage.setItem('username', ${JSON.stringify(USERNAME)});
    localStorage.setItem('ovmanager-theme', ${JSON.stringify(theme)});
    ${rtl ? "localStorage.setItem('ovmanager-lang','fa');" : ''}
  })()`);
  page.on('pageerror', (e) => { console.log(`         [pageerror] ${e.message}`); pageErrors++; });
  return { ctx, page };
}


/* ═══════════ authenticated routes ═══════════ */
for (const theme of ['dark', 'light']) {
  for (const [route, name] of ROUTES) {
    const { ctx, page } = await newAuthedPage(browser, { theme });
    await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
    await page.evaluate(`document.documentElement.setAttribute('data-theme', ${JSON.stringify(theme)})`);
    // let skeletons resolve into real content
    await page.waitForTimeout(1800);
    await auditPage(page, `${name} · ${theme}`, { expectAuthed: true });
    await page.screenshot({ path: `${SHOTS}/${name}-${theme}.png`, fullPage: true });
    await ctx.close();
  }
}

/* ═══════════ authenticated RTL ═══════════ */
for (const [route, name] of [['/', 'dashboard'], ['/users', 'users']]) {
  const { ctx, page } = await newAuthedPage(browser, { theme: 'dark', rtl: true });
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded' });
  await page.evaluate(`(() => {
    document.documentElement.setAttribute('dir','rtl');
    document.documentElement.setAttribute('lang','fa');
    document.body.setAttribute('dir','rtl');
  })()`);
  await page.waitForTimeout(1800);
  await auditPage(page, `${name} · RTL`, { expectAuthed: true });
  await page.screenshot({ path: `${SHOTS}/${name}-rtl.png`, fullPage: true });
  await ctx.close();
}

/* ═══════════ login page, both themes ═══════════ */
for (const theme of ['dark', 'light']) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await page.addInitScript(`localStorage.setItem('ovmanager-theme', '${theme}');`);
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  await page.evaluate(`document.documentElement.setAttribute('data-theme', '${theme}')`);
  await page.waitForTimeout(250);
  await auditPage(page, `login · ${theme}`);
  await page.screenshot({ path: `${SHOTS}/login-${theme}.png`, fullPage: true });
  await ctx.close();
}

/* ═══════════ RTL ═══════════ */
{
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  // Switch languages the way the app does. i18n.js sets dir on BOTH <html>
  // and <body>; setting only <html> leaves body[dir=ltr] overriding it, so
  // the page silently stays LTR and the check proves nothing.
  await page.evaluate(`(() => {
    document.documentElement.setAttribute('dir','rtl');
    document.documentElement.setAttribute('lang','fa');
    document.body.setAttribute('dir','rtl');
  })()`);
  await page.waitForTimeout(250);
  await auditPage(page, 'login · RTL (fa)');
  await page.screenshot({ path: `${SHOTS}/login-rtl.png`, fullPage: true });
  await ctx.close();
}

/* ═══════════ responsive sweep across the old dead zone ═══════════ */
console.log('\n── responsive sweep ─────────────────────');
{
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
  for (const w of [375, 700, 759, 760, 767, 768, 769, 900, 1280]) {
    await page.setViewportSize({ width: w, height: 800 });
    await page.waitForTimeout(120);
    const r = await page.evaluate(`(() => {
      const de = document.documentElement;
      return { over: de.scrollWidth > de.clientWidth + 1, sw: de.scrollWidth, cw: de.clientWidth };
    })()`);
    log(!r.over, `${String(w).padStart(4)}px — no horizontal overflow (${r.sw}/${r.cw})`);
  }
  await ctx.close();
}

/* ═══════════ authenticated responsive sweep ═══════════ */
console.log('\n── authenticated responsive sweep (users table) ──');
{
  const { ctx, page } = await newAuthedPage(browser, { theme: 'dark' });
  await page.goto(`${BASE}/users`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1800);
  for (const w of [375, 700, 759, 767, 768, 900, 1280, 1440]) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.waitForTimeout(200);
    const r = await page.evaluate(`(() => {
      const de = document.documentElement;
      const nav = document.querySelector('.mobile-nav');
      const navShown = nav ? getComputedStyle(nav).display !== 'none' : false;
      return { over: de.scrollWidth > de.clientWidth + 1, sw: de.scrollWidth, cw: de.clientWidth, navShown };
    })()`);
    // Below 768 the bottom tab bar must be present; at/above it must not be.
    const wantNav = w < 768;
    log(!r.over, `${String(w).padStart(4)}px no overflow (${r.sw}/${r.cw})`);
    log(r.navShown === wantNav, `${String(w).padStart(4)}px bottom nav ${r.navShown ? 'shown' : 'hidden'} (expected ${wantNav ? 'shown' : 'hidden'})`);
  }
  await ctx.close();
}

console.log(`\nuncaught page errors: ${pageErrors}`);
failures += pageErrors;

await browser.close();
console.log(failures === 0 ? '\nAll browser checks passed.' : `\n${failures} browser check(s) failed.`);
process.exit(failures === 0 ? 0 : 1);
