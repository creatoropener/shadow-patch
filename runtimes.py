"""Runtime adapters for PatchProof's language-neutral orchestration layer."""

from __future__ import annotations

import json
import os
import shlex
import re
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple


class RuntimeDetectionError(ValueError):
    """Raised when a repository cannot be mapped to a supported runtime."""


def _unused_initialized_bindings(content: str) -> list[str]:
    """Find simple generated-test locals that are declared but never referenced.

    This fast runner-side check intentionally handles only ordinary ``const`` and
    ``let`` identifiers. The sandbox repeats the check with the TypeScript parser.
    Counting lexical identifier occurrences can miss a name repeated in a comment
    or another scope, but it does not reject a binding that is genuinely referenced.
    """
    unused: list[str] = []
    pattern = re.compile(
        r"\b(?:const|let)\s+([A-Za-z_$][\w$]*)\s*"
        r"(?::[^=;\n]+)?\s*="
    )
    for match in pattern.finditer(content):
        name = match.group(1)
        references = re.findall(
            rf"(?<![\w$]){re.escape(name)}(?![\w$])", content
        )
        if len(references) == 1:
            unused.append(name)
    return sorted(set(unused))


def _js_code_only(content: str) -> str:
    """Mask comments and strings for conservative runner-side presence checks."""
    return re.sub(
        r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`",
        lambda match: re.sub(r"[^\n]", " ", match.group()), content,
    )


def _missing_async_success_guard(content: str) -> bool:
    code = _js_code_only(content)
    return bool(
        re.search(r"\.pipeThrough\s*\(", code)
        and re.search(r"\bcollectBytes\s*\(", code)
        and re.search(r"\bassert\.(?:deepStrictEqual|strictEqual|equal)\s*\(", code)
        and not re.search(r"\bawait\s+assert\.doesNotReject\s*\(", code)
    )


_TYPESCRIPT_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts"})
_NODE_TEST_IMPORT = "import test from 'node:test';"
_NODE_ASSERT_IMPORT = "import assert from 'node:assert/strict';"


def _without_comments(content: str) -> str:
    """Drop whole-line and block comments; module specifiers stay visible."""
    return re.sub(r"(?m)^[ \t]*//[^\n]*$|/\*[\s\S]*?\*/", "", content)


def _missing_node_test_imports(content: str) -> list[str]:
    """Return the import lines a generated node:test file needs but lacks.

    Under tsx, ``test`` and ``assert`` are not globals. Without the imports the
    sandbox type-check fails (TS2582/TS2304) and a model that reads the compiler's
    "install @types/jest" hint tends to resubmit the same file unchanged.
    """
    source = _without_comments(content)
    missing: list[str] = []
    if not re.search(r"""(?:\bfrom\s*|\brequire\s*\(\s*)['"]node:test['"]""", source):
        missing.append(_NODE_TEST_IMPORT)
    uses_assert = re.search(r"(?<![\w$.])assert\s*[.(]", _js_code_only(source))
    if uses_assert and not re.search(
        r"""(?:\bfrom\s*|\brequire\s*\(\s*)['"]node:assert(?:/strict)?['"]""", source
    ):
        missing.append(_NODE_ASSERT_IMPORT)
    return missing


# --------------------------------------------------------------------------- #
# node:test names and bare imports in generated ESM tests (rc.24)
# --------------------------------------------------------------------------- #

# rc.24: the pre-execution import check above only ran for node-typescript. A static-web
# test that called describe() or it() without importing them was executed in the sandbox,
# died with "ReferenceError: describe is not defined" (node:test reports that as a generic
# `test failed`, never accepted as assertion evidence), and the model, told only "test
# failed without accepted assertion evidence", swapped describe for it and back without
# ever adding the import (heldout-2, rc.23, trials 1 and 3: six executions in all).
_NODE_TEST_NAMES = (
    "describe", "it", "test", "before", "after", "beforeEach", "afterEach",
)
_NODE_ASSERT_SPECIFIER = re.compile(
    r"""(?:\bfrom\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)['"](?:node:)?assert(?:/strict)?['"]"""
)


def _import_binds(source: str, name: str) -> bool:
    """True when an import or require in ``source`` binds the local identifier ``name``."""
    pattern = rf"(?<![\w$.]){re.escape(name)}(?![\w$])"
    for match in re.finditer(r"\bimport\s+([^'\"();]*?)\s*from\s*['\"][^'\"]+['\"]", source):
        if re.search(pattern, match.group(1)):
            return True
    for match in re.finditer(
        r"(?:const|let|var)\s*(\{[^}]*\}|[A-Za-z_$][\w$]*)\s*=\s*(?:await\s+)?(?:require|import)\s*\(",
        source,
    ):
        if re.search(pattern, match.group(1)):
            return True
    return False


def _node_test_bindings(source: str) -> set[str] | None:
    """Local names bound from 'node:test', or None when that module is never imported."""
    bound: set[str] = set()
    found = False
    for match in re.finditer(r"\bimport\s+([^'\"();]*?)\s*from\s*['\"]node:test['\"]", source):
        found = True
        clause = match.group(1)
        named = re.search(r"\{([^}]*)\}", clause)
        if named:
            for part in named.group(1).split(","):
                part = part.strip()
                if part:
                    bound.add(re.split(r"\s+as\s+", part)[-1].strip())
            clause = clause.replace(named.group(0), " ")
        namespace = re.search(r"\*\s*as\s+([A-Za-z_$][\w$]*)", clause)
        if namespace:
            bound.add(namespace.group(1))  # reached as ns.test(...), never as a bare name
            clause = clause.replace(namespace.group(0), " ")
        default = re.search(r"([A-Za-z_$][\w$]*)", clause)
        if default:
            bound.add(default.group(1))
    for match in re.finditer(
        r"""(?:const|let|var)\s*\{([^}]*)\}\s*=\s*(?:await\s+)?(?:require|import)\s*\(\s*['"]node:test['"]\s*\)""",
        source,
    ):
        found = True
        for part in match.group(1).split(","):
            part = part.strip()
            if part:
                bound.add(re.split(r"\s*:\s*", part)[-1].strip())
    for match in re.finditer(
        r"""(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:await\s+)?(?:require|import)\s*\(\s*['"]node:test['"]\s*\)""",
        source,
    ):
        found = True
        bound.add(match.group(1))
    if not found and re.search(
        r"""(?:\bfrom\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)['"]node:test['"]""", source
    ):
        found = True  # e.g. a side-effect import; nothing is bound
    return bound if found else None


def _node_test_names_used(code: str) -> list[str]:
    """node:test functions called as bare names (``code`` has strings and comments masked)."""
    used: list[str] = []
    for name in _NODE_TEST_NAMES:
        if not re.search(rf"(?<![\w$.]){name}\s*(?:\(|\.(?:skip|only|todo)\b)", code):
            continue
        if re.search(rf"\b(?:function|class|const|let|var)\s+{name}\b", code):
            continue  # the file defines its own helper with that name
        used.append(name)
    return used


def _node_test_import_line(names: list[str]) -> str:
    ordered = [name for name in _NODE_TEST_NAMES if name in names]
    if ordered == ["test"]:
        return _NODE_TEST_IMPORT
    return "import { " + ", ".join(ordered) + " } from 'node:test';"


def missing_node_test_imports(content: str) -> list[str]:
    """Import lines a generated node:test ESM file needs but lacks (rc.24).

    Unlike ``_missing_node_test_imports`` this looks at which names the file really
    calls: ``describe`` and ``it`` are not globals either, so importing only ``test``
    does not make ``describe(...)`` work. ``node:assert`` may also be imported as
    ``assert`` or ``assert/strict``, with or without the ``node:`` prefix.
    """
    source = _without_comments(content)
    code = _js_code_only(source)
    used = _node_test_names_used(code)
    bound = _node_test_bindings(source)
    names = (used or ["test"]) if bound is None else [n for n in used if n not in bound]
    missing: list[str] = []
    if names:
        missing.append(_node_test_import_line(names))
    uses_assert = re.search(r"(?<![\w$.])assert\s*[.(]", code)
    if uses_assert and not (
        _NODE_ASSERT_SPECIFIER.search(source) or _import_binds(source, "assert")
    ):
        missing.append(_NODE_ASSERT_IMPORT)
    return missing


def imports_bare_jsdom(content: str) -> bool:
    """True when a test imports jsdom by name; the package lives outside the repository."""
    return bool(re.search(
        r"""(?:\bfrom\s*|\brequire\s*\(\s*|\bimport\s*\(\s*)['"]jsdom['"]""",
        _without_comments(content),
    ))


_JSDOM_LOADER = (
    "import { createRequire } from 'node:module'; "
    "const { JSDOM } = createRequire('/opt/patchproof/node/package.json')('jsdom');"
)


# --------------------------------------------------------------------------- #
# Error-message pins in generated tests (rc.24)
# --------------------------------------------------------------------------- #

# rc.22 and rc.23 told the verifier not to match error wording the issue never states, and
# on heldout-1 four of four accepted tests did it anyway (/Invalid target: .../, /blocked/,
# /Invalid URL: http:\/\/127.0.0.1/, /SSRF protection: .../); one of them asked for a message
# that no reasonable repair would produce. A prompt rule lowers a rate; this is the check. It reads
# the generated test, finds the regex or string literals used to match an error message,
# and asks of each whether the issue contains that wording.
_REGEX_AFTER_WORDS = frozenset(
    {"return", "typeof", "case", "in", "of", "void", "delete", "throw", "new", "else", "do"}
)


class _Tok(NamedTuple):
    kind: str  # word, number, string, template, regex or punct
    text: str
    start: int
    end: int


class _Pin(NamedTuple):
    kind: str  # "regex" or "string"
    text: str  # the regex source, or the string value
    form: str  # the assertion form it was found in


def _skip_quoted(source: str, i: int) -> int:
    quote, i, n = source[i], i + 1, len(source)
    while i < n:
        if source[i] == "\\":
            i += 2
        elif source[i] == quote:
            return i + 1
        else:
            i += 1
    return n


def _skip_template(source: str, i: int) -> int:
    i, n = i + 1, len(source)
    while i < n:
        char = source[i]
        if char == "\\":
            i += 2
        elif char == "`":
            return i + 1
        elif char == "$" and source[i + 1:i + 2] == "{":
            i, depth = i + 2, 1
            while i < n and depth:
                inner = source[i]
                if inner == "`":
                    i = _skip_template(source, i)
                    continue
                if inner in "'\"":
                    i = _skip_quoted(source, i)
                    continue
                depth += (inner == "{") - (inner == "}")
                i += 1
        else:
            i += 1
    return n


def _skip_regex(source: str, i: int) -> int:
    i, n, in_class = i + 1, len(source), False
    while i < n:
        char = source[i]
        if char == "\\":
            i += 2
            continue
        if char == "\n":
            return i
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            i += 1
            while i < n and source[i].isalpha():
                i += 1
            return i
        i += 1
    return n


def _js_tokens(source: str) -> list[_Tok]:
    """A small JavaScript tokenizer: words, punctuation, strings, templates and regexes.

    Comments are dropped. A slash starts a regular expression unless the previous token
    ends an expression; that is a heuristic, adequate for the assertion forms read below.
    """
    tokens: list[_Tok] = []
    i, n = 0, len(source)

    def add(kind: str, end: int) -> None:
        nonlocal i
        tokens.append(_Tok(kind, source[i:end], i, end))
        i = end

    while i < n:
        char = source[i]
        if char.isspace():
            i += 1
        elif source.startswith("//", i):
            end = source.find("\n", i)
            i = n if end < 0 else end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif char in "'\"":
            add("string", _skip_quoted(source, i))
        elif char == "`":
            add("template", _skip_template(source, i))
        elif char == "/":
            last = tokens[-1] if tokens else None
            starts_regex = (
                last is None
                or (last.kind == "punct" and last.text not in {")", "]", "}"})
                or (last.kind == "word" and last.text in _REGEX_AFTER_WORDS)
            )
            add("regex", _skip_regex(source, i)) if starts_regex else add("punct", i + 1)
        elif char.isalpha() or char in "_$":
            end = i + 1
            while end < n and (source[end].isalnum() or source[end] in "_$"):
                end += 1
            add("word", end)
        elif char.isdigit():
            end = i + 1
            while end < n and (source[end].isalnum() or source[end] == "."):
                end += 1
            add("number", end)
        else:
            add("punct", i + 1)
    return tokens


def _call_arguments(tokens: list[_Tok], open_index: int) -> list[list[_Tok]]:
    """The top-level arguments of the call whose "(" is ``tokens[open_index]``."""
    arguments: list[list[_Tok]] = []
    current: list[_Tok] = []
    depth = 0
    for token in tokens[open_index:]:
        if token.kind == "punct" and token.text in "([{":
            depth += 1
            if depth > 1:
                current.append(token)
        elif token.kind == "punct" and token.text in ")]}":
            depth -= 1
            if depth == 0:
                if current:
                    arguments.append(current)
                return arguments
            current.append(token)
        elif token.kind == "punct" and token.text == "," and depth == 1:
            arguments.append(current)
            current = []
        else:
            current.append(token)
    return arguments


def _string_value(token: _Tok) -> str | None:
    if token.kind == "string" or (token.kind == "template" and "${" not in token.text):
        return re.sub(r"\\(.)", r"\1", token.text[1:-1])
    return None


def _literal_pin(argument: list[_Tok], form: str) -> _Pin | None:
    """A regex or plain string literal standing alone as an argument."""
    if len(argument) != 1:
        return None
    token = argument[0]
    if token.kind == "regex":
        return _Pin("regex", token.text[1:token.text.rfind("/")], form)
    value = _string_value(token)
    return _Pin("string", value, form) if value is not None else None


def _object_message_pin(argument: list[_Tok], form: str) -> _Pin | None:
    """The value of a ``message:`` property when it is a regex or string literal."""
    if not argument or argument[0].text != "{":
        return None
    depth = 0
    for index, token in enumerate(argument):
        if token.kind == "punct" and token.text in "([{":
            depth += 1
        elif token.kind == "punct" and token.text in ")]}":
            depth -= 1
        elif (depth == 1 and token.kind in {"word", "string"}
              and token.text.strip("'\"") == "message"
              and index + 1 < len(argument) and argument[index + 1].text == ":"):
            value, inner = [], 0
            for follower in argument[index + 2:]:
                if follower.kind == "punct" and follower.text in "([{":
                    inner += 1
                elif follower.kind == "punct" and follower.text in ")]}":
                    if inner == 0:
                        break
                    inner -= 1
                elif follower.kind == "punct" and follower.text == "," and inner == 0:
                    break
                value.append(follower)
            return _literal_pin(value, form)
    return None


def _message_pins(content: str) -> list[_Pin]:
    """Regex and string literals this test uses to match an error's message text."""
    source = _without_comments(content)
    tokens = _js_tokens(source)
    pins: list[_Pin] = []

    def negated(index: int) -> bool:
        before = index - 1
        while before >= 0 and tokens[before].text == "(":
            before -= 1
        return (before >= 0 and tokens[before].text == "!"
                and not (before + 1 < len(tokens) and tokens[before + 1].text == "="))

    def chain_start(index: int) -> int:
        while index >= 2 and tokens[index - 1].text == "." and tokens[index - 2].kind == "word":
            index -= 2
        return index

    def mentions_message(argument: list[_Tok]) -> bool:
        return any(t.kind == "word" and t.text in {"message", "stack"} for t in argument) or any(
            t.kind == "word" and t.text in {"String", "toString"} for t in argument)

    for index, token in enumerate(tokens):
        text = token.text
        # assert.rejects(p, /re/) | assert.rejects(p, { message: /re/ }) | assert.throws(...)
        if (token.kind == "word" and text in {"rejects", "throws"} and index >= 2
                and tokens[index - 1].text == "." and tokens[index - 2].text in {"assert", "strict"}
                and index + 1 < len(tokens) and tokens[index + 1].text == "("):
            arguments = _call_arguments(tokens, index + 1)
            if len(arguments) >= 2:
                second = arguments[1]
                found = (_literal_pin(second, f"assert.{text}") if second and second[0].kind == "regex"
                         else _object_message_pin(second, f"assert.{text}"))
                if found:
                    pins.append(found)
        # assert.match(err.message, /re/)
        elif (token.kind == "word" and text == "match" and index >= 2
              and tokens[index - 1].text == "." and tokens[index - 2].text in {"assert", "strict"}
              and index + 1 < len(tokens) and tokens[index + 1].text == "("):
            arguments = _call_arguments(tokens, index + 1)
            if len(arguments) >= 2 and mentions_message(arguments[0]):
                found = _literal_pin(arguments[1], "assert.match")
                if found and found.kind == "regex":
                    pins.append(found)
        # assert.strictEqual(err.message, 'text')
        elif (token.kind == "word" and text in {"strictEqual", "equal", "deepStrictEqual", "deepEqual"}
              and index >= 2 and tokens[index - 1].text == "."
              and tokens[index - 2].text in {"assert", "strict"}
              and index + 1 < len(tokens) and tokens[index + 1].text == "("):
            arguments = _call_arguments(tokens, index + 1)
            if len(arguments) >= 2:
                for message_side, other in ((arguments[0], arguments[1]), (arguments[1], arguments[0])):
                    ends_in_message = (len(message_side) >= 3 and message_side[-1].text == "message"
                                       and message_side[-2].text == ".")
                    found = _literal_pin(other, f"assert.{text}") if ends_in_message else None
                    if found and found.kind == "string":
                        pins.append(found)
        # /re/.test(err.message)
        elif (token.kind == "regex" and index + 3 < len(tokens)
              and tokens[index + 1].text == "." and tokens[index + 2].text == "test"
              and tokens[index + 3].text == "("):
            arguments = _call_arguments(tokens, index + 3)
            if arguments and any(t.text == "message" for t in arguments[0]) and not negated(index):
                found = _literal_pin([token], "regex test on message")
                if found:
                    pins.append(found)
        # err.message.includes('text') | .startsWith | .endsWith | .match(/re/)
        elif (token.kind == "word" and text == "message" and index + 3 < len(tokens)
              and tokens[index + 1].text == "." and tokens[index + 2].kind == "word"
              and tokens[index + 3].text == "(" and index >= 1 and tokens[index - 1].text == "."):
            method = tokens[index + 2].text
            if method in {"includes", "startsWith", "endsWith", "match"} and not negated(chain_start(index)):
                arguments = _call_arguments(tokens, index + 3)
                found = _literal_pin(arguments[0], f"message.{method}") if arguments else None
                if found:
                    pins.append(found)
        # err.message === 'text'
        elif (token.kind == "word" and text == "message" and index >= 1
              and tokens[index - 1].text == "." and index + 3 < len(tokens)
              and tokens[index + 1].text == "=" and tokens[index + 2].text == "="):
            after = index + 3 + (1 if tokens[index + 3].text == "=" else 0)
            if after < len(tokens):
                found = _literal_pin([tokens[after]], "message comparison")
                if found and found.kind == "string":
                    pins.append(found)
    unique: list[_Pin] = []
    for pin in pins:
        if not any(pin.kind == other.kind and pin.text == other.text for other in unique):
            unique.append(pin)
    return unique


def _normalize_words(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _regex_fragments(source: str) -> list[str]:
    """The literal runs inside a regular expression, with every operator removed."""
    fragments: list[str] = []
    current: list[str] = []

    def cut() -> None:
        text = re.sub(r"\s+", " ", "".join(current)).strip()
        if text:
            fragments.append(text)
        current.clear()

    i, n = 0, len(source)
    while i < n:
        char = source[i]
        if char == "\\" and i + 1 < n:
            following = source[i + 1]
            if following in "dDwWsSbBnrtfv0123456789":
                cut()
            else:
                current.append(following)
            i += 2
        elif char == "[":
            cut()
            i += 1
            while i < n and source[i] != "]":
                i += 2 if source[i] == "\\" else 1
            i += 1
        elif char == "(":
            cut()
            i += 1
            group = re.match(r"\?(?:<?[=!]|:|<[A-Za-z_$][\w$]*>)", source[i:])
            if group:
                i += group.end()
        elif char == "{":
            cut()
            end = source.find("}", i)
            i = n if end < 0 else end + 1
        elif char in ").|^$*+?}":
            cut()
            i += 1
        else:
            current.append(char)
            i += 1
    cut()
    return fragments


def _pin_fragments(pin: _Pin) -> list[str]:
    raw = _regex_fragments(pin.text) if pin.kind == "regex" else [
        re.sub(r"\s+", " ", pin.text).strip()
    ]
    fragments: list[str] = []
    for fragment in raw:
        # An error class name or code (TypeError, ERR_INVALID_URL, ECONNREFUSED) names a
        # kind of failure, not wording a repair might phrase differently.
        if re.fullmatch(r"[A-Za-z]*Error|[A-Z][A-Z0-9_]{3,}", fragment):
            continue
        normalized = _normalize_words(fragment)
        # Fewer than three letters (an address, a punctuation mark) says nothing about wording.
        if len(re.findall(r"[a-z]", normalized)) >= 3:
            fragments.append(normalized)
    return fragments


def ungrounded_message_pins(content: str, issue_text: str) -> list[str]:
    """Error-message matchers in ``content`` whose wording the issue never contains."""
    issue = _normalize_words(issue_text)
    found: list[str] = []
    for pin in _message_pins(content):
        if all(fragment in issue for fragment in _pin_fragments(pin)):
            continue
        shown = f"/{pin.text}/" if pin.kind == "regex" else repr(pin.text)
        found.append(shown if len(shown) <= 90 else shown[:87] + "...")
    return found


# --------------------------------------------------------------------------- #
# Relative-import resolution for generated Node tests
# --------------------------------------------------------------------------- #

_IMPORT_SKIP_DIRS = frozenset({
    ".git", ".pytest_cache", ".ruff_cache", "__pycache__", ".venv", "venv",
    "node_modules", "target", "build", "dist", "vendor", ".gradle", ".next",
})
_RESOLVE_EXTENSIONS = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".json")
# TypeScript's ESM convention: `./x.js` may name the source file `./x.ts`.
_JS_TO_TS_EXTENSIONS = {
    ".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",),
}
_STATIC_IMPORT = re.compile(
    r"""^[ \t]*(?:import|export)\b[^;'"`]*?\bfrom\s*(?P<q>['"])(?P<spec>[^'"\n]+)(?P=q)""",
    re.MULTILINE,
)
_SIDE_EFFECT_IMPORT = re.compile(
    r"""^[ \t]*import\s*(?P<q>['"])(?P<spec>[^'"\n]+)(?P=q)""", re.MULTILINE,
)
_CALL_IMPORT = re.compile(
    r"""\b(?:import|require)\s*\(\s*(?P<q>['"])(?P<spec>[^'"\n]+)(?P=q)\s*\)"""
)


