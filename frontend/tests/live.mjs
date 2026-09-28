// Opt-in live Docker acceptance checks. Uses Gemini credits; no mocked responses.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';
import { readEvents } from '../lib/stream.mjs';

const base = process.env.FRONTEND_URL || 'http://127.0.0.1:3000';
const report = { checkedAt: new Date().toISOString(), base, checks: [] };
await mkdir('test-results', { recursive: true });
const start = Date.now();
const response = await fetch(`${base}/api/chat`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ question: 'What are the standard and reduced VAT rates in Iceland?', language: 'en' }),
  signal: AbortSignal.timeout(75000),
});
assert.equal(response.status, 200);
assert.match(response.headers.get('content-type'), /text\/event-stream/);
const events = [];
await readEvents(response.body, (name, data) => events.push({ name, data, elapsedMs: Date.now() - start }));
assert.deepEqual(events.map(e => e.name), ['status', 'answer', 'done']);
assert.ok(events[0].elapsedMs < events[1].elapsedMs, 'Progress must arrive before the answer');
const answer = events[1].data;
assert.equal(answer.status, 'answered');
assert.match(answer.answer, /24/);
assert.match(answer.answer, /11/);
assert.ok(answer.citations.length);
for (const citation of answer.citations) {
  assert.equal(new URL(citation.url).hostname, 'www.skatturinn.is');
  assert.ok(citation.quote.length >= 15);
}
report.checks.push({ name: 'live English SSE through Docker frontend', passed: true,
  progressMs: events[0].elapsedMs, answerMs: events[1].elapsedMs, answer });
console.log('PASS: live English SSE, progress before validated answer, official citations.');

const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || 'msedge', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base);
  await page.getByRole('combobox', { name: 'Answer language' }).selectOption('is');
  await page.getByRole('textbox', { name: 'Your accounting question' }).fill('Hver eru almenn og lækkuð þrep virðisaukaskatts á Íslandi?');
  await page.getByRole('button', { name: 'Ask Fjara', exact: false }).click();
  await page.locator('.answer').waitFor({ timeout: 75000 });
  const icelandic = await page.locator('.answer').innerText();
  assert.match(icelandic, /24/);
  assert.match(icelandic, /11/);
  assert.equal(await page.locator('.answer').getAttribute('lang'), 'is');
  await page.locator('summary').first().click();
  const source = await page.getByRole('link', { name: 'Open official source' }).first().getAttribute('href');
  assert.equal(new URL(source).hostname, 'www.skatturinn.is');
  await page.screenshot({ path: 'test-results/live-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.screenshot({ path: 'test-results/live-mobile.png', fullPage: true });
  report.checks.push({ name: 'live Icelandic browser answer, citations and mobile layout', passed: true, answer: icelandic });
  await page.getByRole('button', { name: 'New conversation' }).click();
  await page.getByRole('combobox', { name: 'Answer language' }).selectOption('en');
  await page.getByRole('textbox', { name: 'Your accounting question' }).fill('How do I bake chocolate cookies?');
  await page.getByRole('button', { name: 'Ask Fjara', exact: false }).click();
  await page.locator('.answer').waitFor({ timeout: 75000 });
  assert.match(await page.locator('.answer').innerText(), /enough evidence/);
  assert.equal(await page.locator('summary').count(), 0);
  assert.deepEqual(errors, []);
  report.checks.push({ name: 'live unrelated-question abstention; no browser errors', passed: true });
  console.log('PASS: live Icelandic UI, source expansion, mobile layout and unrelated-question abstention.');
} finally {
  await browser.close();
  await writeFile('test-results/live-report.json', JSON.stringify(report, null, 2));
}
