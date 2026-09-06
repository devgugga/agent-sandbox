"""agent-sandbox project adapter for Graphify file detection.

Graphify's native detector deliberately supports a bounded set of standard
code and document formats. agent-sandbox also treats operational configuration
(Containerfile, shell recipes, proxy templates, TOML profiles) as architecture
knowledge, so this adapter routes safe operational configuration through the
semantic ``document`` pipeline.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Resolve graphify import when run in environments where graphify was installed via uv tool
try:
    from graphify.detect import (
        _is_sensitive,
        _md5_file,
        detect,
        detect_incremental,
        load_manifest,
    )
except ModuleNotFoundError:
    _resolved = False
    _binary = shutil.which("graphify")
    if _binary:
        _bin_path = Path(_binary).resolve()
        try:
            with open(_bin_path, "rb") as _f:
                _first_line = _f.readline().decode("utf-8", errors="ignore")
            if _first_line.startswith("#!"):
                _py_bin = Path(_first_line[2:].strip())
                _lib_dir = _py_bin.parent.parent / "lib"
                for _sp in _lib_dir.glob("python*/site-packages"):
                    if _sp.is_dir() and str(_sp) not in sys.path:
                        sys.path.insert(0, str(_sp))
                        _resolved = True
        except Exception:
            pass
    if not _resolved:
        _uv_tools = Path.home() / ".local" / "share" / "uv" / "tools" / "graphifyy" / "lib"
        for _sp in _uv_tools.glob("python*/site-packages"):
            if _sp.is_dir() and str(_sp) not in sys.path:
                sys.path.insert(0, str(_sp))
                _resolved = True
    from graphify.detect import (
        _is_sensitive,
        _md5_file,
        detect,
        detect_incremental,
        load_manifest,
    )


_CONFIG_SUFFIXES = {
    ".bash",
    ".conf",
    ".sh",
    ".tmpl",
    ".toml",
    ".yaml",
    ".yml",
}

_CONFIG_NAMES = {
    ".gitattributes",
    ".gitignore",
    ".graphifyignore",
    "Containerfile",
    "Containerfile.proxy",
    "allowlist-base.txt",
    "asb-agent",
    "asb-docker-broker.service.tmpl",
    "asb-guard",
}

_EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".superpowers",
    ".venv",
    ".worktrees",
    "__pycache__",
    "dist",
    "graphify-out",
    "node_modules",
    "scratch",
    "state",
}

_MAX_CONFIG_BYTES = 1_000_000


def _is_excluded(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    if any(part in _EXCLUDED_PARTS for part in relative.parts):
        return True
    name = path.name
    if name.startswith(".env"):
        return True
    if name == ".agent-sandbox.toml" or name.startswith(".agent-sandbox.toml"):
        return True
    if name.startswith("id_ed25519"):
        return True
    if name == "keyring.pass" or name.endswith(".pass") or path.suffix == ".pass":
        return True
    return _is_sensitive(path)


def _is_project_config(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
        size = path.stat().st_size
    except (OSError, ValueError):
        return False
    if any(part in _EXCLUDED_PARTS for part in relative.parts):
        return False
    if _is_excluded(path, root):
        return False
    if size > _MAX_CONFIG_BYTES:
        return False
    return (
        path.name in _CONFIG_NAMES
        or path.name.startswith("Containerfile.")
        or path.suffix.lower() in _CONFIG_SUFFIXES
    )


def _tracked_files(root: Path) -> list[Path]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            check=True,
            capture_output=True,
        )
        if completed.returncode == 0 and completed.stdout:
            return [
                (root / raw.decode("utf-8")).resolve()
                for raw in completed.stdout.split(b"\0")
                if raw
            ]
    except Exception:
        pass
    return [p.resolve() for p in root.rglob("*") if p.is_file()]


def _sanitize_native_result(result: dict, root: Path) -> None:
    for key in ("files", "new_files", "unchanged_files"):
        if key not in result:
            continue
        for category, paths in list(result[key].items()):
            sanitized_paths = []
            for path in paths:
                p = Path(path)
                if _is_excluded(p, root):
                    continue
                if category == "code" and _is_project_config(p, root):
                    continue
                sanitized_paths.append(path)
            result[key][category] = sanitized_paths
    if "deleted_files" in result:
        result["deleted_files"] = [
            path
            for path in result["deleted_files"]
            if not _is_excluded(Path(path), root)
        ]
    if "excluded_files" in result:
        result["excluded_files"] = [
            path
            for path in result["excluded_files"]
            if not _is_excluded(Path(path), root)
        ]


def _additional_configs(root: Path, existing: set[Path]) -> list[Path]:
    return sorted(
        (
            path
            for path in _tracked_files(root)
            if path.is_file()
            and path not in existing
            and _is_project_config(path, root)
        ),
        key=lambda path: path.as_posix(),
    )


def _all_detected_paths(result: dict) -> set[Path]:
    return {
        Path(path).resolve()
        for paths in result.get("files", {}).values()
        for path in paths
    }


def _word_count(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += len(path.read_text(encoding="utf-8", errors="ignore").split())
        except OSError:
            continue
    return total


def detect_project(root: Path) -> dict:
    """Run native detection and add safe, tracked agent-sandbox configuration."""
    root = root.resolve()
    result = detect(root)
    native_code_paths = set(result.get("files", {}).get("code", []))
    _sanitize_native_result(result, root)
    configs = _additional_configs(root, _all_detected_paths(result))
    documents = result.setdefault("files", {}).setdefault("document", [])
    documents.extend(str(path) for path in configs)
    documents.sort()
    result["total_files"] = sum(len(paths) for paths in result["files"].values())
    uncounted_configs = [path for path in configs if str(path) not in native_code_paths]
    result["total_words"] = result.get("total_words", 0) + _word_count(uncounted_configs)
    result["project_config_files"] = [str(path) for path in configs]
    return result


def detect_incremental_project(root: Path, manifest_path: str | None = None) -> dict:
    """Run incremental detection with the same project configuration corpus."""
    root = root.resolve()
    if manifest_path is not None:
        result = detect_incremental(root, manifest_path=manifest_path)
        manifest = load_manifest(manifest_path, root=root)
    else:
        result = detect_incremental(root)
        manifest = load_manifest(root=root)

    native_code_paths = set(result.get("files", {}).get("code", []))
    _sanitize_native_result(result, root)
    existing = _all_detected_paths(result)
    configs = _additional_configs(root, existing)
    config_strings = [str(path) for path in configs]

    documents = result.setdefault("files", {}).setdefault("document", [])
    documents.extend(config_strings)
    documents.sort()

    changed_configs = []
    unchanged_configs = []
    for path in configs:
        stored = manifest.get(str(path))
        if not isinstance(stored, dict) or stored.get("semantic_hash") != _md5_file(path):
            changed_configs.append(str(path))
        else:
            unchanged_configs.append(str(path))

    new_documents = result.setdefault("new_files", {}).setdefault("document", [])
    new_documents.extend(path for path in changed_configs if path not in new_documents)
    new_documents.sort()

    if "unchanged_files" in result:
        unchanged_docs = result.setdefault("unchanged_files", {}).setdefault("document", [])
        unchanged_docs.extend(path for path in unchanged_configs if path not in unchanged_docs)
        unchanged_docs.sort()

    current_configs = {str(path.resolve()) for path in configs}
    result["deleted_files"] = [
        path
        for path in result.get("deleted_files", [])
        if str(Path(path).resolve()) not in current_configs
        and not _is_excluded(Path(path), root)
    ]
    if "excluded_files" in result:
        result["excluded_files"] = [
            path
            for path in result["excluded_files"]
            if str(Path(path).resolve()) not in current_configs
            and not _is_excluded(Path(path), root)
        ]
    result["new_total"] = sum(
        len(paths) for paths in result.get("new_files", {}).values()
    )
    result["total_files"] = sum(len(paths) for paths in result["files"].values())
    uncounted_configs = [path for path in configs if str(path) not in native_code_paths]
    result["total_words"] = result.get("total_words", 0) + _word_count(uncounted_configs)
    result["project_config_files"] = config_strings
    return result
