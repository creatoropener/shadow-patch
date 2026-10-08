import { strict as assert } from 'node:assert';
import { JSDOM } from 'jsdom';

async function loadHTML(filename) {
  const fs = await import('node:fs/promises');
  const content = await fs.readFile(filename, 'utf-8');
  return new JSDOM(content, { url: 'https://patchproof.invalid/', runScripts: 'outside-only' });
}

describe('Form action resolution', () => {
  it('submits to relative path based on current directory', async () => {
    const dom = await loadHTML('./index.html');
    const form = dom.window.document.querySelector('form.contact-form');
    assert.strictEqual(form.action, './thank-you.html');
  });
});
