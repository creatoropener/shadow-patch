#!/usr/bin/env node

import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

function fail(message) {
  process.stderr.write(`${message}\nPATCHPROOF_TYPESCRIPT_LINT=failed\n`);
  process.exitCode = 2;
}

const [targetArg] = process.argv.slice(2);
if (!targetArg) {
  fail('usage: typescript_test_lint.mjs <generated-test.ts>');
} else {
  const root = process.cwd();
  const target = path.resolve(root, targetArg);
  const relative = path.relative(root, target);
  if (
    relative.startsWith(`..${path.sep}`)
    || path.isAbsolute(relative)
    || path.extname(target) !== '.ts'
    || !fs.existsSync(target)
  ) {
    fail('Generated TypeScript test must be an existing repository-relative .ts file.');
  } else {
    try {
      const requireFromProject = createRequire(path.join(root, 'package.json'));
      const ts = requireFromProject('typescript');
      const source = fs.readFileSync(target, 'utf8');
      const sourceFile = ts.createSourceFile(
        target,
        source,
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TS,
      );

      if (sourceFile.parseDiagnostics.length > 0) {
        for (const diagnostic of sourceFile.parseDiagnostics) {
          const start = diagnostic.start ?? 0;
          const position = sourceFile.getLineAndCharacterOfPosition(start);
          const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n');
          process.stderr.write(
            `${targetArg}:${position.line + 1}:${position.character + 1}: ${message}\n`,
          );
        }
        fail('Generated TypeScript test has parser diagnostics.');
      } else {
        const declarations = new Map();
        const declarationNodes = new Set();

        function recordBinding(name) {
          if (ts.isIdentifier(name)) {
            declarationNodes.add(name);
            const locations = declarations.get(name.text) ?? [];
            locations.push(name);
            declarations.set(name.text, locations);
            return;
          }
          if (ts.isObjectBindingPattern(name) || ts.isArrayBindingPattern(name)) {
            for (const element of name.elements) {
              if (ts.isBindingElement(element)) recordBinding(element.name);
            }
          }
        }

        function collect(node) {
          if (ts.isVariableDeclaration(node)) recordBinding(node.name);
          ts.forEachChild(node, collect);
        }
        collect(sourceFile);

        const references = new Map();
        function count(node) {
          if (
            ts.isIdentifier(node)
            && declarations.has(node.text)
            && !declarationNodes.has(node)
          ) {
            references.set(node.text, (references.get(node.text) ?? 0) + 1);
          }
          ts.forEachChild(node, count);
        }
        count(sourceFile);

        const unused = [];
        for (const [name, nodes] of declarations) {
          if ((references.get(name) ?? 0) === 0) {
            const position = sourceFile.getLineAndCharacterOfPosition(nodes[0].getStart());
            unused.push({ name, line: position.line + 1, column: position.character + 1 });
          }
        }

        if (unused.length > 0) {
          for (const item of unused) {
            process.stderr.write(
              `${targetArg}:${item.line}:${item.column}: generated-test binding `
              + `'${item.name}' is declared but never used\n`,
            );
          }
          fail(
            'Every constructed helper, stream, or transform must participate in the asserted behavior.',
          );
        } else {
          process.stdout.write('PATCHPROOF_TYPESCRIPT_LINT=passed\n');
        }
      }
    } catch (error) {
      fail(`Unable to lint generated TypeScript test: ${error.message}`);
    }
  }
}