def _blank_block_comments(source: str) -> str:
    """Replace /* ... */ with spaces of the same length so offsets stay valid."""
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), source, flags=re.DOTALL)


def relative_import_specifiers(source: str) -> list[str]:
    """Literal relative module specifiers in a Node test, in first-seen order.

    Deliberately conservative: static imports/exports must start a line, dynamic
    ``import()``/``require()`` need a string literal, and anything on a line that
    already contains ``//`` is skipped. A missed specifier only means the sandbox
    run reports it instead; a false positive would wrongly reject a valid test.
    """
    text = _blank_block_comments(source)
    found: list[tuple[int, str]] = []
    for pattern in (_STATIC_IMPORT, _SIDE_EFFECT_IMPORT, _CALL_IMPORT):
        for match in pattern.finditer(text):
            spec = match.group("spec")
            if not (spec in {".", ".."} or spec.startswith(("./", "../"))):
                continue
            line_start = text.rfind("\n", 0, match.start()) + 1
            if "//" in text[line_start:match.start()]:
                continue
            found.append((match.start("spec"), spec))
    ordered: list[str] = []
    for _, spec in sorted(found):
        if spec not in ordered:
            ordered.append(spec)
    return ordered


def _module_file_exists(base: Path) -> bool:
    if base.is_file() or base.is_dir():
        return True  # a directory is left to the sandbox: too many valid layouts
    for extension in _RESOLVE_EXTENSIONS:
        if Path(str(base) + extension).is_file():
            return True
    for replacement in _JS_TO_TS_EXTENSIONS.get(base.suffix, ()):
        if base.with_suffix(replacement).is_file():
            return True
    return False


