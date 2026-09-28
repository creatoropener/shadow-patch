import test from 'node:test'; import assert from 'node:assert/strict'; import { buildContent } from '../src/utils/qrBuilder.ts'; import type { QRFormData } from '../src/types.ts';
test('WiFi QR payload escapes reserved characters in SSID and password', async () => {
  const formData: QRFormData = {
    type: 'wifi',
    url: '',
    text: '',
    phone: '',
    email: { address: '', subject: '', body: '' },
    wifi: {
      ssid: 'Test;SSID,with:semi\colon;quote"and\\backslash',
      pass: 'Pass;word,with:semi\colon;quote"and\\backslash',
      sec: 'WPA',
    },
    vcard: {
      firstName: '',
      lastName: '',
      title: '',
      org: '',
      phone: '',
      email: '',
      url: '',
    },
  };
  const payload = buildContent(formData);
  assert.equal(payload, 'WIFI:T:WPA;S:Test\;SSID\,with\:semi\\colon\;quote\"and\\\\backslash;P:Pass\;word\,with\:semi\\colon\;quote\"and\\\\backslash;;');
});
