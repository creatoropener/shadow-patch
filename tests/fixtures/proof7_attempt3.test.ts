import test from 'node:test';
import assert from 'node:assert/strict';
import { generateSessionKey } from './lib/crypto/aes';
import { createEncryptionStream, createDecryptionStream } from './lib/crypto/stream-cipher';
import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';

const PLAINTEXT = new TextEncoder().encode('HelloWorld');

/** Small chunk size (64 bytes) to guarantee a final partial chunk with only 40 real bytes. */
const CHUNK = 64;

const chunks = [];
for (let i = 0; i * CHUNK < PLAINTEXT.length; i++) {
  chunks.push(i);
}
const lastIdx = chunks[chunks.length - 1];
const lastStart = lastIdx * CHUNK;
const realLast = PLAINTEXT.length - lastStart;
const paddedLast = lastIdx < chunks.length - 1 ? CHUNK : realLast;

const FIXTURE = new Uint8Array(PLAINTEXT.length + (paddedLast - realLast));
FIXTURE.set(PLAINTEXT);

function makeStream() {
  const plain = new ReadableStream({
    start(controller) {
      let off = 0;
      while (off < FIXTURE.length) {
        const end = Math.min(off + CHUNK, FIXTURE.length);
        controller.enqueue(FIXTURE.subarray(off, end));
        off = end;
      }
      controller.close();
    },
  });
  return plain;
}

test('createDecryptionStream can decrypt output of createEncryptionStream same key round trip', async () => {
  const { key } = await generateSessionKey();
  const encryptionStream = await createEncryptionStream(key, { chunkSize: CHUNK });
  const decryptionStream = await createDecryptionStream(key);

  const inputStream = readableFromBytes(FIXTURE, CHUNK);
  const encrypted = inputStream.pipeThrough(encryptionStream);
  const recovered = await collectBytes(encrypted.pipeThrough(decryptionStream));

  assert.deepStrictEqual(recovered, FIXTURE);
});
