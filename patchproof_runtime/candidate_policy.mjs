// Parse application edits without importing or executing them. This is a bounded
// interference guard, not a security boundary against arbitrary hostile programs.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

try {
  const require = createRequire(path.join(process.env.PATCHPROOF_TYPESCRIPT_RUNTIME || '/opt/patchproof/node', 'package.json'));
  const ts = require('typescript');
  const payload = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const visit = (node, fn) => { fn(node); ts.forEachChild(node, child => visit(child, fn)); };
  const unwrap = node => {
    while (node && (ts.isParenthesizedExpression(node) || ts.isAsExpression(node)
      || ts.isAwaitExpression(node) || ts.isNonNullExpression(node))) node = node.expression;
    return node;
  };
  const moduleName = node => {
    node = unwrap(node);
    if (node && ts.isCallExpression(node) && node.arguments.length === 1
      && ts.isStringLiteral(node.arguments[0])
      && (node.expression.getText() === 'require' || node.expression.kind === ts.SyntaxKind.ImportKeyword)) {
      return node.arguments[0].text;
    }
    return '';
  };
  const sensitive = name => /^(node:)?(assert(\/strict)?|test|process|module)$/.test(name);
  function inspect(filename, content) {
    const tree = ts.createSourceFile(filename, content, ts.ScriptTarget.Latest, true);
    if (tree.parseDiagnostics.length) throw Error(`${filename}: candidate has parser diagnostics`);
    const aliases = new Set(['process', 'globalThis', 'global']);
    const bindings = [];
    visit(tree, node => {
      if (ts.isImportDeclaration(node) && sensitive(node.moduleSpecifier.text)) {
        if (node.importClause?.name) aliases.add(node.importClause.name.text);
        const named = node.importClause?.namedBindings;
        if (named && ts.isNamespaceImport(named)) aliases.add(named.name.text);
        if (named && ts.isNamedImports(named)) for (const binding of named.elements) aliases.add(binding.name.text);
      }
      if (ts.isVariableDeclaration(node)) bindings.push(node);
    });
    const rootName = expression => {
      let node = unwrap(expression);
      while (node && (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node))) node = unwrap(node.expression);
      return node && ts.isIdentifier(node) ? node.text : '';
    };
    for (let count = 0; count <= bindings.length; count++) {
      for (const binding of bindings) {
        if (sensitive(moduleName(binding.initializer)) || aliases.has(rootName(binding.initializer))) {
          if (ts.isIdentifier(binding.name)) aliases.add(binding.name.text);
          else for (const element of binding.name.elements) if (element.name && ts.isIdentifier(element.name)) aliases.add(element.name.text);
        }
      }
    }
    const violations = [];
    const protectedTarget = node => aliases.has(rootName(node)) || sensitive(moduleName(node));
    visit(tree, node => {
      if (ts.isBinaryExpression(node) && node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment
        && node.operatorToken.kind <= ts.SyntaxKind.LastAssignment && protectedTarget(node.left)) violations.push(node.getText(tree));
      if ((ts.isDeleteExpression(node) || ts.isPrefixUnaryExpression(node) || ts.isPostfixUnaryExpression(node))
        && protectedTarget(node.operand || node.expression)
        && (ts.isDeleteExpression(node) || [ts.SyntaxKind.PlusPlusToken, ts.SyntaxKind.MinusMinusToken].includes(node.operator))) violations.push(node.getText(tree));
      if (ts.isCallExpression(node)) {
        const name = node.expression.getText(tree);
        if (/^(Object|Reflect)\.(assign|defineProperty|defineProperties|setPrototypeOf|set|deleteProperty)$/.test(name)
          && node.arguments[0] && protectedTarget(node.arguments[0])) violations.push(node.getText(tree));
        if (protectedTarget(node.expression) && /(?:\.|\[['"])(exit|reallyExit|abort|setSourceMapsEnabled|_load|_resolveFilename)(?:['"]\])?$/.test(name)) violations.push(node.getText(tree));
      }
    });
    const declarations = new Map();
    for (const statement of tree.statements) {
      if (statement.name && ts.isIdentifier(statement.name)) declarations.set(statement.name.text, statement.getText(tree));
      if (ts.isVariableStatement(statement)) for (const node of statement.declarationList.declarations) {
        if (ts.isIdentifier(node.name)) declarations.set(node.name.text, statement.getText(tree));
      }
    }
    return { violations, declarations };
  }
  for (const file of payload.files) {
    const old = inspect(file.path, file.original);
    const updated = inspect(file.path, file.content);
    const remaining = [...old.violations];
    for (const violation of updated.violations) {
      const index = remaining.indexOf(violation);
      if (index < 0) throw Error(`${file.path}: candidate introduces test/runtime interference: ${violation.slice(0, 160)}`);
      remaining.splice(index, 1);
    }
    for (const name of file.protected_symbols || []) {
      if (!old.declarations.has(name) || old.declarations.get(name) !== updated.declarations.get(name)) {
        throw Error(`scope_failed: protected symbol ${file.path}:${name} changed or is missing`);
      }
    }
  }
  console.log('PATCHPROOF_CANDIDATE_POLICY=passed');
} catch (error) {
  console.error(String(error));
  console.error('PATCHPROOF_CANDIDATE_POLICY=failed');
  process.exitCode = 1;
}
