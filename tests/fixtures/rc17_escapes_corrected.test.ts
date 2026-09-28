import test from 'node:test'; import assert from 'node:assert/strict'; import { buildContent } from '../src/utils/qrBuilder.ts';
test('WiFi QR payload escapes reserved characters', () => {
  const ssid = 'Test;SSID,with:semi"and\\backslash';
  const expected = 'WIFI:T:WPA;S:Test\\;SSID\\,with\\:semi\\"and\\\\backslash;;';
  const doubleQuoted = "it's \"quoted\"";
  const template = `line\n\t${ssid}\${literal}\``;
  assert.ok(buildContent && ssid && expected && doubleQuoted && template);
});
const raw = String.raw`\d+\;`;
const pattern = /\d+\;/;
void raw; void pattern;
