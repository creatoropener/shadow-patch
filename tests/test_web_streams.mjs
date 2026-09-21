import test from 'node:test';
import assert from 'node:assert/strict';

import {
  collectBytes,
  readableFromBytes,
} from '../patchproof_runtime/web_streams.mjs';

test('byte stream helper preserves bytes across uneven segments', async () => {
  const input = Uint8Array.from({ length: 37 }, (_, index) => (index * 17) % 256);
  const output = await collectBytes(readableFromBytes(input, 8));
  assert.deepStrictEqual(output, input);
  assert.notStrictEqual(output.buffer, input.buffer);
});

test('byte stream helper rejects invalid inputs', async () => {
  assert.throws(() => readableFromBytes('not bytes'), TypeError);
  assert.throws(() => readableFromBytes(new Uint8Array([1]), 0), RangeError);
  await assert.rejects(
    collectBytes(new ReadableStream({
      start(controller) {
        controller.enqueue('not bytes');
        controller.close();
      },
    })),
    TypeError,
  );
});
