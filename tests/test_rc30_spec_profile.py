"""rc.30: the specification-compiled verifier profile (spec_profile.py and its place in the engine)."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import proof
import spec_profile as sp
from tests import support_pipeline as pipeline

BS = "\\"  # one backslash; every backslash in these fixtures is spelled out, never typed inside a literal
WIFI_PAYLOAD = "WIFI:T:WPA;S:Cafe" + BS + ";Guest;P:pass" + BS + ":word;;"
WIFI_LINE = "payload " + WIFI_PAYLOAD + " for SSID Cafe;Guest and password pass:word"

ISSUE = "\n".join([
    "formatBytes 512 512 B",
    "formatBytes 1536 1.5 KB",
    "formatSpeed 1536 1.5 KB/s",
    "ratio 4 0 must throw an error",
    "Calling ratio with 1 and 4 returns 0.25.",
    "WiFi example: " + WIFI_LINE,
])

SOURCE = """export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  return "v.toFixed(1) {units[i]}";
}
export const formatSpeed = (n: number): string => formatBytes(n) + "/s";
export function ratio(a: number, b: number): number { if (b === 0) throw new Error("zero"); return a / b; }
export function buildContent(input: { type: string; ssid: string; password: string }): string {
  return `WIFI:T:WPA;S:${input.ssid};P:${input.password};;`;
}
export default function fallback(): string { return "x"; }
export class Widget {}
"""
MODULES = {"lib/utils/format.ts": SOURCE}


def example(ident, export, args, **kw):
    item = {"id": ident, "export": export, "args": args, **kw}
    return item


def good_spec():
    return {"supported": True, "module": "lib/utils/format.ts", "examples": [
        example("e1", "formatBytes", [512], returns="512 B", evidence="formatBytes 512 512 B"),
        example("e2", "formatBytes", [1536], returns="1.5 KB", evidence="formatBytes 1536 1.5 KB"),
        example("e3", "formatSpeed", [1536], returns="1.5 KB/s", evidence="formatSpeed 1536 1.5 KB/s"),
    ]}


def validate(raw, issue=ISSUE, literals=frozenset()):
    return sp.validate_spec(raw, issue_text=issue, modules=MODULES, source_literals=set(literals))


class ParseTests(unittest.TestCase):
    def wrap(self, body):
        return f"{sp.SPEC_BEGIN}\n{body}\n{sp.SPEC_END}"

    def test_accepts_one_marked_object(self):
        self.assertEqual(sp.parse_spec_response(self.wrap('{"supported": false, "reason": "x"}'))["supported"], False)

    def test_rejects_structure_problems(self):
        cases = {
            "no markers": '{"a": 1}',
            "text outside": "hello " + self.wrap("{}"),
            "fence": self.wrap("```json\n{}\n```"),
            "duplicate key": self.wrap('{"a": 1, "a": 2}'),
            "constant": self.wrap('{"a": NaN}'),
            "array": self.wrap("[1]"),
            "reversed": f"{sp.SPEC_END}\n{{}}\n{sp.SPEC_BEGIN}",
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(sp.SpecFormatError):
                sp.parse_spec_response(text)

    def test_an_unclosed_object_is_closed_and_the_repair_is_reported(self):
        # The live file-sharing-app-1 shape: examples closed, then a stray quote before the END marker.
        notes = []
        value = sp.parse_spec_response(self.wrap('{"supported": true, "examples": [{"id": "e1"}], "'), notes)
        self.assertEqual(value, {"supported": True, "examples": [{"id": "e1"}]})
        self.assertEqual(len(notes), 1)
        self.assertIn("dangling quote", notes[0])
        self.assertIn("closed 1 open bracket", notes[0])

    def test_a_missing_close_bracket_alone_is_closed_without_changing_values(self):
        notes = []
        value = sp.parse_spec_response(self.wrap('{"examples": [{"id": "e1", "returns": "1.5 KB"}],'), notes)
        self.assertEqual(value["examples"][0]["returns"], "1.5 KB")
        self.assertIn("trailing comma", notes[0])

    def test_a_valid_block_is_never_reported_as_repaired(self):
        notes = []
        sp.parse_spec_response(self.wrap('{"supported": false, "reason": "x"}'), notes)
        self.assertEqual(notes, [])

    def test_a_value_cut_off_in_the_middle_is_not_repaired(self):
        for body in ('{"examples": [{"returns": "1.5 K', '{"examples": [{"id": "e1"}, {"id":', '{"a": 1}}', '{"a": [1}]'):
            with self.subTest(body), self.assertRaises(sp.SpecFormatError):
                sp.parse_spec_response(self.wrap(body), [])

    def test_an_unclosed_block_is_explained_as_unclosed_not_as_a_backslash_problem(self):
        with self.assertRaises(sp.SpecFormatError) as caught:
            sp.parse_spec_response(self.wrap('{"returns": "abc'))
        message = str(caught.exception)
        self.assertIn("not closed", message)
        self.assertNotIn("two backslashes", message)
        self.assertNotIn("at at", message)

    def test_bad_backslash_escape_gets_the_json_hint(self):
        with self.assertRaisesRegex(sp.SpecFormatError, "two backslashes"):
            sp.parse_spec_response(self.wrap('{"returns": "a' + BS + ';b"}'))


class ExportScanTests(unittest.TestCase):
    def scan(self, source):
        return sp.scan_exports(source)

    def test_common_forms(self):
        scan = self.scan(SOURCE)
        self.assertEqual(scan.names, {"formatBytes": "function", "formatSpeed": "variable", "ratio": "function",
                                      "buildContent": "function", "default": "default", "Widget": "class"})
        self.assertFalse(scan.opaque)

    def test_async_generator_lists_and_aliases(self):
        scan = self.scan("export async function a() {}\nexport function* g() {}\n"
                         "const x = 1; const y = 2;\nexport { x, y as z };\nexport type { T } from './t';\n"
                         "export { type U, w } from './w';\nexport interface I {}\nexport type K = string;\n"
                         "export enum E { A }\nexport declare function d(): void;")
        self.assertEqual(scan.names, {"a": "function", "g": "function", "x": "binding", "z": "binding",
                                      "w": "binding", "E": "enum", "d": "function"})

    def test_incomplete_scans_are_marked_opaque(self):
        for source in ("export * from './a';", "export const { a, b } = obj;", "module.exports = { a };",
                       "exports.a = 1;", "export = foo;"):
            with self.subTest(source):
                self.assertTrue(self.scan(source).opaque)

    def test_nested_and_quoted_exports_are_ignored(self):
        scan = self.scan('const s = "export function fake() {}";\nfunction f() { return { export: 1 }; }\n'
                         "// export function commented() {}\nexport function real() {}")
        self.assertEqual(set(scan.names), {"real"})

    def test_string_literals(self):
        self.assertEqual(sp.string_literals("const a = 'wifi'; const b = \"WPA\"; const c = `x`; const d = `${y}`;"),
                         {"wifi", "WPA", "x"})


class ValidationTests(unittest.TestCase):
    def test_valid_specification(self):
        result = validate(good_spec())
        self.assertTrue(result.ok, result.errors)
        self.assertEqual([e.id for e in result.spec.examples], ["e1", "e2", "e3"])
        self.assertIn("formatBytes 1536 1.5 KB", result.spec.examples[1].span)

    def test_unsupported_answer(self):
        result = validate({"supported": False, "reason": "The issue describes network behavior only."})
        self.assertEqual(result.unsupported, "The issue describes network behavior only.")
        self.assertFalse(result.ok)
        self.assertTrue(validate({"supported": False}).errors)

    def test_module_and_export_must_exist(self):
        raw = good_spec()
        raw["module"] = "lib/other.ts"
        self.assertIn("must be one of the editable TypeScript source files", validate(raw).errors[0])
        raw = good_spec()
        raw["examples"][0]["export"] = "formatByte"
        message = validate(raw).errors[0]
        self.assertIn("does not export 'formatByte'", message)
        self.assertIn("formatBytes", message)

    def test_a_class_cannot_be_called(self):
        raw = good_spec()
        raw["examples"][0]["export"] = "Widget"
        self.assertIn("is a class", validate(raw).errors[0])

    def test_opaque_module_defers_the_export_check_to_the_compiler(self):
        modules = {"lib/x.ts": "export * from './y';"}
        raw = {"supported": True, "module": "lib/x.ts", "examples": [
            example("e1", "anything", [1], returns=1, evidence="anything 1 returns 1")]}
        result = sp.validate_spec(raw, issue_text="anything 1 returns 1", modules=modules, source_literals=set())
        self.assertTrue(result.ok, result.errors)

    def test_evidence_must_be_in_the_issue_with_a_pointer_to_the_nearest_line(self):
        raw = good_spec()
        raw["examples"][1]["evidence"] = "formatBytes 1536 yields 1.5 KB"
        message = validate(raw).errors[0]
        self.assertIn("does not appear in the issue", message)
        self.assertIn('"formatBytes 1536 1.5 KB"', message)

    def test_evidence_matching_ignores_only_whitespace(self):
        raw = good_spec()
        raw["examples"][1]["evidence"] = "formatBytes   1536\n 1.5   KB"
        self.assertTrue(validate(raw).ok)

    def test_an_invented_expected_value_is_refused(self):
        raw = good_spec()
        raw["examples"][1]["returns"] = "1.50 KB"
        message = validate(raw).errors[0]
        self.assertIn('expected string "1.50 KB" is not in the quoted evidence', message)

    def test_a_value_quoted_from_a_different_line_is_refused(self):
        raw = good_spec()
        raw["examples"][1]["returns"] = "1.5 KB/s"  # real text, but not in this example's evidence
        self.assertIn("is not in the quoted evidence", validate(raw).errors[0])

    def test_argument_strings_need_the_issue_or_the_source(self):
        raw = {"supported": True, "module": "lib/utils/format.ts", "examples": [example(
            "e1", "buildContent", [{"type": "wifi", "ssid": "Cafe;Guest", "password": "pass:word"}],
            returns=WIFI_PAYLOAD, evidence=WIFI_LINE)]}
        self.assertIn('argument string "wifi"', validate(raw).errors[0])
        self.assertTrue(validate(raw, literals={"wifi"}).ok, validate(raw, literals={"wifi"}).errors)

    def test_backslash_values_must_match_the_issue_exactly(self):
        # What the model must write: the issue has one backslash, JSON text spells it with two.
        def spec_json(returns):
            raw = {"supported": True, "module": "lib/utils/format.ts", "examples": [example(
                "e1", "buildContent", [{"type": "wifi", "ssid": "Cafe;Guest", "password": "pass:word"}],
                returns=returns, evidence=WIFI_LINE)]}
            return json.dumps(raw)
        correct = spec_json(WIFI_PAYLOAD)
        self.assertIn(BS + BS + ";Guest", correct)  # two backslashes on the wire
        self.assertTrue(validate(json.loads(correct), literals={"wifi"}).ok)
        # One backslash too many after decoding, a lost backslash, and a doubled-up payload all fail.
        for name, wrong in (("extra backslash", WIFI_PAYLOAD.replace(BS + ";", BS + BS + ";", 1)),
                            ("lost backslash", WIFI_PAYLOAD.replace(BS + ";", ";", 1)),
                            ("unescaped colon", WIFI_PAYLOAD.replace(BS + ":", ":", 1))):
            with self.subTest(name):
                result = validate(json.loads(spec_json(wrong)), literals={"wifi"})
                self.assertFalse(result.ok)
                self.assertIn("is not in the quoted evidence", result.errors[0])

    def test_numbers_are_matched_by_value(self):
        raw = {"supported": True, "module": "lib/utils/format.ts", "examples": [
            example("e1", "ratio", [1, 4], returns=0.25, evidence="Calling ratio with 1 and 4 returns 0.25."),
            example("e2", "ratio", [1.0, 4.0], returns=0.250, evidence="Calling ratio with 1 and 4 returns 0.25."),
        ]}
        self.assertTrue(validate(raw).ok, validate(raw).errors)
        raw["examples"][0]["returns"] = 0.5
        self.assertIn("expected number 0.5", validate(raw).errors[0])

    def test_throws_needs_failure_language_in_the_evidence(self):
        raw = {"supported": True, "module": "lib/utils/format.ts", "examples": [
            example("e1", "ratio", [4, 0], throws=True, evidence="ratio 4 0 must throw an error")]}
        self.assertTrue(validate(raw).ok)
        raw["examples"][0]["evidence"] = "Calling ratio with 1 and 4 returns 0.25."
        raw["examples"][0]["args"] = [1, 4]
        self.assertIn("cannot support `throws: true`", validate(raw).errors[0])

    def test_values_without_text_of_their_own_must_be_stated_in_the_evidence(self):
        issue = 'f 1 gives wrong. f 2 returns false. f 3 must return null. f 4 gives an empty array. f 5 gives "". f 6 gives {}.'
        mods = {"src/f.ts": "export function f(a: unknown): unknown { return a; }\n"}

        def check(returns, evidence, arg=1):
            raw = {"supported": True, "module": "src/f.ts", "examples": [
                example("e1", "f", [arg], returns=returns, evidence=evidence)]}
            return sp.validate_spec(raw, issue_text=issue, modules=mods, source_literals=set())

        for value in (False, True, None, "", [], {}, {"ok": True}):
            with self.subTest(unstated=value):
                result = check(value, "f 1 gives wrong.")
                self.assertFalse(result.ok)
                self.assertIn("is not stated in the quoted evidence", result.errors[0])
        for value, evidence, arg in ((False, "f 2 returns false.", 2), (None, "f 3 must return null.", 3),
                                     ([], "f 4 gives an empty array.", 4), ("", 'f 5 gives "".', 5), ({}, "f 6 gives {}.", 6)):
            with self.subTest(stated=value):
                self.assertTrue(check(value, evidence, arg).ok, check(value, evidence, arg).errors)
        # The word must match the value: `true` is not supported by text that says false.
        self.assertFalse(check(True, "f 2 returns false.", 2).ok)

    def test_literal_hazards_and_trivial_quotations_are_refused(self):
        def check(**change):
            raw = good_spec()
            raw["examples"][0].update(change)
            return validate(raw)
        proto = check(args=[json.loads('{"__proto__": 1}')])
        self.assertIn("__proto__", proto.errors[0])
        self.assertIn("reserved word", check(export="delete").errors[0])
        deep = check(args=[json.loads("[" * 13 + "]" * 13)])
        self.assertIn("nested at most", deep.errors[0])
        short = check(evidence="B")
        self.assertIn("too short to be a quotation", short.errors[0])

    def test_partial_mode_keeps_grounded_examples_and_records_the_rest(self):
        raw = good_spec()
        raw["examples"].append(example("e4", "formatBytes", [7], returns="seven bytes", evidence="formatBytes 7 gives seven bytes"))
        strict = validate(raw)
        self.assertFalse(strict.ok)  # strict mode is unchanged: one bad example sinks the specification
        loose = sp.validate_spec(raw, issue_text=ISSUE, modules=MODULES, source_literals=set(), partial=True)
        self.assertTrue(loose.ok, loose.errors)
        self.assertEqual([e.id for e in loose.spec.examples], ["e1", "e2", "e3"])
        self.assertEqual([label for label, _ in loose.rejected], ["example e4"])
        self.assertIn("does not appear in the issue", loose.rejected[0][1])

    def test_partial_mode_still_fails_when_nothing_is_grounded_or_the_module_is_wrong(self):
        raw = good_spec()
        raw["examples"] = [example("e4", "formatBytes", [7], returns="seven bytes", evidence="formatBytes 7 gives seven bytes")]
        result = sp.validate_spec(raw, issue_text=ISSUE, modules=MODULES, source_literals=set(), partial=True)
        self.assertFalse(result.ok)
        self.assertIn("does not appear in the issue", result.errors[0])
        raw = good_spec()
        raw["module"] = "lib/other.ts"
        self.assertFalse(sp.validate_spec(raw, issue_text=ISSUE, modules=MODULES, source_literals=set(), partial=True).ok)

    def test_json_errors_show_where_the_text_went_wrong(self):
        body = '{"returns": "say"hello", "x": 1}'
        with self.assertRaises(sp.SpecFormatError) as caught:
            sp.parse_spec_response(f"{sp.SPEC_BEGIN}\n{body}\n{sp.SPEC_END}")
        self.assertIn("near", str(caught.exception))
        self.assertIn("say", str(caught.exception))

    def test_shape_errors(self):
        def broken(change):
            raw = good_spec()
            change(raw)
            return validate(raw)
        cases = {
            "both outcomes": lambda r: r["examples"][0].update(throws=True),
            "neither outcome": lambda r: r["examples"][0].pop("returns"),
            "throws false": lambda r: (r["examples"][0].pop("returns"), r["examples"][0].update(throws=False)),
            "bad id": lambda r: r["examples"][0].update(id="E-1"),
            "duplicate id": lambda r: r["examples"][1].update(id="e1"),
            "unknown field": lambda r: r["examples"][0].update(note="x"),
            "unknown top field": lambda r: r.update(extra=1),
            "args not list": lambda r: r["examples"][0].update(args=512),
            "too many args": lambda r: r["examples"][0].update(args=[1] * 9),
            "empty examples": lambda r: r.update(examples=[]),
            "too many examples": lambda r: r.update(examples=[good_spec()["examples"][0]] * 13),
            "huge integer": lambda r: r["examples"][0].update(args=[2 ** 60]),
            "empty evidence": lambda r: r["examples"][0].update(evidence=" "),
            "supported missing": lambda r: r.pop("supported"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                result = broken(change)
                self.assertFalse(result.ok, name)
                self.assertTrue(result.errors, name)

    def test_conflicting_expectations_for_one_call(self):
        raw = good_spec()
        raw["examples"].append(example("e4", "formatBytes", [512], returns="512 B",
                                       evidence="formatBytes 512 512 B"))
        self.assertTrue(validate(raw).ok)  # the same call and result twice is harmless
        raw["examples"][3]["returns"] = "512"
        self.assertTrue(any("two different expected results" in e or "not in the quoted" in e for e in validate(raw).errors))


class CompileTests(unittest.TestCase):
    def spec(self):
        return validate(good_spec()).spec

    def test_import_specifiers(self):
        for style, expected in (("js", "../lib/utils/format.js"), ("ts", "../lib/utils/format.ts"),
                                ("bare", "../lib/utils/format")):
            self.assertEqual(sp.import_specifier("lib/utils/format.ts", "tests/t.test.ts", style), expected)
        self.assertEqual(sp.import_specifier("src/a.mts", "t.test.ts", "js"), "./src/a.mjs")
        self.assertEqual(sp.import_specifier("src/a.ts", "src/t.test.ts", "bare"), "./a")
        with self.assertRaises(ValueError):
            sp.import_specifier("a.ts", "t.ts", "weird")

    def test_output_is_deterministic_and_carries_the_spec_hash(self):
        one = sp.compile_test(self.spec(), test_path="tests/t.test.ts")
        two = sp.compile_test(validate(good_spec()).spec, test_path="tests/t.test.ts")
        self.assertEqual(one, two)
        self.assertIn(self.spec().sha256(), one)
        self.assertIn('import { formatBytes, formatSpeed } from "../lib/utils/format.js";', one)
        self.assertIn('assert.deepStrictEqual(await formatBytes(1536), "1.5 KB", "PATCHPROOF_EXAMPLE e2 VALUE");', one)

    def test_values_are_serialized_not_hand_escaped(self):
        nasty = "a\"b" + BS + "c\u2028d\u00e9" + BS + "n"
        built = sp.Spec("lib/utils/format.ts", (
            sp.Example("e1", "buildContent", ({"ssid": nasty},), "returns", nasty, "ev", "ev"),))
        source = sp.compile_test(built, test_path="tests/t.test.ts")
        self.assertTrue(source.isascii())
        literal = json.dumps(nasty)  # ensure_ascii form: quote, backslash and U+2028 are all escaped
        self.assertEqual(source.count(literal), 2)  # once as the argument, once as the expectation
        self.assertEqual(json.loads(literal), nasty)
        self.assertNotIn("\u2028", source.replace(BS + "u2028", ""))  # never a raw line separator

    def test_default_export_and_throws(self):
        built = sp.Spec("lib/utils/format.ts", (
            sp.Example("e1", "default", (), "returns", "x", "ev", "ev"),
            sp.Example("e2", "ratio", (4, 0), "throws", None, "ev", "ev")))
        source = sp.compile_test(built, test_path="tests/t.test.ts")
        self.assertIn('import patchproofDefault, { ratio } from "../lib/utils/format.js";', source)
        self.assertIn("patchproofDefault()", source)
        self.assertIn("assert.rejects(async () => { await ratio(4, 0); }, () => true,", source)


TAP = """TAP version 13
# Subtest: e1
ok 1 - e1
  ---
  duration_ms: 2.4
  type: 'test'
  ...
