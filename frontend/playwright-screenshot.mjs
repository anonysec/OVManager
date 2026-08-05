import { chromium } from 'playwright';

(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/chromium-browser', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push('[console] ' + msg.text()); });
  page.on('pageerror', err => errors.push('[pageerror] ' + err.message));
  page.on('requestfailed', req => errors.push('[requestfailed] ' + req.url() + ' → ' + (req.failure()?.errorText || '?')));

  await page.goto('http://127.0.0.1:2095/dash/', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: '/tmp/dash-login.png', fullPage: false });
  console.log('Login page:', page.url());

  const inputs = await page.locator('input').count();
  console.log('Input count:', inputs);
  if (inputs >= 2) {
    await page.locator('input').nth(0).fill('admin');
    await page.locator('input').nth(1).fill('admin');
    await page.screenshot({ path: '/tmp/dash-login-filled.png' });
    const buttons = await page.locator('button').count();
    console.log('Button count:', buttons);
    await page.locator('button').nth(0).click();
    await page.waitForTimeout(3000);
    console.log('After login URL:', page.url());
    await page.screenshot({ path: '/tmp/dash-dashboard.png', fullPage: false });
    const title = await page.title();
    const bodyText = await page.locator('body').innerText().then(t => t.slice(0, 300)).catch(e => 'ERR:' + e.message);
    console.log('TITLE:', title);
    console.log('BODY:', bodyText);
  }
  console.log('--- ERRORS ---');
  errors.slice(0, 15).forEach(e => console.log(e));
  await browser.close();
})().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
