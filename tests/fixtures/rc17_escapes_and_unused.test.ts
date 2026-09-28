import test from 'node:test'; import assert from 'node:assert/strict';
test('both problems at once', () => {
  const unusedHelper = 'x';
  assert.equal('a\;b', 'a;b');
});
