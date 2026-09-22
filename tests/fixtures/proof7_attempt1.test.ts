import test from 'node:test';
import assert from 'node:assert/strict';
import { generateSessionKey } from './lib/crypto/aes';
import { createEncryptionStream, createDecryptionStream } from './lib/crypto/stream-cipher';
import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';

const PLAINTEXT = new TextEncoder().encode('HelloWorld');

test('createDecryptionStream can decrypt output of createEncryptionStream (same key, no seed passed, round trip)', async () => {
  const { key } = await generateSessionKey();
  const encryptionStream = await createEncryptionStream(key);
  const decryptionStream = await createDecryptionStream(key);

  const inputStream = readableFromBytes(PLAINTEXT, 4);
  const encrypted = inputStream.pipeThrough(encryptionStream);
  const recovered = await collectBytes(encrypted.pipeThrough(decryptionStream));

  assert.deepStrictEqual(recovered, PLAINTEXT);
});
