import { strict as assert } from 'node:assert';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';

const { JSDOM } = createRequire('/opt/patchproof/node/package.json')('jsdom');

async function getFormAction(filePath, baseUrl) {
  const html = readFileSync(filePath, 'utf8');
  const dom = new JSDOM(html, { url: baseUrl, runScripts: 'outside-only' });
  const form = dom.window.document.querySelector('form.contact-form');
  assert.ok(form, 'Contact form not found');
  return form.action;
}

it('should resolve relative to the page location when served from a subpath', async () => {
  const baseUrl = 'https://patchproof.invalid/Tabloop/';
  const action = await getFormAction('./index.html', baseUrl);
  assert.strictEqual(action, 'https://patchproof.invalid/Tabloop/thank-you.html');
});
