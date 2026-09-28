// Run with backend/tests/serve_fixture.py and the local frontend running.
import assert from 'node:assert/strict';
import { readEvents } from '../lib/stream.mjs';
const url = `${process.env.FRONTEND_URL || 'http://127.0.0.1:3001'}/api/chat`;
const ask = question => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({question}) });
const success = await ask('proxy test');
assert.equal(success.status, 200);
const events = [];
await readEvents(success.body, (name, data) => events.push([name, data]));
assert.deepEqual(events.map(e => e[0]), ['status','answer','done']);
assert.equal(events[1][1].answer, 'Fixture answer [1]');
const quota = await ask('quota test');
await assert.rejects(readEvents(quota.body, () => {}), /usage limit/i);
const invalid = await ask(' ');
assert.equal(invalid.status, 422);
console.log('PASS: Next.js → FastAPI SSE proxy, answer/citation forwarding, quota event, and validation errors. Fixture data only.');
