import test from 'node:test';
import assert from 'node:assert/strict';
import { generateSessionKey } from './lib/crypto/aes';
import { createEncryptionStream, createDecryptionStream } from './lib/crypto/stream-cipher';
import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';

const FIXTURE = new Uint8Array([0x42, 0x11, 0x22, 0x33, 0x44, 0x55]);
const CHUNK = 2;

test('stream encrypt/decrypt round trip recovers original bytes including final partial chunk', async () => {
  const { key } = await generateSessionKey();
  const enc = await createEncryptionStream(key, { chunkSize: CHUNK });
  const dec = await createDecryptionStream(key);
  const input = readableFromBytes(FIXTURE, CHUNK);
  const encStream = input.pipeThrough(enc);
  const decStream = encStream.pipeThrough(dec);
  const recovered = await collectBytes(decStream);
  assert.deepStrictEqual(recovered, FIXTURE);
});
