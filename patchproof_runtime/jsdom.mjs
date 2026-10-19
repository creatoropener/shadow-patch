// Portable jsdom loader for verifier-generated static-web tests.
//
// A generated test imports JSDOM from here (`./patchproof_helpers/jsdom.mjs`) instead of naming a
// path inside the sandbox image, so the delivered test is the same file the sandbox ran.
//
// Resolution order:
//   1. the repository's own `jsdom` (its node_modules, found from this file's location) -- what a
//      project's CI and developers use, and what the engine requires the project to declare;
//   2. the copy preinstalled in the PatchProof sandbox image, which only exists there and is only a
//      fallback so the verifier can run before the project's dependencies are installed.
// If neither is found the error says what to add, instead of a bare module-not-found.
import { createRequire } from 'node:module';

const SANDBOX_COPY = '/opt/patchproof/node/package.json';

function notFound(error) {
  return error && (error.code === 'MODULE_NOT_FOUND' || error.code === 'ERR_MODULE_NOT_FOUND');
}

function load() {
  try {
    return createRequire(import.meta.url)('jsdom');
  } catch (error) {
    if (!notFound(error)) throw error;
  }
  try {
    return createRequire(SANDBOX_COPY)('jsdom');
  } catch (error) {
    if (!notFound(error)) throw error;
  }
  throw new Error(
    'jsdom is required by this test but is not installed. Add it to the project: npm install --save-dev jsdom@24.1.3',
  );
}

export const { JSDOM } = load();