def _suggest_import_paths(root: Path, base_dir: Path, tail: list[str], limit: int = 3) -> list[str]:
    """Repository files that match the tail of a missing import, as corrected specifiers."""
    if not tail:
        return []
    wanted_two = "/".join(tail[-2:])
    wanted_one = tail[-1]
    exact: list[Path] = []
    by_name: list[Path] = []
    seen = 0
    for directory, names, files in os.walk(root):
        names[:] = sorted(n for n in names if n not in _IMPORT_SKIP_DIRS and not n.startswith("."))
        for name in sorted(files):
            seen += 1
            if seen > 50000:
                break
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if relative == wanted_two or relative.endswith("/" + wanted_two):
                exact.append(path)
            elif name == wanted_one:
                by_name.append(path)
    suggestions: list[str] = []
    for path in (exact or by_name)[:limit]:
        specifier = os.path.relpath(path, base_dir).replace(os.sep, "/")
        suggestions.append(specifier if specifier.startswith(".") else "./" + specifier)
    return suggestions


def unresolved_relative_imports(content: str, test_path: str, root: Path) -> list[dict[str, object]]:
    """Relative imports in a generated test that do not exist from the test's location."""
    root = root.resolve()
    base_dir = Path(os.path.normpath(root / test_path)).parent
    problems: list[dict[str, object]] = []
    for spec in relative_import_specifiers(content):
        target = Path(os.path.normpath(base_dir / spec))
        inside = target == root or root in target.parents
        if inside and _module_file_exists(target):
            continue
        tail = [part for part in spec.split("/") if part not in {"", ".", ".."}]
        problems.append({
            "specifier": spec,
            "resolved": target.relative_to(root).as_posix() if inside else None,
            "suggestions": _suggest_import_paths(root, base_dir, tail),
        })
    return problems


