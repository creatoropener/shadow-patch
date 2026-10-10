"""Immutable repository snapshots and bounded, literal retrieval tools."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from types import MappingProxyType

from agent_budget import AgentStop


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RepositorySnapshot:
    def __init__(self, root, adapter, excluded_dirs, protected_names, protected_path):
        files, editable = {}, set()
        total = 0
        excluded = set(excluded_dirs) | {"bench", "legacy", "patchproof_runtime", "patchproof_helpers"}
        skipped = []
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in excluded and not d.startswith(".")
                             and d.lower() != "regression" and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                path = Path(directory) / name
                relative = path.relative_to(root)
                if name.startswith(".") or name in protected_names or path.is_symlink():
                    continue
                if not (adapter.is_context_file(relative) or path.suffix in {".md", ".txt"}):
                    continue
                if not path.resolve().is_relative_to(root.resolve()):
                    continue
                key = relative.as_posix()
                if path.stat().st_size > 1_000_000:
                    skipped.append({"path": key, "reason": "file_exceeds_1MB"})
                    continue
                try:
                    content = path.read_bytes().decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    skipped.append({"path": key, "reason": "not_readable_utf8"})
                    continue
                if "\x00" in content:
                    continue
                total += len(content.encode("utf-8"))
                if len(files) >= 10_000 or total > 64_000_000:
                    raise AgentStop("blocked_setup", "Repository snapshot exceeds the 10,000-file/64MB profile; narrow the checkout.")
                files[key] = content
                if adapter.is_editable_source(relative) and not protected_path(relative):
                    editable.add(key)
        if not files:
            raise AgentStop("blocked_setup", "No readable repository files in the bounded profile.")
        self.files = MappingProxyType(files)
        self.editable = frozenset(editable)
        self.hashes = {path: digest(content) for path, content in files.items()}
        self.identity = digest(json.dumps(self.hashes, sort_keys=True))
        self.skipped = skipped

    def provenance(self):
        return {"snapshot_sha256": self.identity, "files": self.hashes,
                "skipped": self.skipped, "file_count": len(self.files),
                "retrieval": "literal search and lexical declaration lookup; pagination and line ranges"}

    def tools(self, allowed=None):
        return ContextTools(self, self.editable if allowed is None else allowed)


class ContextTools:
    def __init__(self, snapshot: RepositorySnapshot, allowed):
        self.snapshot = snapshot
        self.allowed = frozenset(allowed)
        self.overlay: dict[str, str] = {}
        self.observed: dict[str, str] = {}

    def content(self, path):
        if not isinstance(path, str) or PurePosixPath(path).as_posix() != path or path not in self.snapshot.files:
            raise ValueError("Path is not in the immutable repository inventory.")
        return self.overlay.get(path, self.snapshot.files[path])

    @staticmethod
    def number(value, low, high, label):
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise ValueError(f"{label} must be an integer between {low} and {high}.")
        return value

    def invoke(self, action: dict) -> dict:
        name = action.get("action")
        if name == "read":
            path = action.get("path")
            content = self.content(path)
            start = self.number(action.get("start_line", 1), 1, 1_000_000, "start_line")
            count = self.number(action.get("line_count", 100), 1, 200, "line_count")
            lines = content.splitlines()
            if start > len(lines) + 1:
                raise ValueError("start_line is beyond this file.")
            entries, size = [], 0
            for index in range(start - 1, min(len(lines), start - 1 + count)):
                text = lines[index]
                if len(text) > 8000:
                    raise ValueError("This source line exceeds the 8000-character retrieval limit.")
                if entries and size + len(text) > 8000:
                    break
                entries.append({"line": index + 1, "text": text})
                size += len(text)
            self.observed[path] = digest(content)
            following = start + len(entries)
            return {"path": path, "sha256": digest(content), "editable": path in self.allowed,
                    "total_lines": len(lines), "lines": entries,
                    "line_ending": "CRLF" if "\r\n" in content else "LF",
                    "next_line": following if following <= len(lines) else None}
        prefix = action.get("path_prefix", "")
        if not isinstance(prefix, str) or len(prefix) > 500:
            raise ValueError("path_prefix must be a short string.")
        offset = self.number(action.get("offset", 0), 0, 1_000_000, "offset")
        paths = [path for path in sorted(self.snapshot.files) if path.startswith(prefix)]
        if name == "list":
            return {"files": [{"path": path, "editable": path in self.allowed,
                               "sha256": digest(self.content(path))} for path in paths[offset:offset+80]],
                    "total": len(paths), "next_offset": offset + 80 if offset + 80 < len(paths) else None}
        if name not in {"search", "symbols"}:
            raise ValueError("Unknown repository tool.")
        query = action.get("query", "")
        if not isinstance(query, str) or not 1 <= len(query) <= 200:
            raise ValueError("query must contain 1 to 200 literal characters.")
        # No user/model regex execution; this is a bounded lexical index, not a
        # claim of complete TypeScript symbol resolution.
        declaration = re.compile(r"\b(?:function|class|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)")
        matches, seen = [], 0
        for path in paths:
            for line_number, line in enumerate(self.content(path).splitlines(), 1):
                found = query in line if name == "search" else any(query in item for item in declaration.findall(line))
                if not found:
                    continue
                if seen >= offset:
                    matches.append({"path": path, "line": line_number, "text": line[:400]})
                    if len(matches) == 41:
                        return {"matches": matches[:40], "next_offset": offset + 40}
                seen += 1
        return {"matches": matches, "next_offset": None}

    def prepare_edits(self, edits: list, adapter) -> list[dict]:
        if not isinstance(edits, list) or not 1 <= len(edits) <= 20:
            raise ValueError("edit requires 1 to 20 exact-match edits.")
        proposed = dict(self.overlay)
        for edit in edits:
            if not isinstance(edit, dict) or set(edit) != {"path", "old", "new"}:
                raise ValueError("Each edit requires exactly path, old, new.")
            path, old, new = edit["path"], edit["old"], edit["new"]
            if not all(isinstance(value, str) for value in (path, old, new)) or not old:
                raise ValueError("Edits require strings and a non-empty old snippet.")
            if path not in self.allowed:
                raise ValueError("scope_failed: edit targets a protected, unknown, or disallowed path.")
            if self.observed.get(path) != digest(self.content(path)):
                raise ValueError("Read the current file before editing it.")
            content = proposed.get(path, self.snapshot.files[path])
            if content.count(old) != 1:
                raise ValueError(f"Exact old snippet must occur once in {path}.")
            proposed[path] = content.replace(old, new, 1)
            if len(proposed[path].encode("utf-8")) > 1_000_000:
                raise ValueError("Edited source exceeds the supported 1MB file limit.")
            adapter.validate_candidate_file(path, proposed[path])
        changes = [{"path": path, "content": content} for path, content in sorted(proposed.items())
                   if content != self.snapshot.files[path]]
        if not changes:
            raise ValueError("The proposal has no net source change.")
        if len(changes) > 10:
            raise ValueError("A bounded repair may change at most ten source files.")
        return changes

    def accept(self, changes):
        self.overlay = {item["path"]: item["content"] for item in changes}

    def changes(self):
        return [{"path": path, "content": content} for path, content in sorted(self.overlay.items())]
