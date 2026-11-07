const { chromium } = require('playwright-core');
(async () => {
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = await browser.newContext();
  await ctx.addCookies([{ name: 'ovm_session', value: 'A4k13vahcNaRuF92AtT2lZEqrh1ReA4INJZ9rtt6ObA', domain: 'star.imkoris.info', path: '/', secure: true, httpOnly: true }]);
  const page = await ctx.newPage();
  const r = await page.request.get('https://star.imkoris.info:2095/api/users/');
  console.log('api status:', r.status());
})(  );
