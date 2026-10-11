// End-to-end test of the P&ID designer in a real browser.
// Needs a running server (python -m steamsuite.web --no-browser) and Playwright:
//   node tests/e2e/designer_e2e.mjs [http://localhost:8000] [screenshot-dir]
import { createRequire } from 'module';

const require = createRequire(import.meta.url);
let chromium;
try { ({ chromium } = require('playwright')); } catch (e) { ({ chromium } = require('/opt/node-tools/node_modules/playwright')); }

const BASE = process.argv[2] || 'http://localhost:8000';
const SHOTS = process.argv[3] || null;
let failures = 0;
const check = (cond, msg) => { if (cond) console.log(`  ✓ ${msg}`); else { failures++; console.log(`  ✗ ${msg}`); } };

async function settle(page) {
  await page.waitForTimeout(300);
  await page.waitForFunction(() => !document.querySelector('#statusbar .dot.busy'), null, { timeout: 30000 });
  await page.waitForTimeout(250);
}
async function center(loc) {
  const b = await loc.boundingBox();
  return { x: b.x + b.width / 2, y: b.y + b.height / 2 };
}
async function dragMouse(page, from, to, button = 'left') {
  await page.mouse.move(from.x, from.y);
  await page.mouse.down({ button });
  await page.mouse.move((from.x + to.x) / 2, (from.y + to.y) / 2, { steps: 4 });
  await page.mouse.move(to.x, to.y, { steps: 4 });
  await page.mouse.up({ button });
}
const status = (page) => page.locator('#statusbar').innerText();
async function streamFlow(page, name) {
  await page.locator('#workbook-head button', { hasText: 'Streams' }).click();
  const row = page.locator('#workbook-body tbody tr').filter({ has: page.locator('td:first-child', { hasText: new RegExp(`^\\s*${name}\\s*$`) }) });
  return Number((await row.locator('td').nth(3).innerText()).replace(/,/g, ''));
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('dialog', (d) => d.accept());

  console.log('Load');
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await settle(page);
  check((await status(page)).includes('Solved'), 'default example loads and solves');
  check((await page.locator('.palette-item').count()) >= 19, 'palette lists all equipment');

  console.log('Build a flowsheet by drag and drop');
  await page.locator('#toolbar button', { hasText: 'New' }).click();
  await settle(page);
  check((await page.locator('#pid .node').count()) === 0, 'new drawing is empty');
  const canvas = page.locator('#pid');
  const cb = await canvas.boundingBox();
  await page.locator('.palette-item[data-type="feed"]').dragTo(canvas, { targetPosition: { x: 200, y: 250 } });
  await page.locator('.palette-item[data-type="pipe"]').dragTo(canvas, { targetPosition: { x: 420, y: 250 } });
  await settle(page);
  check((await page.locator('#pid .node').count()) === 2, 'supply and pipe dropped on the drawing');
  const feedOut = page.locator('[data-port][data-block="IN-101"][data-side="out"]');
  const pipeIn = page.locator('[data-port][data-block="L-101"][data-side="in"]');
  await dragMouse(page, await center(feedOut), await center(pipeIn));
  await settle(page);
  check((await page.locator('#pid path.edge').count()) === 1, 'nozzles connected with a stream');
  const pipeOut = page.locator('[data-port][data-block="L-101"][data-side="out"]');
  const po = await center(pipeOut);
  await dragMouse(page, po, { x: po.x + 160, y: po.y });
  await settle(page);
  check((await page.locator('#pid path.edge').count()) === 2, 'outlet dragged to empty space makes a product stream');
  check((await status(page)).includes('Solved'), 'flowsheet solves after connecting');

  console.log('Edit in the inspector');
  await page.locator('#pid .node[data-node="IN-101"] .body').click({ force: true });
  await page.locator('#inspector select[data-key="p-condition"], #inspector [data-key="p-condition"]').first().waitFor();
  // make it steam: pressure 10 bar(g), saturated
  const pIn = page.locator('#inspector input[data-key="p-pressure"]');
  await pIn.fill('10');
  await pIn.press('Enter');
  await page.locator('#inspector .seg[data-key="p-condition"] button', { hasText: 'Dryness fraction' }).click();
  await settle(page);
  const flow = page.locator('#inspector input[data-key="p-flow"]');
  await flow.fill('8');
  await flow.press('Enter');
  await settle(page);
  await page.locator('#pid .node[data-node="L-101"] .body').click({ force: true });
  const len = page.locator('#inspector input[data-key="p-length"]');
  await len.fill('300');
  await len.press('Enter');
  await settle(page);
  await page.locator('#inspector .insp-tabs button', { hasText: 'Results' }).click();
  const resText = await page.locator('#inspector .kv').innerText();
  check(resText.includes('Pressure drop') && resText.includes('bar'), 'pipe results show the pressure drop');
  await page.locator('#inspector .insp-tabs button', { hasText: 'Calculation' }).click();
  check((await page.locator('#inspector .katex').count()) > 3, 'calculation steps render equations');
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/e2e-pipe.png` });

  console.log('Context menu: insert a valve and a relief valve');
  const edge = page.locator('#pid path.edge-hit[data-stream="S2"]');
  const eb = await edge.boundingBox();
  const ep = { x: eb.x + eb.width * 0.6, y: eb.y + eb.height / 2 };
  await page.mouse.click(ep.x, ep.y, { button: 'right' });
  await page.locator('#ctxmenu button', { hasText: 'Insert valve' }).click();
  await settle(page);
  check((await page.locator('#pid .node').count()) === 3, 'valve inserted on the line');
  check((await status(page)).includes('Solved'), 'still solves with the valve');
  const edge1 = page.locator('#pid path.edge-hit[data-stream="S1"]');
  const e1 = await edge1.boundingBox();
  await page.mouse.click(e1.x + e1.width / 2, e1.y + e1.height / 2, { button: 'right' });
  await page.locator('#ctxmenu button', { hasText: 'Add relief valve' }).click();
  await settle(page);
  const psv = page.locator('#pid .node[data-node^="PSV-"]');
  check((await psv.count()) === 1, 'relief valve added');
  const setP = page.locator('#inspector input[data-key="p-set_pressure"]');
  await setP.fill('12');
  await setP.press('Enter');
  await settle(page);
  await page.locator('#inspector .insp-tabs button', { hasText: 'Results' }).click();
  const psvRes = await page.locator('#inspector .kv').innerText();
  check(/API 526 orifice\s+[A-T]/.test(psvRes), 'relief valve sized with an API 526 orifice');

  console.log('Undo / redo / delete / rotate');
  await canvas.click({ position: { x: 30, y: 30 } });
  await page.keyboard.press('Control+z');
  await settle(page);
  check((await page.locator('#pid .node[data-node^="PSV-"]').count()) === 1, 'undo reverts the set pressure only');
  await page.keyboard.press('Control+z');
  await settle(page);
  check((await page.locator('#pid .node[data-node^="PSV-"]').count()) === 0, 'undo removes the relief valve');
  await page.keyboard.press('Control+y');
  await settle(page);
  check((await page.locator('#pid .node[data-node^="PSV-"]').count()) === 1, 'redo restores it');
  await page.locator('#pid .node[data-node="L-101"] .body').click({ force: true });
  await page.keyboard.press('r');
  await page.waitForTimeout(200);
  const tr = await page.locator('#pid .node[data-node="L-101"] > g').getAttribute('transform');
  check(tr.includes('rotate(90)'), 'R rotates the selected unit');
  await page.keyboard.press('Control+d');
  await settle(page);
  check((await page.locator('#pid .node').count()) === 5, 'Ctrl+D duplicates');
  await page.keyboard.press('Delete');
  await settle(page);
  check((await page.locator('#pid .node').count()) === 4, 'Delete removes the duplicate');

  console.log('Click-to-place, tidy and export');
  const before = await page.locator('#pid .node').count();
  await page.locator('.palette-item[data-type="pump"]').click();
  await canvas.click({ position: { x: 300, y: 520 } });
  await settle(page);
  check((await page.locator('#pid .node').count()) === before + 1, 'click a palette item then the drawing places a unit');
  await page.locator('#toolbar button', { hasText: 'Tidy' }).click();
  await settle(page);
  check((await page.locator('#pid .node').count()) === before + 1, 'tidy layout keeps every unit');
  const [svgDl] = await Promise.all([page.waitForEvent('download'), page.locator('#toolbar button', { hasText: 'Export drawing' }).click()]);
  check(svgDl.suggestedFilename().endsWith('.svg'), 'export drawing downloads an SVG');
  await page.keyboard.press('Control+z');
  await page.keyboard.press('Control+z');
  await settle(page);

  console.log('Workbook and units');
  await page.locator('#workbook-head button', { hasText: 'Streams' }).click();
  const rows = await page.locator('#workbook-body tbody tr').count();
  check(rows >= 3, `workbook lists ${rows} streams`);
  await page.locator('#workbook-body tbody tr').first().click();
  check((await page.locator('#inspector .kind').innerText()).toLowerCase().includes('stream'), 'clicking a row selects the stream');
  await page.selectOption('#units-preset', 'us');
  await settle(page);
  check((await page.locator('#workbook-body thead').innerText()).includes('psig'), 'US units shown after switching');
  await page.selectOption('#units-preset', 'metric');

  console.log('Case study');
  await page.locator('#toolbar button', { hasText: 'Case study' }).click();
  await page.locator('.modal footer button', { hasText: 'Run' }).click();
  await page.waitForSelector('.modal .mini-table tbody tr', { timeout: 30000 });
  check((await page.locator('.modal .mini-table tbody tr').count()) === 6, 'case study table has 6 rows');
  await page.locator('.modal header button').click();

  console.log('Pressure–flow mode');
  await page.selectOption('#toolbar select', { label: 'Cooling-water network (pressure–flow)' });
  await settle(page);
  check(/pressure–flow: 34 equations for 34 unknowns/.test(await status(page)), 'parallel cooling-water network solves as a pressure–flow network');
  const flowsBefore = [await streamFlow(page, 'CW-A1'), await streamFlow(page, 'CW-B1'), await streamFlow(page, 'CW-C1')];
  const pumpFlow = await streamFlow(page, 'CW2');
  check(flowsBefore.every((f) => f > 0) && new Set(flowsBefore.map((f) => f.toFixed(1))).size === 3,
    `branches take different flows by their resistance (${flowsBefore.join(', ')} t/h)`);
  check(Math.abs(flowsBefore.reduce((a, b) => a + b, 0) - pumpFlow) < 0.05, 'branch flows add up to the pump flow');
  await page.locator('#workbook-head button', { hasText: 'Equipment' }).click();
  await page.locator('#workbook-body tbody tr', { hasText: 'HV-201' }).click();
  const opening = page.locator('#inspector input[data-key="p-opening"]');
  await opening.fill('25');
  await opening.press('Enter');
  await settle(page);
  const flowA = await streamFlow(page, 'CW-A1');
  const flowB = await streamFlow(page, 'CW-B1');
  check(flowA < flowsBefore[0] - 1 && flowB > flowsBefore[1], 'throttling a balancing valve moves flow to the other branches');
  await page.locator('.palette-item[data-type="sink"]').dragTo(canvas, { targetPosition: { x: 300, y: 600 } });
  await settle(page);
  check((await page.locator('#pid .node[data-node^="OUT-"]').count()) === 1, 'a product/sink can be placed from the palette');
  await page.keyboard.press('Delete');
  await settle(page);
  await page.selectOption('#toolbar select', { label: 'Steam distribution with pipes and relief valves' });
  await settle(page);
  await page.selectOption('#solver-mode', 'pressure_flow');
  await settle(page);
  check(/pressure–flow: \d+ equations for \d+ unknowns/.test(await status(page)), 'the solver can be switched to pressure–flow in the toolbar');
  await page.selectOption('#solver-mode', 'sequential');
  await settle(page);

  console.log('Relief scenarios on the drawing');
  await page.locator('#pid .node[data-node="PSV-101"] .body').click({ force: true });
  await page.selectOption('#inspector select[data-key="p-rate_mode"]', 'Scenarios (API 521)');
  await settle(page);
  await page.selectOption('#inspector select[data-key="sc-add"]', 'cv_failure');
  await settle(page);
  await page.selectOption('#inspector select[data-key="sc-0-valve"]', 'PCV-101');
  await settle(page);
  await page.selectOption('#inspector select[data-key="sc-add"]', 'fire');
  await settle(page);
  check((await page.locator('#inspector .scenario-card').count()) === 2, 'two relief scenarios added to the PSV');
  check((await page.locator('#inspector .scenario-card.governs').count()) === 1, 'the governing scenario is highlighted');
  await page.locator('#inspector .insp-tabs button', { hasText: 'Results' }).click();
  const scRes = await page.locator('#inspector .kv').innerText();
  check(/Governing scenario\s+Control valve fails open/.test(scRes), 'the failed-open PRV governs, with values from PCV-101 on the drawing');
  await page.locator('#workbook-head button', { hasText: 'Relief' }).click();
  check((await page.locator('#workbook-body').innerText()).includes('Control valve fails open'), 'relief workbook lists the governing scenario');

  console.log('Compare with reference results');
  await page.locator('#workbook-head button', { hasText: 'Compare' }).click();
  await page.locator('textarea[data-key="compare-text"]').fill('Stream\tS1\tS4\nTemperature [C]\t185.6\t156.8\nPressure [bar]\t11.47\t4.9\n');
  await page.locator('#workbook-body button', { hasText: 'Compare' }).click();
  await page.waitForSelector('#workbook-body tbody tr');
  check((await page.locator('#workbook-body tbody tr').count()) === 4, 'pasted HYSYS-style table compared stream by stream');
  check((await page.locator('#workbook-body .band-good').count()) >= 2, 'close values are marked good');
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/e2e-compare.png` });

  console.log('Examples, save, other pages');
  await page.selectOption('#toolbar select', { label: 'Rankine cycle with closed feedwater heater' });
  await settle(page);
  check((await status(page)).includes('Solved'), 'closed feedwater heater example solves');
  const [download] = await Promise.all([page.waitForEvent('download'), page.locator('#toolbar button', { hasText: 'Save' }).click()]);
  check(download.suggestedFilename().endsWith('.json'), 'Save downloads a .json flowsheet');
  await page.goto(`${BASE}/#/relief`);
  await page.waitForSelector('#page-relief .metric .v');
  await page.waitForTimeout(800);
  check((await page.locator('#page-relief .metric .v').nth(1).innerText()).trim() === 'L', 'relief page sizes the default case (L orifice)');
  check((await page.locator('#page-relief .katex').count()) > 5, 'relief steps render equations');
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/e2e-relief.png`, fullPage: true });
  await page.locator('#page-relief button', { hasText: 'Work it out (API 521 scenarios)' }).click();
  await page.waitForTimeout(1000);
  await page.selectOption('#page-relief select[data-key="rsc-add"]', 'cv_failure');
  await page.locator('#page-relief input[data-key="rf-inlet_on"]').check();
  await page.locator('#page-relief input[data-key="rf-outlet_on"]').check();
  await page.waitForFunction(() => document.querySelector('#page-relief')?.innerText.includes('Reaction force'), null, { timeout: 30000 });
  const relText = await page.locator('#page-relief .two-col > div:nth-child(2)').innerText();
  check(/Governing scenario\s+(External fire|Control valve fails open)/.test(relText), 'relief page sizes several API 521 scenarios');
  const govCard = await page.locator('#page-relief .scenario-card.governs').getAttribute('data-label');
  check(relText.includes(`Governing scenario\n${govCard}`), `the governing scenario's card is highlighted (${govCard})`);
  check(/Inlet pressure loss\s+[\d.]+ % of set/.test(relText) && relText.includes('Built-up back pressure'),
    'relief page checks the inlet loss and the built-up back pressure');
  const sizes = await page.$$eval('#page-relief select[data-key="rf-inlet-nps"] option', (o) => o.map((x) => x.value));
  check(sizes[0] === '1/2' && sizes.indexOf('1-1/4') === sizes.indexOf('1') + 1, 'pipe sizes listed in order');
  await page.goto(`${BASE}/#/steam`);
  await page.waitForSelector('#page-steam .msg.ok');
  check((await page.locator('#page-steam .msg.ok').innerText()).includes('Superheated'), 'steam tables page shows a state');
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/e2e-steam.png`, fullPage: true });

  check(errors.length === 0, `no browser errors${errors.length ? `: ${errors.join(' | ')}` : ''}`);
  await browser.close();
  console.log(failures ? `\n${failures} check(s) failed` : '\nAll checks passed');
  process.exit(failures ? 1 : 0);
})();
