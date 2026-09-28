import test from 'node:test'; import assert from 'node:assert/strict'; import { buildContent } from '../src/utils/qrBuilder.ts'; import type { QRFormData } from '../src/types.ts';
test('WiFi QR payload escapes reserved characters in SSID and password', async () => {
  const formData: QRFormData = {
    type: 'wifi',
    url: '',
    text: '',
    phone: '',
    email: { address: '', subject: '', body: '' },
    wifi: {
      ssid: 'Net;Work,Test:\"Pass\\Word',
      pass: 'Sec;Ret,Pas:s\"Wo\r\nrd',
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
  assert.equal(payload, 'WIFI:T:WPA;S:Net\\;Work\\,Test\\:\\\"Pass\\\\Word;P:Sec\\;Ret\\,Pas\\:s\\\"Wo\\\\r\\\\nrd;;');
});
