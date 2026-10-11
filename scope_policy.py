"""Explicit repair boundaries, read from the original repository configuration."""
from __future__ import annotations

import ast
import json
from contextvars import ContextVar
from pathlib import Path, PurePosixPath

# patchproof.json lives in the repository checkout even when the project is a subfolder (`root`).
CONFIG_ROOT: ContextVar = ContextVar("patchproof_config_root", default=None)
JS_EXTENSIONS = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}


def validate_scope(value: object) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - {"allowed_paths", "protected_symbols", "new_file_dirs"}:
        raise ValueError("scope accepts allowed_paths, protected_symbols and new_file_dirs only")

    def safe(path):
        return (isinstance(path, str) and bool(path) and "\\" not in path
                and not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts
                and PurePosixPath(path).as_posix() == path)

    if "allowed_paths" in value:
        paths = value["allowed_paths"]
        if not isinstance(paths, list) or not paths or not all(safe(p) for p in paths):
            raise ValueError("scope.allowed_paths needs a nonempty list of exact repository-relative paths")
    if "new_file_dirs" in value:
        dirs = value["new_file_dirs"]
        if (not isinstance(dirs, list) or not 1 <= len(dirs) <= 5 or not all(safe(d) for d in dirs)
                or any(part.startswith(".") for d in dirs for part in PurePosixPath(d).parts)
                or len(set(dirs)) != len(dirs)):
            raise ValueError("scope.new_file_dirs needs 1 to 5 distinct existing repository-relative folders "
                             "(no hidden folders) where the repair may create new source files")
    symbols = value.get("protected_symbols", {})
    if not isinstance(symbols, dict):
        raise ValueError("scope.protected_symbols must map source paths to symbol-name lists")
    for path, names in symbols.items():
        if (not safe(path) or Path(path).suffix not in JS_EXTENSIONS | {".py"}
                or not isinstance(names, list) or not names
                or not all(isinstance(n, str) and n.isidentifier() for n in names)):
            raise ValueError("protected_symbols supports named top-level JS/TS/Python declarations")
    return value


def load_scope(root: Path) -> dict:
    config = (CONFIG_ROOT.get() or root) / "patchproof.json"
    scope = validate_scope(json.loads(config.read_text()).get("scope")) if config.is_file() else {}
    for name in scope.get("protected_symbols", {}):
        path = root / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("Protected symbol file is missing or outside the repository: " + name)
    return scope


def new_file_allowed(name: str, scope: dict) -> bool:
    """A file that does not exist yet may be created only inside a declared folder."""
    return any(name.startswith(folder + "/") for folder in scope.get("new_file_dirs", ()))


def check_paths(root: Path, changes: list[dict], scope: dict) -> None:
    allowed = scope.get("allowed_paths")
    for change in changes:
        name = change["path"]
        if not (root / name).is_file():
            if not new_file_allowed(name, scope):
                raise ValueError(f"scope_failed: {name} does not exist and is outside scope.new_file_dirs")
            continue
        if allowed is not None and name not in allowed:
            raise ValueError(f"scope_failed: {name} is outside scope.allowed_paths")
    updated = {item["path"]: item["content"] for item in changes}
    for name, protected in scope.get("protected_symbols", {}).items():
        if Path(name).suffix == ".py":
            def declarations(source):
                return {node.name: ast.dump(node, include_attributes=False)
                        for node in ast.parse(source).body
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
            old = declarations((root / name).read_text())
            new = declarations(updated.get(name, (root / name).read_text()))
            for symbol in protected:
                if symbol not in old or old[symbol] != new.get(symbol):
                    raise ValueError(f"scope_failed: protected symbol {name}:{symbol} changed or is missing")


def node_payload(root: Path, changes: list[dict], scope: dict) -> dict:
    # Check configured symbols even when their file was not edited, so a typo
    # in the policy cannot silently claim protection that was never evaluated.
    files = {item["path"]: item for item in changes}
    for name in scope.get("protected_symbols", {}):
        files.setdefault(name, {"path": name, "content": (root / name).read_text()})
    return {"files": [{**change, "original": (root / change["path"]).read_text() if (root / change["path"]).is_file() else "",
                       "protected_symbols": scope.get("protected_symbols", {}).get(change["path"], [])}
                      for change in files.values() if Path(change["path"]).suffix in JS_EXTENSIONS]}
