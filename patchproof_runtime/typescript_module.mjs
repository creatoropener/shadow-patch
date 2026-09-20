// Loader for standalone TypeScript utilities, using the project's pinned compiler.
// It executes actual repository source; it does not substitute application logic.
import { readFileSync, realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('typescript');
const root = realpathSync(resolve(dirname(fileURLToPath(import.meta.url)), '..'));

export function loadStandaloneTypeScript(relativePath) {
  const filename = realpathSync(resolve(root, relativePath));
  const local = relative(root, filename);
  if (local.startsWith('..') || isAbsolute(local) || !filename.endsWith('.ts')) {
    throw new Error('The loader accepts only .ts files inside this repository.');
  }
  const source = readFileSync(filename, 'utf8');
  const parsed = ts.createSourceFile(filename, source, ts.ScriptTarget.ES2022, true);
  // This small loader deliberately does not resolve application import graphs.
  const check = (node) => {
    if (ts.isImportDeclaration(node) || ts.isImportEqualsDeclaration(node)
        || (ts.isExportDeclaration(node) && node.moduleSpecifier)
        || (ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword
          || (ts.isIdentifier(node.expression) && node.expression.text === 'require')))) {
      throw new Error('This loader supports standalone utilities without runtime imports.');
    }
    ts.forEachChild(node, check);
  };
  check(parsed);
  const result = ts.transpileModule(source, {
    fileName: filename,
    reportDiagnostics: true,
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  });
  const errors = [...parsed.parseDiagnostics, ...(result.diagnostics ?? [])]
    .filter((item) => item.category === ts.DiagnosticCategory.Error);
  if (errors.length) {
    throw new SyntaxError(errors.map((item) =>
      ts.flattenDiagnosticMessageText(item.messageText, '\n')).join('\n'));
  }
  const module = { exports: {} };
  // Transpilation is not type-checking or a security boundary; execution belongs
  // in the isolated sandbox, just like the rest of the application under test.
  const execute = new Function('module', 'exports', result.outputText);
  execute(module, module.exports);
  return module.exports;
}
