import test from 'node:test'; import assert from 'node:assert/strict'; import { buildContent } from '../src/utils/qrBuilder.ts'; import type { QRFormData } from '../src/types.ts';
test('WiFi QR payload escapes reserved characters in SSID and password', async () => {
  const formData: QRFormData = {
    type: 'wifi', url: '', text: '', phone: '',
    email: { address: '', subject: '', body: '' },
    wifi: { ssid: String.raw`Net;Work,Test:"Pass\Word`, pass: String.raw`Sec;Ret,Pas:s"Word`, sec: 'WPA' },
    vcard: { firstName: '', lastName: '', title: '', org: '', phone: '', email: '', url: '' },
  };
  const payload = buildContent(formData);
  assert.equal(payload, String.raw`WIFI:T:WPA;S:Net\;Work\,Test\:\"Pass\\Word;P:Sec\;Ret\,Pas\:s\"Word;;`);
});
