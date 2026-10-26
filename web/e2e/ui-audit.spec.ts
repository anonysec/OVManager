import { test } from '@playwright/test';

const CREDS = { username: 'admin', password: 'TestPass123!' };

async function login(page: any) {
  await page.goto('login');
  await page.waitForLoadState('domcontentloaded');
  const userIn = page.locator('input[type="text"]').first();
  if (!(await userIn.inputValue())) await userIn.fill(CREDS.username);
  await page.locator('input[type="password"]').first().fill(CREDS.password);
  await page.click('button[type="submit"]');
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1000);
}

async function runAudit(page: any, name: string, url: string) {
  await page.goto(url);
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1000);

  const report: any = await page.evaluate(() => {
    const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6')).map(h => ({
      level: (h as HTMLElement).tagName[1],
      text: h.textContent?.trim()
    }));

    const buttons = Array.from(document.querySelectorAll('button')).map(b => ({
      text: b.textContent?.trim(),
      ariaLabel: b.getAttribute('aria-label'),
      role: b.getAttribute('role'),
      type: b.getAttribute('type')
    }));

    const links = Array.from(document.querySelectorAll('a')).map(a => ({
      text: a.textContent?.trim(),
      href: a.getAttribute('href'),
      ariaLabel: a.getAttribute('aria-label')
    }));

    const ariaEls = Array.from(document.querySelectorAll(
      '[aria-hidden],[aria-expanded],[aria-pressed],[aria-current],[aria-label],[aria-labelledby],[aria-describedby]'
    ));
    const aria: any[] = [];
    const ariaAttrs = ['aria-hidden','aria-expanded','aria-pressed','aria-current','aria-label','aria-labelledby','aria-describedby'];
    for (const el of ariaEls) {
      const entry: any = { tag: (el as HTMLElement).tagName, className: (el as HTMLElement).className };
      for (const k of ariaAttrs) {
        const v = el.getAttribute(k);
        if (v) entry[k] = v;
      }
      aria.push(entry);
    }

    const interactive = Array.from(document.querySelectorAll('button, a, input, select'));
    let focusVisibleCount = 0;
    for (const el of interactive) {
      const cs = window.getComputedStyle(el, ':focus-visible');
      if (cs.outline !== 'none' || cs.boxShadow !== 'none') focusVisibleCount++;
    }

    const tiny: any[] = [];
    for (const el of interactive) {
      const r = el.getBoundingClientRect();
      if (r.width < 24 || r.height < 24) {
        tiny.push({ tag: (el as HTMLElement).tagName, className: (el as HTMLElement).className, text: el.textContent?.trim() });
      }
    }

    return { headings, buttons, links, aria, focusVisibleCount, tinyTargets: tiny };
  });

  console.log(`\n=== AUDIT ${name.toUpperCase()} (${url}) ===`);
  console.log(JSON.stringify(report, null, 2));

  await page.screenshot({ path: `/tmp/opencode/ui-audit-${name}.png`, fullPage: true });
}

test.describe('browser UI/UX audit', () => {
  test('dashboard', async ({ page }) => {
    await login(page);
    await page.goto('./');
    await page.waitForLoadState('domcontentloaded');
    await page.waitForTimeout(1000);

    const headings = await page.evaluate(() =>
      Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6')).map(h => `${(h as HTMLElement).tagName}:${h.textContent?.trim()}`)
    );
    console.log('\n=== DASHBOARD HEADINGS ===');
    console.log(headings.join('\n'));

    const errors: string[] = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    await page.waitForTimeout(1500);
    const real = errors.filter(e => !/favicon/i.test(e));
    console.log('DASHBOARD ERRORS:', real.length);

    await page.screenshot({ path: '/tmp/opencode/ui-audit-dashboard.png', fullPage: true });
  });

  test('users page', async ({ page }) => {
    await login(page);
    await runAudit(page, 'users', 'users');
  });
  test('nodes page', async ({ page }) => {
    await login(page);
    await runAudit(page, 'nodes', 'nodes');
  });
  test('settings page', async ({ page }) => {
    await login(page);
    await runAudit(page, 'settings', 'settings');
  });
  test('logs page', async ({ page }) => {
    await login(page);
    await runAudit(page, 'logs', 'logs');
  });
});
