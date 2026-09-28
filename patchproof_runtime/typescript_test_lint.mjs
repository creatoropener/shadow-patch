#!/usr/bin/env node

import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

function fail(message, marker = 'PATCHPROOF_TYPESCRIPT_LINT=unavailable') {
  process.stderr.write(`${message}\n${marker}\n`);
  process.exitCode = 2;
}

// Escapes that carry meaning inside a JavaScript/TypeScript string or template
// literal. Anything else (`\;`, `\,`, `\:`, `\c`, or the "wrong" quote character)
// is an identity escape: the backslash is silently dropped, so the runtime value
// is NOT what the author most likely intended (typically a literal backslash).
const MEANINGFUL_ESCAPES = new Set([
  '\\', 'n', 'r', 't', 'b', 'f', 'v', 'u', 'x',
  '0', '1', '2', '3', '4', '5', '6', '7', '8', '9',
  '\n', '\r', '\u2028', '\u2029',
]);

function uselessEscapes(inner, delimiter) {
  const found = [];
  for (let index = 0; index < inner.length; index += 1) {
    if (inner[index] !== '\\') continue;
    const next = inner[index + 1];
    if (next === undefined) break;
    // A backslash before ANY quote character yields exactly that quote character,
    // which is what the author almost always means (\" inside '...' is a style
    // nit, not a changed value). Only escapes that silently turn an intended
    // literal backslash into nothing (\; \, \: \c ...) are gated.
    const meaningful = MEANINGFUL_ESCAPES.has(next)
      || next === '"' || next === "'" || next === '`'
      || next === delimiter
      || (delimiter === '`'
        && ((next === '$' && inner[index + 2] === '{')
          || (next === '{' && inner[index - 1] === '$')));
    if (!meaningful) found.push({ index, char: next });
    index += 1; // the escaped character is consumed
  }
  return found;
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
      // Resolve `typescript` from PatchProof's own pinned runtime toolchain
      // (baked into the sandbox image alongside tsx — see prepare-image.yml),
      // never from the target repository's own node_modules. This AST-based
      // structural lint needs the classic TypeScript Compiler API; a target
      // repo pinned to a bare TypeScript 7.x (the native Go compiler, which
      // does not ship that API until 7.1) would otherwise break this step
      // for every one of its generated tests, regardless of content.
      // PATCHPROOF_TYPESCRIPT_RUNTIME lets local/dev runs (see
      // TypeScriptLintIntegrationTests) point this at an arbitrary installed
      // TypeScript for testing; it always defaults to the real sandbox path.
      const runtimeRoot = process.env.PATCHPROOF_TYPESCRIPT_RUNTIME || '/opt/patchproof/node';
      const requireFromPatchProofRuntime = createRequire(path.join(runtimeRoot, 'package.json'));
      const ts = requireFromPatchProofRuntime('typescript');
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
        fail('Generated TypeScript test has parser diagnostics.', 'PATCHPROOF_TYPESCRIPT_PARSE=failed');
      } else {
        // Enforce the conventional generated stream-test contract structurally.
        // This is deliberately narrower than arbitrary JavaScript data-flow analysis.
        const contractErrors = [];
        const visit = (node, fn) => { fn(node); ts.forEachChild(node, child => visit(child, fn)); };
        const callName = node => ts.isCallExpression(node) ? node.expression.getText(sourceFile) : '';
        // Useless-escape gate (ESLint no-useless-escape semantics, strings and
        // templates only; regex literals and tagged templates such as String.raw
        // are left alone). Reported once per literal position, capped for brevity.
        const escapeDiagnostics = [];
        const scanLiteral = (node, delimiter, startTrim, endTrim) => {
          const text = node.getText(sourceFile);
          const inner = text.slice(startTrim, text.length - endTrim);
          for (const item of uselessEscapes(inner, delimiter)) {
            const position = sourceFile.getLineAndCharacterOfPosition(
              node.getStart(sourceFile) + startTrim + item.index,
            );
            escapeDiagnostics.push(
              `${targetArg}:${position.line + 1}:${position.character + 1}: useless string escape `
              + `'\\${item.char}' evaluates to just '${item.char}' (the backslash is dropped). `
              + `If you want only '${item.char}', remove the backslash. If you want a literal `
              + `backslash followed by '${item.char}', write two backslashes: '\\\\${item.char}'`,
            );
          }
        };
        visit(sourceFile, node => {
          if (ts.isStringLiteral(node)) {
            scanLiteral(node, node.getText(sourceFile)[0], 1, 1);
          } else if (ts.isNoSubstitutionTemplateLiteral(node)
            && !(node.parent && ts.isTaggedTemplateExpression(node.parent))) {
            scanLiteral(node, '`', 1, 1);
          } else if (ts.isTemplateExpression(node)
            && !(node.parent && ts.isTaggedTemplateExpression(node.parent))) {
            scanLiteral(node.head, '`', 1, 2);
            for (const span of node.templateSpans) {
              scanLiteral(span.literal, '`', 1, ts.isTemplateMiddle(span.literal) ? 2 : 1);
            }
          }
        });
        visit(sourceFile, node => {
          if (!ts.isCallExpression(node) || !['test', 'it'].includes(callName(node))) return;
          const callback = node.arguments.find(arg => ts.isArrowFunction(arg) || ts.isFunctionExpression(arg));
          if (!callback) return;
          const calls = [];
          visit(callback.body, child => { if (ts.isCallExpression(child)) calls.push(child); });
          const consumers = calls.filter(call => callName(call) === 'collectBytes');
          const equality = calls.some(call => /^assert\.(deepStrictEqual|strictEqual|equal)$/.test(callName(call)));
          const pipeline = calls.some(call => ts.isPropertyAccessExpression(call.expression)
            && call.expression.name.text === 'pipeThrough');
          if (consumers.length && equality && pipeline) {
            const guards = calls.filter(call => callName(call) === 'assert.doesNotReject'
              && ts.isAwaitExpression(call.parent)
              && call.arguments[0]
              && (ts.isArrowFunction(call.arguments[0]) || ts.isFunctionExpression(call.arguments[0]))
              && call.arguments[0].modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.AsyncKeyword));
            const guarded = operation => guards.some(guard => {
              for (let parent = operation.parent; parent && parent !== callback; parent = parent.parent) {
                if (parent === guard.arguments[0]) return true;
              }
              return false;
            });
            const operations = calls.filter(call => callName(call) !== 'assert.doesNotReject'
              && (callName(call) === 'collectBytes'
                || (ts.isPropertyAccessExpression(call.expression) && call.expression.name.text === 'pipeThrough')
                || ts.isAwaitExpression(call.parent)));
            if (!guards.length || operations.some(operation => !guarded(operation))) {
              contractErrors.push('Stream success contract: put awaited application operations, pipeThrough and collectBytes inside an awaited assert.doesNotReject(async () => { ... }); then compare output.');
            }
          }
          const title = node.arguments[0];
          if (!title || !ts.isStringLiteralLike(title) || !/partial/i.test(title.text)) return;
          const bindings = new Map();
          visit(sourceFile, child => {
            if (ts.isVariableDeclaration(child) && ts.isIdentifier(child.name)) {
              const entries = bindings.get(child.name.text) ?? [];
              entries.push(child.initializer);
              bindings.set(child.name.text, entries);
            }
          });
          const resolve = (expression, depth = 0) => {
            if (!expression || depth > 8) return undefined;
            if (ts.isIdentifier(expression)) {
              const entries = bindings.get(expression.text);
              return entries?.length === 1 ? resolve(entries[0], depth + 1) : undefined;
            }
            return expression;
          };
          const sources = calls.filter(call => callName(call) === 'readableFromBytes');
          const sizes = [];
          for (const call of calls) for (const arg of call.arguments) {
            if (ts.isObjectLiteralExpression(arg)) for (const property of arg.properties) {
              if (ts.isPropertyAssignment(property) && property.name.getText(sourceFile) === 'chunkSize') {
                sizes.push(resolve(property.initializer));
              }
            }
          }
          // Ambiguous or computed values are not guessed. Input segmentation is
          // not the application chunkSize and is never used as a substitute.
          if (sources.length !== 1 || sizes.length !== 1) return;
          const fixture = resolve(sources[0].arguments[0]);
          const size = sizes[0];
          if (!fixture || !size || !ts.isNumericLiteral(size)) return;
          const chunk = Number(size.text);
          let length;
          if (ts.isNewExpression(fixture) && fixture.expression.getText(sourceFile) === 'Uint8Array') {
            const values = fixture.arguments?.[0];
            if (values && ts.isArrayLiteralExpression(values)
              && values.elements.every(value => ts.isNumericLiteral(value))) length = values.elements.length;
          } else if (ts.isCallExpression(fixture) && ts.isPropertyAccessExpression(fixture.expression)
            && fixture.expression.name.text === 'encode'
            && ts.isNewExpression(fixture.expression.expression)
            && fixture.expression.expression.expression.getText(sourceFile) === 'TextEncoder'
            && fixture.arguments[0] && ts.isStringLiteralLike(fixture.arguments[0])) {
            length = Buffer.byteLength(fixture.arguments[0].text, 'utf8');
          }
          if (length === undefined || !Number.isSafeInteger(chunk) || chunk <= 0) return;
          if (length % chunk === 0 || (/\bfull\b/i.test(title.text) && length <= chunk)) {
            contractErrors.push(`Chunk coverage contract: ${length} fixture bytes with application chunkSize ${chunk} do not support the claimed full/partial coverage. Use a non-multiple; for full and partial coverage exceed one chunk.`);
          }
        });
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

        let literalFailed = false;
        if (escapeDiagnostics.length > 0) {
          literalFailed = true;
          for (const line of escapeDiagnostics.slice(0, 12)) process.stderr.write(`${line}\n`);
          if (escapeDiagnostics.length > 12) {
            process.stderr.write(`...and ${escapeDiagnostics.length - 12} more useless escapes\n`);
          }
          process.stderr.write('PATCHPROOF_TYPESCRIPT_LITERAL=failed\n');
          process.exitCode = 2;
        }

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
            'PATCHPROOF_TYPESCRIPT_LINT=failed',
          );
        } else if (contractErrors.length) {
          fail(contractErrors.join('\n'), 'PATCHPROOF_TYPESCRIPT_CONTRACT=failed');
        } else if (!literalFailed) {
          process.stdout.write('PATCHPROOF_TYPESCRIPT_LINT=passed\n');
        }
      }
    } catch (error) {
      fail(`Unable to lint generated TypeScript test: ${error.message}`);
    }
  }
}
