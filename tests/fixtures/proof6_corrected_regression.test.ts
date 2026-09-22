import test from 'node:test';
import assert from 'node:assert/strict';
import { generateSessionKey } from './lib/crypto/aes';
import { createEncryptionStream, createDecryptionStream } from './lib/crypto/stream-cipher';
import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';

const FIXTURE = new TextEncoder().encode('Hello, World! This is a test of the stream cipher regression test.');

test('stream cipher round-trip preserves all bytes including final partial chunk', async () => {
  let recovered: Uint8Array | undefined;

  await assert.doesNotReject(async () => {
    const { key } = await generateSessionKey();
    recovered = await collectBytes(
      readableFromBytes(FIXTURE, 7)
        .pipeThrough(await createEncryptionStream(key, { chunkSize: 16 }))
        .pipeThrough(await createDecryptionStream(key)),
    );
  });

  assert.deepStrictEqual(recovered, FIXTURE);
});
