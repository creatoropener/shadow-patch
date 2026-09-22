import test from 'node:test';
import assert from 'node:assert/strict';
import { generateSessionKey } from './lib/crypto/aes';
import { createEncryptionStream, createDecryptionStream } from './lib/crypto/stream-cipher';
import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';

const FIXTURE = new TextEncoder().encode('Hello, World! This is a test of the stream cipher regression test.');

test('stream cipher round-trip preserves all bytes including final partial chunk', async () => {
  const { key } = await generateSessionKey();

  const enc = await createEncryptionStream(key, { chunkSize: 16 });
  const dec = await createDecryptionStream(key);

  const inputStream = readableFromBytes(FIXTURE, 16);
  const encoded = inputStream.pipeThrough(enc);
  const recovered = await collectBytes(encoded);

  assert.deepStrictEqual(recovered, FIXTURE);
});