def describe_unresolved_imports(problems: list[dict[str, object]], test_path: str) -> str:
    directory = Path(test_path).parent.as_posix()
    location = "the repository root" if directory in {"", "."} else f"'{directory}/'"
    lines = [
        f"The test will be saved as '{test_path}', so relative imports resolve from {location}. "
        "These relative imports do not point to any file in the repository:"
    ]
    for problem in problems[:3]:
        resolved = problem["resolved"]
        where = (f"resolves to '{resolved}', which does not exist" if resolved
                 else "resolves to a location outside the repository")
        line = f"- '{problem['specifier']}' {where}."
        suggestions = problem["suggestions"]
        if suggestions:
            line += " A file with that name exists; from this location the import is " + \
                    " or ".join(f"'{item}'" for item in suggestions) + "."
        else:
            line += " No similarly named file exists; do not import it."
        lines.append(line)
    lines.append(
        "An import path copied from an existing test is wrong when that test lives in a "
        "different directory: recompute every relative path from the directory above. "
        "Import only files that appear in the repository context, and keep the asserted "
        "behavior unchanged."
    )
    return "\n".join(lines)


@dataclass(frozen=True)
class RuntimeAdapter:
    id: str
    display_name: str
    application_languages: tuple[str, ...]
    test_runtime: str
    source_extensions: frozenset[str]
    context_extensions: frozenset[str]
    context_names: frozenset[str]
    test_suffix: str
    baseline_command: str
    bootstrap_command: str
    preflight_command: str
    verifier_guidance: str
    solver_guidance: str
    test_directory: str = ""
    tool_command: str = ""

    def test_path(self, issue_number: int, root: Path | None = None) -> str:
        identifier = str(issue_number) if issue_number else "manual"
        if self.test_runtime == "junit":
            return f"src/test/java/PatchProofIssue{identifier}Test.java"
        if self.id == "go":
            return f"{self.test_directory}/patchproof_issue_{identifier}_test.go".lstrip("/")
        if self.id == "rust":
            return f"tests/patchproof_issue_{identifier}.rs"
        prefix = "tests/" if self.id == "web-playwright" else ""
        filename_prefix = ""
        if self.id in {"node-typescript", "node-package"} and root is not None:
            # The Node adapters have no fixed test directory of their own (unlike
            # web-playwright). A generated test placed at the repo root
            # breaks any relative import (e.g. '../src/x.ts') a model wrote
            # to match a project whose own tests already live in tests/ --
            # so match that existing convention when one is evident on disk,
            # and otherwise keep the long-standing root placement unchanged.
            # node-package joined in rc.21: file-sharing-app's tests/ import a
            # helper as '../patchproof_runtime/...', the model copied that line
            # into a root-level test, and Node resolved it outside the repo.
            existing_tests_dir = root / "tests"
            if existing_tests_dir.is_dir() and any(
                existing_tests_dir.glob(f"*{self.test_suffix}")
            ):
                prefix = "tests/"
                # A leading dot keeps the file out of the project's own
                # shell-expanded baseline glob (e.g. `tsx --test
                # tests/*.test.ts`), which would otherwise sweep the hidden,
                # still-failing pre-fix regression into the *baseline* run
                # and corrupt "does the existing suite pass" -- while an
                # explicit path (what regression_command always uses) still
                # runs it directly regardless of the leading dot.
                filename_prefix = "."
        if self.test_suffix == ".py":
            return f"{prefix}{filename_prefix}test_patchproof_issue_{identifier}.py"
        return f"{prefix}{filename_prefix}test_patchproof_issue_{identifier}{self.test_suffix}"

    def regression_command(self, test_path: str) -> str:
        target = shlex.quote(test_path)
        name = Path(test_path).stem
        if self.id == "go":
            directory = shlex.quote("./" + str(Path(test_path).parent))
            identifier = name.removeprefix("patchproof_issue_").removesuffix("_test")
            pattern = shlex.quote(f"^TestPatchProofIssue{identifier}($|_)")
            return f"go test -json -count=1 {directory} -run {pattern}"
        if self.id == "rust":
            return f"cargo test --locked --offline --test {shlex.quote(name)} -- --nocapture"
        if self.test_runtime == "junit":
            if self.id == "java-maven":
                command = f"{self.tool_command} -B clean test -Dtest={name} -DfailIfNoTests=true"
            elif self.id == "java-gradle":
                command = f"{self.tool_command} --no-daemon --console=plain cleanTest test --rerun-tasks --tests '*{name}'"
            else:
                command = f"python /patchproof/java_check.py {shlex.quote(name)}"
            return f"python /patchproof/junit_check.py {self.id} {shlex.quote(name)} {shlex.quote(command)}"
        if self.test_runtime in {"pytest", "pytest-playwright"}:
            prefix = (
                "PLAYWRIGHT_BROWSERS_PATH=0 "
                if self.test_runtime == "pytest-playwright"
                else ""
            )
            return f"{prefix}python -m pytest -q {target}"
        if self.id == "node-typescript":
            return (
                f"python /patchproof/typescript_check.py {target} && "
                "/opt/patchproof/node/node_modules/.bin/tsx "
                f"--test --test-reporter=tap {target}"
            )
        return f"node --test --test-reporter=tap {target}"

    def full_command(self, test_path: str) -> str:
        # The isolated regression always runs explicitly, even if a project's
        # normal suite silently excludes new test files.
        return f"{self.baseline_command} && echo PATCHPROOF_REGRESSION_START && {self.regression_command(test_path)}"

    def is_context_file(self, path: Path) -> bool:
        return (
            path.name in self.context_names
            or path.suffix.lower() in self.context_extensions
        )

    def is_editable_source(self, path: Path) -> bool:
        return path.suffix.lower() in self.source_extensions

    def validate_generated_imports(self, content: str, test_path: str, root: Path) -> None:
        """Reject relative imports that cannot resolve before any sandbox run is spent."""
        if self.id not in {"node-typescript", "node-package"}:
            return
        problems = unresolved_relative_imports(content, test_path, root)
        if problems:
            raise ValueError(describe_unresolved_imports(problems, test_path))

    def validate_generated_test(self, content: str, filename: str) -> None:
        if not content.strip():
            raise ValueError("Generated regression test is empty.")
        if self.test_suffix == ".py":
            compile(content, filename, "exec")
        if self.id == "node-typescript":
            if Path(filename).suffix != ".ts":
                raise ValueError("The node-typescript adapter requires a .ts test file.")
            if "typescript_module" in content or "loadStandaloneTypeScript" in content:
                raise ValueError(
                    "Do not use the retired TypeScript loader; import application modules "
                    "normally in the tsx-executed test."
                )
            if re.search(r"""['"]/@/""", content):
                raise ValueError(
                    "Malformed path alias: found '/@/' with a leading slash before the @. "
                    "This project's alias is '@/' with no leading slash — for example "
                    "import { generateSessionKey } from '@/lib/crypto/aes';"
                )    
            if re.search(
                r"@ts-(?:ignore|nocheck|expect-error)\b|\bas\s+(?:unknown\s+as\s+)?any\b|"
                r"\bas\s+unknown\s+as\s+[A-Za-z_$]|:\s*any\b",
                content,
            ):
                raise ValueError(
                    "Do not bypass TypeScript API contracts with ts-ignore, ts-nocheck, "
                    "ts-expect-error, or any casts."
                )
            unused = _unused_initialized_bindings(content)
            if unused:
                raise ValueError(
                    "Generated TypeScript regression declares initialized bindings that are "
                    "never used: " + ", ".join(unused) + ". Every constructed helper, stream, "
                    "or transform must participate in the asserted behavior."
                )
            uses_web_streams = any(
                marker in content
                for marker in ("ReadableStream", "TransformStream", ".pipeThrough(")
            )
            if uses_web_streams:
                required = (
                    "file:///patchproof/web_streams.mjs",
                    "readableFromBytes(",
                    "collectBytes(",
                )
                missing = [marker for marker in required if marker not in content]
                if missing:
                    raise ValueError(
                        "Web Streams regressions must import and call readableFromBytes and "
                        "collectBytes from file:///patchproof/web_streams.mjs; missing: "
                        + ", ".join(missing)
                    )
                if _missing_async_success_guard(content):
                    raise ValueError(
                        "Stream output compared for equality must be collected inside "
                        "await assert.doesNotReject(async () => { ... }); then assert "
                        "the expected output. Put creation and consumption inside the "
                        "callback. An unrelated assert.rejects is not a success guard."
                    )
            missing_imports = _missing_node_test_imports(content)
            if missing_imports:
                raise ValueError(
                    "Generated TypeScript regression is missing required imports: `test` "
                    "and `assert` are not globals under tsx. Add exactly: "
                    + " ".join(missing_imports)
                    + " Declare each case as test('name', async () => { ... });. "
                    "This is a missing import, not a missing @types package."
                )
            # rc.24: the check above only asks whether node:test is imported at all.
            # Importing `test` does not make describe() or it() available.
            unbound = missing_node_test_imports(content)
            if unbound:
                raise ValueError(
                    "Generated TypeScript regression calls node:test functions it does "
                    "not import: they are not globals under tsx. Add exactly: "
                    + " ".join(unbound) + " This is a missing import, not a missing "
                    "@types package."
                )
        if self.id in {"node-package", "static-web"}:
            # rc.24: the import check used to run for node-typescript only. A generated
            # .mjs test that calls describe()/it()/test() without importing them is
            # certain to die with a ReferenceError, which node:test reports as a generic
            # failure that is never accepted as evidence.
            problems: list[str] = []
            unbound = missing_node_test_imports(content)
            if unbound:
                problems.append(
                    "Generated regression calls node:test or assert functions it does not "
                    "import: describe, it, test and assert are not globals in an ES module "
                    "run by node --test. Add exactly: " + " ".join(unbound)
                    + " Keep the test cases you already wrote; this is a missing import, "
                    "not evidence about the bug."
                )
            if self.id == "static-web" and imports_bare_jsdom(content):
                problems.append(
                    "jsdom is not installed in the repository, so importing it by name "
                    "fails with ERR_MODULE_NOT_FOUND. Load the preinstalled copy exactly "
                    "like this instead: " + _JSDOM_LOADER
                )
            if problems:
                raise ValueError(" ".join(problems))

    def validate_generated_pins(self, content: str, issue_text: str) -> None:
        """Reject tests that match error wording the issue never states (rc.24).

        A correct repair may word its refusal differently, so a test that pins invented
        text can reject every correct repair. Only wording found in the issue may be
        matched; everything else must be told apart by behaviour.
        """
        if self.test_runtime != "node-test":
            return
        try:
            pinned = ungrounded_message_pins(content, issue_text)
        except Exception:  # noqa: BLE001 - a heuristic must never abort a run; fail open
            return
        if pinned:
            raise ValueError(
                "The regression test matches error wording the issue never states: "
                + ", ".join(pinned[:3]) + ". A correct repair may word its refusal "
                "differently, so this test could reject a correct fix. Do not match on "
                "message text: no regex, string or `message:` matcher on an error. Assert "
                "that the operation is refused with `await assert.rejects(promise)` or "
                "`assert.throws(fn)` and no message matcher, and tell that refusal apart "
                "from the unfixed failure by the effect the issue forbids. Observe the "
                "effect directly, for example start http.createServer on 127.0.0.1 with "
                "an ephemeral port, count its 'connection' events and assert that the "
                "count is 0; or assert that the rejection is not the unfixed failure, "
                "such as a network error code (ECONNREFUSED, ENOTFOUND, ETIMEDOUT). Only "
                "a message the issue itself quotes may be matched."
            )

    def project_check_command(self) -> str | None:
        """Sandbox command that type-checks the whole unmodified project, or None (rc.24)."""
        if self.id != "node-typescript":
            return None
        return "python /patchproof/typescript_source_check.py --project"

    def source_check_command(self, changed_paths: list[str]) -> str | None:
        """Sandbox command that type-checks the project after a repair, or None (rc.24).

        The same whole-project check that has to pass on the unmodified repository, and
        only when the repair touched a TypeScript file.
        """
        if self.id != "node-typescript":
            return None
        if not any(Path(p).suffix.lower() in _TYPESCRIPT_SUFFIXES for p in changed_paths):
            return None
        return self.project_check_command()

    def validate_candidate_file(self, path: str, content: str) -> None:
        if Path(path).suffix.lower() == ".py":
            compile(content, path, "exec")

    def passed_count(self, output: str) -> int | None:
        output = output.rsplit("PATCHPROOF_REGRESSION_START", 1)[-1]
        if self.id == "go":
            events = _go_events(output)
            counts = [e for e in events if e.get("Action") == "pass" and e.get("Test")]
            return len(counts) if events else None
        if self.test_runtime == "junit":
            patterns = [r"PATCHPROOF_JUNIT_PASS=(\d+)"]
        elif self.id == "rust":
            patterns = [r"test result: ok\. (\d+) passed"]
        elif self.test_runtime == "node-test":
            patterns = [r"# pass\s+(\d+)"]
        else:
            patterns = [r"(\d+) passed"]
        for pattern in patterns:
            matches = re.findall(pattern, output)
            if matches:
                return int(matches[-1])
        return None

    def is_regression_failure(self, exit_code: int, output: str) -> bool:
        if self.id == "rust":
            return (exit_code == 101 and "test result: FAILED." in output
                    and "assertion" in output and "could not compile" not in output)
        if exit_code != 1:
            return False
        if self.test_runtime == "junit":
            return "PATCHPROOF_JUNIT_ASSERTION_FAILURE=1" in output
        if self.id == "go":
            return any(e.get("Action") == "fail" and e.get("Test", "").startswith("TestPatchProof")
                       for e in _go_events(output)) and "[build failed]" not in output
        if self.test_runtime == "node-test":
            return _node_assertion_failure(output)
        return ("AssertionError" in output and bool(re.search(r"\d+ failed", output))
                and not re.search(r"\d+ errors?", output))


