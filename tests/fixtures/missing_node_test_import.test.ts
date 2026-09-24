import { generateSessionKey } from '@/lib/crypto/aes';
import { createEncryptionStream, createDecryptionStream } from '@/lib/crypto/stream-cipher';
import { readableFromBytes, collectBytes } from 'file:///patchproof/web_streams.mjs';
import { strict as assert } from 'node:assert';

test('stream cipher round trip with per-chunk IV seed — full + partial chunk', async () => {
  const input = new Uint8Array(97);
  for (let i = 0; i < input.length; i++) input[i] = i;
  const n = 40;

  await assert.doesNotReject(async () => {
    const { key } = await generateSessionKey();
    const forward = await createEncryptionStream(key, { chunkSize: n });
    const encoded = await collectBytes(readableFromBytes(input, n).pipeThrough(forward));
    const inverse = await createDecryptionStream(key);
    const recovered = await collectBytes(readableFromBytes(encoded, n).pipeThrough(inverse));
    assert.deepStrictEqual(recovered, input);
  });
});