# Subtest: e2
not ok 2 - e2
  ---
  duration_ms: 3.0
  failureType: 'testCodeFailure'
  error: |-
    PATCHPROOF_EXAMPLE e2 VALUE
    + actual - expected
  code: 'ERR_ASSERTION'
  name: 'AssertionError'
  operator: 'deepStrictEqual'
  ...
# Subtest: e3
not ok 3 - e3
  ---
  failureType: 'testCodeFailure'
  error: 'zero'
  code: 'ERR_TEST_FAILURE'
  ...
# Subtest: e4
not ok 4 - e4
  ---
  failureType: 'testCodeFailure'
  error: 'boom from the application'
  code: 'ERR_ASSERTION'
  ...
1..4
"""


class ReadingTests(unittest.TestCase):
    def spec(self, n):
        return sp.Spec("lib/utils/format.ts", tuple(
            sp.Example(f"e{i}", "formatBytes", (i,), "returns", "x", "ev", "ev") for i in range(1, n + 1)))

    def test_states_from_tap(self):
        results = sp.parse_example_results(TAP, ["e1", "e2", "e3", "e4", "e5"])
        self.assertEqual({k: v["state"] for k, v in results.items()},
                         {"e1": "pass", "e2": "mismatch", "e3": "error", "e4": "error", "e5": "missing"})
        self.assertEqual(results["e3"]["code"], "ERR_TEST_FAILURE")

    def test_an_assertion_raised_inside_the_application_is_not_the_examples_own(self):
        self.assertEqual(sp.parse_example_results(TAP, ["e4"])["e4"]["state"], "error")

    def test_accept_when_a_value_mismatch_is_the_only_failure(self):
        decision = sp.decide({"e1": {"state": "pass"}, "e2": {"state": "mismatch"}}, self.spec(2))
        self.assertEqual((decision.action, decision.qualifying, decision.pruned), ("accept", ["e2"], {}))

    def test_errors_are_dropped_and_the_test_recompiled(self):
        decision = sp.decide({"e1": {"state": "pass"}, "e2": {"state": "mismatch"}, "e3": {"state": "error"}}, self.spec(3))
        self.assertEqual(decision.action, "recompile")
        self.assertEqual(list(decision.pruned), ["e3"])
        self.assertEqual(decision.qualifying, ["e2"])

    def test_all_passing_is_not_a_reproduction(self):
        decision = sp.decide({"e1": {"state": "pass"}, "e2": {"state": "pass"}}, self.spec(2))
        self.assertEqual((decision.action, decision.classification), ("retry", "test passed on the unfixed revision"))

    def test_only_errors_is_not_a_reproduction_either(self):
        decision = sp.decide({"e1": {"state": "error", "detail": "TypeError"}, "e2": {"state": "pass"}}, self.spec(2))
        self.assertEqual((decision.action, decision.classification),
                         ("retry", "test failed without accepted assertion evidence"))
        self.assertIn("TypeError", decision.message)

    def test_a_missing_result_is_never_accepted(self):
        decision = sp.decide({"e1": {"state": "mismatch"}, "e2": {"state": "missing"}}, self.spec(2))
        self.assertEqual(decision.action, "retry")


if __name__ == "__main__":
    unittest.main()
