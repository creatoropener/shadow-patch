import test from 'node:test';
import assert from 'node:assert/strict';
import { runDastSiteScan } from '@/src/server/dastEngine.js';

test('SSRF protection: rejects internal IP address', async () => {
  await assert.rejects(
    runDastSiteScan('http://127.0.0.1'),
    { message: /blocked/ }
  );
});
