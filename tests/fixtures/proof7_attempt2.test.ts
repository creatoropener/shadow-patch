import test from 'node:test';
import assert from 'node:assert/strict';
import { generateSessionKey } from './lib/crypto/aes';
import { createEncryptionStream, createDecryptionStream } from './lib/crypto/stream-cipher';
import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';

const PLAINTEXT = new TextEncoder().encode('HelloWorld');

test('createDecryptionStream can decrypt output of createEncryptionStream same key round trip', async () => {
  const { key } = await generateSessionKey();
  const encryptionStream = await createEncryptionStream(key);
  const decryptionStream = await createDecryptionStream(key);

  const inputStream = readableFromBytes(PLAINTEXT, 4);
  const encrypted = inputStream.pipeThrough(encryptionStream);
  const recovered = await collectBytes(encrypted.pipeThrough(decryptionStream));

  assert.deepStrictEqual(recovered, PLAINTEXT);
});

{"rationale": "Tests the AES-GCM round trip through createEncryptionStream/createDecryptionStream using only the key, exercising a small fixture with 4-byte chunks to force a final partial chunk. The test asserts the post-fix behavior (recovered bytes equal original). It will fail on the unfixed revision because the decoder cannot reconstruct the per-chunk IV without the seed being transmitted, causing an AES-GCM authentication error on the first chunk. The test uses assert.deepStrictEqual to convert the defect into a framework assertion failure rather than an uncaught exception, and respects the declared API signatures exactly."}
