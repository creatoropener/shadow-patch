import { strict as assert } from 'node:assert';
import { JSDOM } from 'jsdom';

async function loadFormActionFromFile(filePath, baseUrl) {
  const fs = await import('node:fs');
  const html = fs.readFileSync(filePath, 'utf8');
  const dom = new JSDOM(html, { url: baseUrl, runScripts: 'outside-only' });
  const form = dom.window.document.querySelector('form.contact-form');
  assert.ok(form, 'Contact form not found');
  return form.action;
}

describe('Contact form action resolution', () => {
  it('should resolve relative to the page location when served from a subpath', async () => {
    const baseUrl = 'https://patchproof.invalid/Tabloop/';
    const action = await loadFormActionFromFile('./index.html', baseUrl);
    assert.strictEqual(action, 'https://patchproof.invalid/Tabloop/thank-you.html');
  });
});
