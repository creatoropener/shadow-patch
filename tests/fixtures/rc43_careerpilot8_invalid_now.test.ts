import test from 'node:test';
import assert from 'node:assert/strict';
import { findPostedDate } from '../lib/recency.js';

test('findPostedDate recognises \"Posted a month ago\"', async () => {
  const now = new Date('2026-10-24T10:00:00:00Z');
  const result = findPostedDate({ text: 'Posted a month ago' }, now);
  assert.strictEqual(result?.date.toISOString(), '2026-09-24T10:00:00.000Z');
});

test('findPostedDate recognises \"Posted an hour ago\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'Posted an hour ago' }, now);
  assert.strictEqual(result?.date.toISOString(), '2026-10-24T09:00:00.000Z');
});

test('findPostedDate recognises \"Posted a day ago\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'Posted a day ago' }, now);
  assert.strictEqual(result?.date.toISOString(), '2026-10-23T10:00:00.000Z');
});

test('findPostedDate recognises \"Posted a week ago\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'Posted a week ago' }, now);
  assert.strictEqual(result?.date.toISOString(), '2026-10-17T10:00:00.000Z');
});

test('findPostedDate recognises \"Senior Manager 24h Easy Apply\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'Senior Manager 24h Easy Apply' }, now);
  assert.strictEqual(result?.date.toISOString(), '2026-10-23T10:00:00.000Z');
});

test('findPostedDate recognises \"Senior Manager 7d Easy Apply\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'Senior Manager 7d Easy Apply' }, now);
  assert.strictEqual(result?.date.toISOString(), '2026-10-17T10:00:00.000Z');
});

test('findPostedDate recognises \"Senior Manager 30d+ Easy Apply\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'Senior Manager 30d+ Easy Apply' }, now);
  assert.strictEqual(result?.date.toISOString(), '2026-09-23T10:00:00.000Z');
});

test('findPostedDate recognises \"PostedPosted30+ days ago\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'PostedPosted30+ days ago' }, now);
  assert.strictEqual(result?.date.toISOString(), '2026-09-23T10:00:00.000Z');
});

test('findPostedDate recognises \"Just now\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'Just now' }, now);
  assert.strictEqual(result?.date.toISOString(), '2026-10-24T10:00:00.000Z');
});

test('findPostedDate ignores uppercase D in \"3D printing technician\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: '3D printing technician' }, now);
  assert.strictEqual(result, null);
});

test('findPostedDate ignores \"Apply within 30 days\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'Apply within 30 days' }, now);
  assert.strictEqual(result, null);
});

test('findPostedDate ignores \"Closes in 2 weeks\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'Closes in 2 weeks' }, now);
  assert.strictEqual(result, null);
});

test('findPostedDate ignores \"Founded 5 years ago\"', async () => {
  const now = new Date('2026-10-24T10:00:00Z');
  const result = findPostedDate({ text: 'Founded 5 years ago' }, now);
  assert.strictEqual(result, null);
});
