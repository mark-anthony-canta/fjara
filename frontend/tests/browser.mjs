import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';

const browser = await chromium.launch({ channel: process.env.BROWSER_CHANNEL || 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
const base = process.env.FRONTEND_URL || 'http://127.0.0.1:3001';
const answer = { answer: 'The standard VAT rate is 24%. [1]', status: 'answered', citations: [{ id: 1,
  url: 'https://www.skatturinn.is/english/companies/value-added-tax/', title: 'Value Added Tax (VAT)',
  quote: 'The standard rate of VAT in Iceland is 24%.', crawled_at: '2026-09-24T10:00:00Z' }] };
let mode = 'answer';
let lastRequest;
await page.route('**/api/chat', async route => {
  lastRequest = route.request().postDataJSON();
  if (mode === 'slow') { await new Promise(resolve => setTimeout(resolve, 2000)); }
  if (mode === 'http-error') return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Service unavailable. Please retry.' }) });
  const result = mode === 'abstain' ? { answer: 'I do not have enough evidence.', status: 'insufficient_evidence', citations: [] } : answer;
  const body = mode === 'stream-error' ? 'event: error\ndata: {"message":"Provider usage limit reached."}\n\n'
    : `event: status\ndata: {"message":"Checking sources…"}\n\nevent: answer\ndata: ${JSON.stringify(result)}\n\nevent: done\ndata: {}\n\n`;
  await route.fulfill({ contentType: 'text/event-stream', body }).catch(() => {});
});
try {
  await page.goto(base);
  await page.getByRole('heading', { level: 1 }).waitFor();
  await mkdir('test-results', { recursive: true });
  await page.screenshot({ path: 'test-results/desktop.png', fullPage: true });
  assert.equal(await page.getByRole('button', { name: 'Ask Fjara', exact: false }).isDisabled(), true);
  await page.getByRole('button', { name: /What are the VAT rates/ }).click();
  await page.getByRole('combobox', { name: 'Answer language' }).selectOption('is');
  await page.getByRole('button', { name: 'Ask Fjara', exact: false }).click();
  await page.getByText('The standard VAT rate is 24%.', { exact: false }).waitFor();
  assert.equal(lastRequest.language, 'is');
  await page.locator('summary').click();
  assert.equal(await page.getByRole('link', { name: 'Open official source' }).getAttribute('href'), answer.citations[0].url);
  await page.getByText(answer.citations[0].quote, { exact: true }).waitFor();
  await page.screenshot({ path: 'test-results/answer-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'New conversation' }).click();
  mode = 'stream-error';
  await page.getByRole('textbox', { name: 'Your accounting question' }).fill('VAT?');
  await page.getByRole('button', { name: 'Ask Fjara', exact: false }).click();
  await page.getByText('Provider usage limit reached.', { exact: true }).waitFor();
  assert.match(await page.locator('.error').innerText(), /usage limit/);
  mode = 'abstain';
  await page.getByRole('button', { name: 'Retry question' }).click();
  await page.getByText('I do not have enough evidence.').waitFor();
  mode = 'slow';
  await page.getByRole('textbox', { name: 'Your accounting question' }).fill('Stop this request');
  await page.getByRole('button', { name: 'Ask Fjara', exact: false }).click();
  await page.getByRole('button', { name: 'Stop', exact: false }).click();
  await page.getByText('Request stopped.', { exact: false }).waitFor();
  mode = 'http-error';
  await page.getByRole('textbox', { name: 'Your accounting question' }).fill('VAT again?');
  await page.getByRole('button', { name: 'Ask Fjara', exact: false }).click();
  await page.getByText('Service unavailable. Please retry.', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'New conversation' }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: 'test-results/mobile.png', fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  mode = 'answer';
  await page.getByRole('textbox', { name: 'Your accounting question' }).fill('VAT?');
  await page.getByRole('button', { name: 'Ask Fjara', exact: false }).click();
  await page.locator('summary').waitFor();
  await page.locator('summary').click();
  await page.screenshot({ path: 'test-results/answer-mobile.png', fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  assert.deepEqual(errors, []);
  console.log('PASS: desktop/mobile layout, language, citations, abstention, retry, cancellation, HTTP and stream errors; no browser exceptions.');
} finally { await browser.close(); }
