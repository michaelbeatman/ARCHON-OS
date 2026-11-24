/* E2E im echten Chromium: 60er-Batches, "Mehr laden", 180-ms-Debounce. */
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..', '..');
const SCRIPT = path.join(ROOT, 'static', 'js', 'prompt_studio.js');

(async () => {
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
  } catch (err) {
    if (/executable doesn't exist|browser not installed/i.test(String(err))) {
      console.log('SKIP: Chromium nicht installiert');
      process.exit(0);
    }
    throw err;
  }

  const page = await browser.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));

  await page.setContent(`<!doctype html><html><body>
    <div id="sp-cards-wrapper"></div>
    <input id="sp-search-input" type="text" />
    <span id="sp-cards-count-label"></span>
  </body></html>`);
  await page.addScriptTag({ path: SCRIPT });

  const result = await page.evaluate(async () => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const cards = () => document.querySelectorAll('#sp-cards-wrapper div.cursor-pointer').length;
    const label = () => document.getElementById('sp-cards-count-label').textContent;
    const more = () => Array.from(document.querySelectorAll('#sp-cards-wrapper button'))
      .find(b => /Mehr laden/.test(b.textContent || '')) || null;

    currentSurePromptsCatalog = Array.from({ length: 180 }, (_, i) => ({
      id: 'p' + i, name: 'Prompt ' + i, name_de: 'Prompt ' + i,
      description: 'Beschreibung ' + i, category: 'Allgemein',
    }));

    renderSurePromptsCards('');
    const out = { initialCards: cards(), initialLabel: label(), initialButton: more() && more().textContent.trim() };
    more().click();
    out.afterOneClick = cards();
    more().click();
    out.afterTwoClicks = cards();
    out.buttonAfterAll = !!more();

    // RenderKey ist unveraendert -> spVisibleCount explizit zuruecksetzen,
    // sonst bleiben die 180 gerade geladenen Karten im DOM.
    spVisibleCount = 60;
    renderSurePromptsCards('');
    searchSurePrompts('prompt 1');
    out.immediateCards = cards();
    await sleep(100);
    out.after100ms = cards();
    await sleep(180);
    out.after180msLabel = label();
    out.after180msCards = cards();
    out.errors = [];
    return out;
  });

  await browser.close();

  assert.equal(result.initialCards, 60, 'nur 60 Karten initial im DOM');
  assert.equal(result.initialLabel, '180');
  assert.match(result.initialButton || '', /Mehr laden \(60\/180\)/);
  assert.equal(result.afterOneClick, 120, 'Mehr laden -> 120');
  assert.equal(result.afterTwoClicks, 180, 'Mehr laden -> 180');
  assert.equal(result.buttonAfterAll, false, 'Button verschwindet am Ende');
  assert.equal(result.immediateCards, 60, 'Debounce: sofort kein Render');
  assert.equal(result.after100ms, 60, 'Debounce: bei 100 ms kein Render');
  assert.equal(result.after180msLabel, '91', 'Debounce: nach 180 ms gerendert');
  assert.equal(result.after180msCards, 60, 'auch nach Suche nur 60 sichtbar');
  assert.deepEqual(errors, [], 'keine Konsolenfehler');
  console.log('OK: ' + JSON.stringify(result));
})().catch(err => { console.error(err); process.exit(1); });
