import test from 'node:test';
import assert from 'node:assert/strict';
import { readEvents } from '../lib/stream.mjs';

function bytes(text, step = 1) {
  const data = new TextEncoder().encode(text);
  return new ReadableStream({ start(controller) {
    for (let i = 0; i < data.length; i += step) controller.enqueue(data.slice(i, i + step));
    controller.close();
  }});
}
test('parses fragmented UTF-8 and ignores heartbeat comments', async () => {
  const events = [];
  await readEvents(bytes(': keepalive\n\nevent: answer\ndata: {"answer":"Ísland"}\n\nevent: done\ndata: {}\n\n'), (name, data) => events.push([name, data]));
  assert.deepEqual(events, [['answer', { answer: 'Ísland' }], ['done', {}]]);
});
test('surfaces provider error', async () => {
  await assert.rejects(readEvents(bytes('event: error\ndata: {"message":"Usage limit reached"}\n\n'), () => {}), /Usage limit/);
});
test('rejects interrupted streams', async () => {
  await assert.rejects(readEvents(bytes('event: status\ndata: {}\n\n'), () => {}), /before the answer was complete/);
});