# Message prefixes Node's assert module generates itself. Some assertion forms (for
# example assert.rejects with an object that contains an `instanceOf` key) are reported
# by node:test as code ERR_TEST_FAILURE instead of ERR_ASSERTION, so the message is the
# only reliable sign that an assertion, not an application crash, ended the test.
_ASSERTION_MESSAGE_PREFIXES = (
    "Expected values to be strictly deep-equal",
    "Expected values to be loosely deep-equal",
    "Expected values to be strictly equal",
    "Expected values to be loosely equal",
    "Expected \"actual\" to be strictly unequal to",
    "Expected \"actual\" not to be strictly deep-equal to",
    "Expected \"actual\" not to be loosely deep-equal to",
    "The expression evaluated to a falsy value",
    "Missing expected rejection",
    "Missing expected exception",
    "Got unwanted exception",
    "Got unwanted rejection",
    "The input did not match the regular expression",
    "The input was expected to not match the regular expression",
    "Input A expected to strictly deep-equal input B",
)


def _node_error_message(body: str, indent: str) -> str:
    """First line of the YAML `error:` field of one TAP block, or an empty string."""
    inline = re.search(r"^" + indent + r"  error: (?!\|)['\"]?(.*?)['\"]?\s*$", body, re.MULTILINE)
    if inline and inline.group(1):
        return inline.group(1)
    block = re.search(r"^" + indent + r"  error: \|[-+]?\s*\n" + indent + r"    ([^\n]*)", body, re.MULTILINE)
    return block.group(1).strip() if block else ""


