import test from 'node:test';
import assert from 'node:assert/strict';
import { formatBytes, formatSpeed, formatEta } from '../lib/utils/format';

// Existing, unaffected behavior only. PatchProof independently creates the
// failing regression for the reported KB/MB/GB formatting issue.
test('byte-sized values retain their B suffix', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(512), '512 B');
  assert.equal(formatBytes(1023), '1023 B');
});

test('byte-sized transfer rates retain their suffix', () => {
  assert.equal(formatSpeed(512), '512 B/s');
});

test('short and unknown ETA behavior remains intact', () => {
  assert.equal(formatEta(0), '0s');
  assert.equal(formatEta(1.2), '2s');
  assert.equal(formatEta(Infinity), '—');
});
