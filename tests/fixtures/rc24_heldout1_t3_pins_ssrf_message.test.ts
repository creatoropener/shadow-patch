import test from 'node:test';
import assert from 'node:assert/strict';
import { scanSiteUrl } from '@/src/services/api';

test('SSRF protection: rejects internal IP address', async () => {
  await assert.rejects(
    scanSiteUrl('http://127.0.0.1'),
    { message: /SSRF protection: Target host resolves to a disallowed IP address/ }
  );
});
