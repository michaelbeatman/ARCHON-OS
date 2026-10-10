const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();

  console.log('Loading app on http://localhost:8501...');
  await page.goto('http://localhost:8501', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(3000);

  console.log('Navigating to Agenten-Kader...');
  await page.click('#nav-agent-profiles');
  await page.waitForTimeout(1500);

  console.log('Testing all 7 tiles:');
  const tabs = ['overview', 'chat', 'skills', 'paperclip', 'soul', 'personalakte', 'marketplace'];
  for (const t of tabs) {
    console.log(`- Clicking #agent-tab-btn-${t}`);
    await page.click(`#agent-tab-btn-${t}`);
    await page.waitForTimeout(400);
  }

  // Back to overview
  await page.click('#agent-tab-btn-overview');
  await page.waitForTimeout(500);

  await page.screenshot({ path: 'scratch_agent_header_mockup_verified.png' });
  console.log('Screenshot saved: scratch_agent_header_mockup_verified.png');

  await browser.close();
  console.log('Verification finished successfully!');
})();
