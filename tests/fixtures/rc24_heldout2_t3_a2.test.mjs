import { strict as assert } from 'node:assert';
import { promises as fs } from 'node:fs';
import { createRequire } from 'node:module';
const { JSDOM } = createRequire('/opt/patchproof/node/package.json')('jsdom');

async function loadHTML(filename) {
  const content = await fs.readFile(filename, 'utf-8');
  return new JSDOM(content, { url: 'https://patchproof.invalid/', runScripts: 'outside-only' });
}

it('form action resolves relative to base URL when deployed in subpath', async () => {
  const dom = await loadHTML('./index.html');
  const form = dom.window.document.querySelector('form.contact-form');
  // Simulate deployment at subpath /Tabloop/
  const baseURL = new URL('https://patchproof.invalid/Tabloop/');
  const resolved = new URL(form.action, baseURL);
  assert.strictEqual(resolved.pathname, '/Tabloop/thank-you.html');
});
