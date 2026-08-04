const { chromium } = require("playwright");
(async () => {
  const browser = await chromium.launch({ executablePath: "/usr/bin/chromium-browser", headless: true, args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on("pageerror", err => console.log("ERR:", err.message));
  page.on("console", msg => { if (msg.type() === "error") console.log("JS:", msg.text()); });
  await page.goto("http://127.0.0.1:2095/dash/", { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(2000);
  const inputs = await page.$$("input");
  if (inputs.length >= 2) {
    await inputs[0].fill("admin");
    await inputs[1].fill("admin");
    await page.click("button[type=submit]");
    await page.waitForLoadState("networkidle", { timeout: 10000 });
    await page.waitForTimeout(2000);
  }
  await page.screenshot({ path: "/tmp/onboarding-live.png", fullPage: true });
  console.log("done");
  await browser.close();
})();