def _node_assertion_failure(output: str) -> bool:
    """Conservatively recognize native TAP assertion diagnostics, not log text.

    This is an evidence check, not a security boundary against a malicious process
    capable of writing arbitrary TAP to stdout.

    rc.22: a test wrapped in describe() prints one extra `subtestsFailed` block for the
    parent suite, and `# fail` counts only the leaf. Suite blocks are therefore allowed
    in addition to exactly one leaf block per counted failure. A leaf block labelled
    ERR_TEST_FAILURE is accepted only when its message is one that Node's assert module
    generates.
    """
    failures = re.findall(r"^# fail (\d+)\s*$", output, re.MULTILINE)
    if len(failures) != 1 or int(failures[0]) == 0:
        return False
    if re.search(r"^# (?:cancelled|skipped|todo) [1-9]\d*\s*$", output, re.MULTILINE):
        return False
    blocks = re.findall(
        r"^([ ]*)not ok [^\n]*\n\1  ---\n(.*?)^\1  \.\.\.\s*$",
        output, re.MULTILINE | re.DOTALL,
    )
    assertions = 0
    leaves = 0
    for indent, body in blocks:
        def field(name: str) -> str | None:
            matches = re.findall(r"^" + indent + r"  " + name + r": ['\"]?([A-Za-z_]+)['\"]?\s*$",
                                 body, re.MULTILINE)
            return matches[0] if len(matches) == 1 else None
        code, failure_type = field("code"), field("failureType")
        if code == "ERR_TEST_FAILURE" and failure_type == "subtestsFailed":
            continue
        leaves += 1
        if failure_type != "testCodeFailure":
            return False
        if code == "ERR_ASSERTION":
            assertions += 1
        elif code == "ERR_TEST_FAILURE" and _node_error_message(body, indent).startswith(
                _ASSERTION_MESSAGE_PREFIXES):
            assertions += 1
        else:
            return False
    return leaves == int(failures[0]) and assertions > 0


def _go_events(output: str) -> list[dict]:
    events = []
    for line in output.splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict) and "Action" in item:
                events.append(item)
        except ValueError:
            pass
    return events


def _contains_playwright(root: Path) -> bool:
    candidates = [
        root / "tests" / "requirements.txt",
        root / "requirements.txt",
        root / "pyproject.toml",
    ]
    for path in candidates:
        if path.is_file():
            try:
                if "playwright" in path.read_text(encoding="utf-8").lower():
                    return True
            except (OSError, UnicodeDecodeError):
                pass
    for path in (root / "tests").glob("*.py") if (root / "tests").is_dir() else ():
        try:
            if "playwright" in path.read_text(encoding="utf-8").lower():
                return True
        except (OSError, UnicodeDecodeError):
            pass
    return False


def _python_bootstrap(root: Path) -> str:
    if (root / "requirements.txt").is_file():
        return "python -m pip install --disable-pip-version-check -r requirements.txt"
    if (root / "pyproject.toml").is_file():
        return "python -m pip install --disable-pip-version-check ."
    return "true"


def _node_baseline(root: Path) -> tuple[str, str]:
    package_path = root / "package.json"
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeDetectionError(f"Invalid package.json: {error}") from error
    scripts = package.get("scripts") if isinstance(package, dict) else None
    has_test_script = isinstance(scripts, dict) and isinstance(scripts.get("test"), str)
    baseline = "CI=1 npm test" if has_test_script else "node --test"
    if (root / "npm-shrinkwrap.json").is_file() or (
        root / "package-lock.json"
    ).is_file():
        bootstrap = "npm ci --ignore-scripts --no-audit --no-fund"
    else:
        bootstrap = "npm install --ignore-scripts --no-audit --no-fund"
    return baseline, bootstrap


def _strip_jsonc(text: str) -> str:
    """Remove comments and trailing commas from tsconfig-style JSON, leaving strings alone.

    Glob patterns such as "@/*" and "src/**/*" contain comment-looking sequences, so a
    plain regular expression would delete real content.
    """
    out: list[str] = []
    i, n, in_string = 0, len(text), False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        else:
            out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _alias_guidance(root: Path) -> str:
    """Describe the import aliases this repository's tsconfig really defines (rc.22).

    Earlier releases told the model the project has an '@/' alias and gave an example
    from one particular repository. On a repository without that alias, or whose alias
    points at the repository root rather than src/, the model copied the pattern and the
    import failed the type-check.
    """
    try:
        text = _strip_jsonc((root / "tsconfig.json").read_text(encoding="utf-8"))
        paths = (json.loads(text).get("compilerOptions") or {}).get("paths") or {}
    except (OSError, ValueError, AttributeError):
        return ("Use relative import paths from the test file's own directory, exactly as "
                "the application's modules import each other. ")
    rules = []
    for pattern, targets in paths.items():
        if isinstance(targets, list) and targets and isinstance(targets[0], str):
            rules.append(f"'{pattern}' maps to '{targets[0]}'")
    if not rules:
        return ("This project defines no path aliases in tsconfig.json: use relative "
                "import paths, and never write imports that start with '@/'. ")
    return ("This project's tsconfig.json defines these path aliases: " + "; ".join(rules[:4])
            + ". Resolve an alias exactly as written there (for example, when '@/*' maps to "
            "'./*', a file at src/server/x.ts is imported as '@/src/server/x', not "
            "'@/server/x'), or use relative paths. ")


def _compiled_adapter(root: Path, runtime: str, test_directory: str) -> RuntimeAdapter:
    common = dict(
        id=runtime, solver_guidance="Repair existing application source only; do not edit tests, build scripts, manifests, or lockfiles.",
        test_directory=test_directory,
    )
    if runtime == "go":
        directory = root / test_directory
        if not any(p for p in directory.glob("*.go") if not p.name.endswith("_test.go")):
            raise RuntimeDetectionError("Go needs a package with source files. Set test_directory in patchproof.json (for example internal/wifi).")
        return RuntimeAdapter(**common, display_name="Go modules", application_languages=("Go",),
            test_runtime="go-test", source_extensions=frozenset({".go"}),
            context_extensions=frozenset({".go"}), context_names=frozenset({"go.mod", "go.sum"}),
            test_suffix="_test.go", baseline_command="go test -json -count=1 ./...",
            bootstrap_command="go mod download", preflight_command="go version",
            verifier_guidance=f"Write a native Go testing test in package directory {test_directory or '.'}. Match that package declaration. Name every test TestPatchProofIssue<identifier> or TestPatchProofIssue<identifier>_<suffix>, where identifier is the issue identifier in the required filename. Use t.Errorf or t.Fatalf on observable wrong results; no network, skips, source edits, or build tags.")
    if runtime == "rust":
        import tomllib
        manifest = tomllib.loads((root / "Cargo.toml").read_text())
        if "package" not in manifest or manifest.get("package", {}).get("autotests") is False:
            raise RuntimeDetectionError("Rust requires a root Cargo package with automatic integration tests enabled; virtual workspaces are not yet supported.")
        return RuntimeAdapter(**common, display_name="Rust / Cargo", application_languages=("Rust",),
            test_runtime="cargo-test", source_extensions=frozenset({".rs"}),
            context_extensions=frozenset({".rs"}), context_names=frozenset({"Cargo.toml", "Cargo.lock"}),
            test_suffix=".rs", baseline_command="cargo test --locked --offline",
            bootstrap_command="cargo fetch --locked" if (root / "Cargo.lock").exists() else "cargo generate-lockfile && cargo fetch --locked",
            preflight_command="rustc --version && cargo --version",
            verifier_guidance="Write a Rust integration test using #[test] and assert_eq!/assert!. Import the public library crate; for a binary-only crate use std::process::Command and env!(\"CARGO_BIN_EXE_<binary-name>\"). No include! of copied source, ignored tests, source edits, network, or custom harness.")
    tool = ""
    if runtime == "java-maven":
        tool = "sh ./mvnw" if (root / "mvnw").is_file() else "mvn"
        baseline, bootstrap = f"{tool} -B clean test", f"{tool} -B -DskipTests test-compile"
    elif runtime == "java-gradle":
        if not (root / "gradlew").is_file():
            raise RuntimeDetectionError("Gradle requires the committed gradlew, wrapper JAR, and wrapper properties; a system Gradle may be incompatible.")
        for name in ("gradle/wrapper/gradle-wrapper.jar", "gradle/wrapper/gradle-wrapper.properties"):
            if not (root / name).is_file():
                raise RuntimeDetectionError(f"Missing Gradle wrapper file: {name}")
        tool = "sh ./gradlew"
        baseline = f"{tool} --no-daemon --console=plain cleanTest test --rerun-tasks"
        bootstrap = f"{tool} --no-daemon testClasses"
    else:
        if not (root / "src/main/java").is_dir():
            raise RuntimeDetectionError("Plain Java requires src/main/java; use Maven or Gradle for custom layouts or dependencies.")
        baseline, bootstrap = "python /patchproof/java_check.py", "true"
    return RuntimeAdapter(**common, display_name={"java-maven": "Java / Maven", "java-gradle": "Java / Gradle", "java-junit": "Java / JUnit standalone"}[runtime],
        application_languages=("Java",), test_runtime="junit", source_extensions=frozenset({".java"}),
        context_extensions=frozenset({".java", ".gradle", ".kts"}),
        context_names=frozenset({"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}),
        test_suffix=".java", baseline_command=baseline, bootstrap_command=bootstrap,
        preflight_command="java -version && javac -version" + (f" && {tool} --version" if tool else ""),
        tool_command=tool,
        verifier_guidance="Write one JUnit test class whose class name exactly matches the required filename, with no package declaration. Import application classes by fully qualified name and test public behavior with assertions. For Maven/Gradle reuse the existing JUnit version; do not add dependencies. Plain Java supplies JUnit Jupiter. Never skip tests or edit the build configuration.")


def detect_runtime(root: Path) -> RuntimeAdapter:
    root = root.resolve()
    config_path = root / "patchproof.json"
    try:
        config = json.loads(config_path.read_text()) if config_path.is_file() else {}
    except (OSError, ValueError) as error:
        raise RuntimeDetectionError(f"Invalid patchproof.json: {error}") from error
    if not isinstance(config, dict) or set(config) - {"runtime", "test_directory"}:
        raise RuntimeDetectionError("patchproof.json accepts only runtime and test_directory.")
    requested = config.get("runtime")
    if requested is not None and not isinstance(requested, str):
        raise RuntimeDetectionError("runtime must be a string adapter ID.")
    directory = config.get("test_directory", "")
    if not isinstance(directory, str) or Path(directory).is_absolute() or ".." in Path(directory).parts or not (root / directory).resolve().is_relative_to(root):
        raise RuntimeDetectionError("test_directory must stay inside the repository.")
    markers = {"java-maven": "pom.xml", "java-gradle": "build.gradle", "go": "go.mod", "rust": "Cargo.toml", "node-package": "package.json"}
    found = [key for key, name in markers.items() if (root / name).is_file()]
    if (root / "build.gradle.kts").is_file() and "java-gradle" not in found:
        found.append("java-gradle")
    if requested is None and len(found) > 1:
        raise RuntimeDetectionError("Multiple runtime manifests found; select runtime in patchproof.json: " + ", ".join(found))
    selected = requested or (found[0] if found else None)
    if requested is None and selected == "node-package" and (root / "tsconfig.json").is_file():
        selected = "node-typescript"
    compiled = {"java-maven", "java-gradle", "java-junit", "go", "rust"}
    if selected in compiled:
        if selected != "java-junit" and selected not in found:
            raise RuntimeDetectionError(f"Missing manifest for selected runtime {selected}.")
        return _compiled_adapter(root, selected, directory)
    if selected is None and any((root / "src/main/java").rglob("*.java")):
        return _compiled_adapter(root, "java-junit", directory)
    adapter = _detect_script_runtime(root, requested)
    if requested is not None and requested != adapter.id:
        raise RuntimeDetectionError(f"Requested runtime {requested!r} does not match detected {adapter.id!r}.")
    return adapter


def _detect_script_runtime(root: Path, requested: str | None = None) -> RuntimeAdapter:
    root = root.resolve()
    has_html = any(
        path.is_file() for path in (root / "index.html", root / "src" / "index.html")
    )

    if requested in (None, "web-playwright") and has_html and _contains_playwright(root):
        bootstrap = _python_bootstrap(root)
        if (root / "tests/requirements.txt").is_file():
            bootstrap += " && python -m pip install -r tests/requirements.txt"
        return RuntimeAdapter(
            id="web-playwright",
            display_name="Web application + Python Playwright",
            application_languages=("HTML", "CSS", "JavaScript"),
            test_runtime="pytest-playwright",
            source_extensions=frozenset({".html", ".css", ".js", ".mjs", ".cjs"}),
            context_extensions=frozenset(
                {".html", ".css", ".js", ".mjs", ".cjs", ".py"}
            ),
            context_names=frozenset({"requirements.txt", "pyproject.toml"}),
            test_suffix=".py",
            baseline_command="PLAYWRIGHT_BROWSERS_PATH=0 python -m pytest -q tests",
            bootstrap_command=(
                f"{bootstrap} && "
                "PLAYWRIGHT_BROWSERS_PATH=0 python -m playwright install chromium"
            ),
            preflight_command=(
                "python -c \"import pytest, playwright; print('Playwright ready')\""
            ),
            verifier_guidance=(
                "Return a pytest Playwright regression that exercises observable browser "
                "behavior. Reuse fixtures from tests/conftest.py when present. Keep it "
                "offline and deterministic; do not change application source."
            ),
            solver_guidance=(
                "Repair only HTML, CSS, or JavaScript application source. Preserve the "
                "existing UI and unrelated behavior."
            ),
        )

    if requested in (None, "node-typescript") and (root / "package.json").is_file() and (root / "tsconfig.json").is_file():
        baseline, bootstrap = _node_baseline(root)
        return RuntimeAdapter(
            id="node-typescript",
            display_name="Node.js / TypeScript (tsx)",
            application_languages=("JavaScript", "TypeScript"),
            test_runtime="node-test",
            source_extensions=frozenset({".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}),
            context_extensions=frozenset(
                {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".json"}
            ),
            context_names=frozenset({"package.json", "tsconfig.json"}),
            test_suffix=".test.ts",
            baseline_command=baseline,
            bootstrap_command=bootstrap,
            preflight_command=(
                "node --version && npm --version && "
                "/opt/patchproof/node/node_modules/.bin/tsx --version && "
                "test -x ./node_modules/.bin/tsc && ./node_modules/.bin/tsc --version"
            ),
            verifier_guidance=(
                "Return an offline deterministic test using node:test and node:assert, "
                "executed with tsx (real TypeScript, not a custom loader). `test` and "
                "`assert` are NOT globals: the file MUST include exactly these two imports, "
                "written this way: import test from 'node:test'; "
                "import assert from 'node:assert/strict'; "
                "and every case is declared as test('descriptive name', async () => { ... }); "
                "never call test() or assert without importing them. Import application "
                "modules the normal way, exactly as the application itself does. " +
                _alias_guidance(root) +
                "When the intended behavior is that an operation must be refused, assert it with "
                "await assert.rejects(promise, /expected message/) or assert.throws(fn, /expected message/); "
                "never pass an object containing instanceOf. "
                "Never invent a helper import or reimplement application logic; call the real "
                "exported functions directly. Respect every declared TypeScript signature. If "
                "a factory returns a wrapper object, destructure or select the documented field "
                "whose type the next API requires; never pass the wrapper itself and never hide "
                "a mismatch with any, ts-ignore, or a double cast. The engine type-checks the "
                "test and its imported application modules before executing it. "
                "When a fixture or expected value needs an apostrophe, backslash, or quote "
                "character, pick the quote style that avoids escaping it: write "
                "\"Pa'ss\" (double-quoted) rather than 'Pa\\'ss' (single-quoted) for a value "
                "containing an apostrophe. When escaping is unavoidable, do it correctly: a "
                "literal backslash in the runtime value is the two-character source sequence "
                "\\\\, and a literal double quote inside a double-quoted string is \\\". Every "
                "backslash or quote you intend to appear literally must be escaped for the "
                "quote style you chose — an unescaped character matching the string's own "
                "delimiter ends it early and breaks parsing. Never sidestep a needed "
                "apostrophe, quote, or backslash by rewording or dropping it from the "
                "fixture; escape it correctly instead. "
                "For any Web Streams test, you MUST import "
                "{ readableFromBytes, collectBytes } from "
                "'file:///patchproof/web_streams.mjs' and use those helpers instead of "
                "constructing or collecting streams yourself. Pipe application transforms "
                "between them before collecting, for example: const output = await collectBytes("
                "readableFromBytes(input, 512).pipeThrough(await makeFirstTransform())"
                ".pipeThrough(await makeSecondTransform())); collectBytes returns Uint8Array, "
                "not a stream, so never call pipeThrough on its result. Every transform you "
                "construct must actually appear in the pipeline. For an encrypt/decrypt "
                "round trip, chain BOTH transforms before collectBytes; never collect the "
                "encrypted intermediate and compare ciphertext with plaintext. "
                "Use a small explicit application chunk size and a small byte fixture; do not "
                "allocate multi-megabyte input merely to exercise a final partial chunk. "
                "Assert the intended post-fix behavior, never the current defect. If an operation "
                "should succeed but currently rejects or throws, use assert.doesNotReject(...)—"
                "not assert.rejects(...)—so the unfixed revision produces a recognized assertion "
                "failure; then assert its expected result. Put the ENTIRE operation under test "
                "inside that one awaited callback — every awaited call, including session/key "
                "generation and both directions of a round trip, not only the stream transforms. "
                "Do not split the round trip into an unguarded setup/forward step and a "
                "separately-guarded inverse step; nothing the test awaits may sit outside the "
                "callback. Only plain imports and constant/fixture declarations belong outside "
                "it. Do not assert anything about an intermediate encoded value, not even its "
                "byteLength — only the final recovered value is compared to the original input. "
                "For example: "
                "let recovered: Uint8Array | undefined; "
                "await assert.doesNotReject(async () => { "
                "const { key } = await generateSessionKey(); "
                "const forward = await makeForwardTransform(key); "
                "const encoded = await collectBytes(readableFromBytes(input, n).pipeThrough(forward)); "
                "const inverse = await makeInverseTransform(key); "
                "recovered = await collectBytes(readableFromBytes(encoded, n).pipeThrough(inverse)); "
                "}); "
                "assert.deepStrictEqual(recovered, original). A later equality assertion cannot "
                "catch an earlier rejection. Use assert.rejects only when "
                "rejection is the required correct behavior and the bug is that invalid input is "
                "accepted. An uncaught exception is not accepted as reproduction evidence even "
                "when it demonstrates the real defect."
            ),
            solver_guidance=(
                "Repair existing JavaScript or TypeScript application files only. "
                "Keep module format and public APIs compatible. For binary frames or protocol "
                "changes, privately verify that every allocated buffer is at least as large as "
                "its highest write offset plus payload length, that producer and consumer use "
                "identical field offsets and frame lengths, and that full-chunk and final-flush "
                "paths emit the same format. Return only the reviewed minimal edit."
            ),
        )

    if requested in (None, "node-package") and (root / "package.json").is_file():
        baseline, bootstrap = _node_baseline(root)
        return RuntimeAdapter(
            id="node-package",
            display_name="Node.js / JavaScript",
            application_languages=("JavaScript",),
            test_runtime="node-test",
            source_extensions=frozenset({".js", ".mjs", ".cjs", ".jsx"}),
            context_extensions=frozenset(
                {".js", ".mjs", ".cjs", ".jsx", ".json"}
            ),
            context_names=frozenset({"package.json"}),
            test_suffix=".test.mjs",
            baseline_command=baseline,
            bootstrap_command=bootstrap,
            preflight_command="node --version && npm --version",
            verifier_guidance=(
                "Return an offline deterministic test using node:test and node:assert. "
                "The test may import project modules but must not modify the repository. "
                "Relative import paths resolve from the directory that will contain the "
                "required filename, which can differ from where the repository's existing "
                "tests live: recompute every relative path from that directory and import "
                "only files that appear in the repository context."
            ),
            solver_guidance=(
                "Repair existing JavaScript application files only. "
                "Keep module format and public APIs compatible."
            ),
        )

    if requested in (None, "static-web") and has_html:
        entry = "index.html" if (root / "index.html").is_file() else "src/index.html"
        return RuntimeAdapter(
            id="static-web",
            display_name="Static HTML / CSS / JavaScript",
            application_languages=("HTML", "CSS", "JavaScript"),
            test_runtime="node-test",
            source_extensions=frozenset({".html", ".css", ".js", ".mjs", ".cjs"}),
            context_extensions=frozenset({".html", ".css", ".js", ".mjs", ".cjs"}),
            context_names=frozenset(),
            test_suffix=".test.mjs",
            baseline_command=f"node /patchproof/static_web_check.mjs {entry}",
            bootstrap_command="true",
            preflight_command="node --version && node -e \"require('/opt/patchproof/node/node_modules/jsdom')\"",
            verifier_guidance=(
                "Return one offline node:test regression using node:assert/strict for this static web app. "
                "The assertion must exercise observable behavior in actual repository code and must fail "
                "on the supplied unfixed revision. Do not merely inspect source text or copy/reimplement "
                "the application algorithm inside the test. Use "
                "the real DOM via preinstalled jsdom: import {createRequire} from 'node:module'; "
                "const {JSDOM} = createRequire('/opt/patchproof/node/package.json')('jsdom'); "
                "Load the actual HTML from disk and exercise its functions/events. Set "
                "url: 'https://patchproof.invalid/' to enable localStorage without an opaque origin; "
                "this URL does not require a network request. Use runScripts: 'outside-only' "
                "and window.eval for relevant actual inline scripts. Do not enable external resources, "
                "network access, install packages, catch/swallow assertion failures, call process.exit, "
                "or modify the test/application files. Select UI modes through actual DOM events; "
                "top-level let/const bindings are not window properties. Stub only unavailable external "
                "APIs, never the application behavior under test. "
                "jsdom is not a real browser: layout/canvas/visual behavior requires Playwright."
            ),
            solver_guidance=(
                "Repair existing HTML, CSS, or inline/external JavaScript only. Preserve "
                "the single-page app structure and unrelated UI behavior."
            ),
        )

    python_markers = (
        root / "pyproject.toml",
        root / "requirements.txt",
        root / "setup.py",
        root / "pytest.ini",
    )
    has_application_python = any(
        path.is_file()
        and "tests" not in {part.lower() for part in path.relative_to(root).parts}
        and not path.name.startswith("test_")
        and path.name not in {"proof.py", "runtimes.py", "apply_fix.py"}
        and "patchproof_runtime" not in path.relative_to(root).parts
        for path in root.rglob("*.py")
    )
    if requested in (None, "python-pytest") and (any(path.is_file() for path in python_markers) or has_application_python):
        return RuntimeAdapter(
            id="python-pytest",
            display_name="Python + pytest",
            application_languages=("Python",),
            test_runtime="pytest",
            source_extensions=frozenset({".py"}),
            context_extensions=frozenset({".py", ".toml"}),
            context_names=frozenset(
                {"requirements.txt", "pyproject.toml", "pytest.ini"}
            ),
            test_suffix=".py",
            baseline_command="python -m pytest -q --ignore=regression",
            bootstrap_command=_python_bootstrap(root),
            preflight_command="python -m pytest --version",
            verifier_guidance=(
                "Return one deterministic pytest regression. It must fail through a "
                "normal assertion on the reported behavior, not collection or import errors."
            ),
            solver_guidance=(
                "Repair existing Python application source only and preserve public APIs."
            ),
        )

    raise RuntimeDetectionError(
        "Unsupported repository. Supported: Python, Node, static web, Python Playwright, "
        "Java/JUnit, Maven, Gradle, Go modules, and Rust/Cargo."
    )
