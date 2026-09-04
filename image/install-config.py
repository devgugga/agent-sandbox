#!/usr/bin/env python3
"""Instala um destino de configuracao sem seguir symlinks do agente."""
import os
import shutil
import stat
import sys
from pathlib import Path

ALLOWED_ROOTS = (
    Path("/home/agent/.claude"),
    Path("/home/agent/.codex"),
    Path("/home/agent/.gemini"),
)
PROTECTED = {
    Path("/home/agent/.claude/.credentials.json"),
    Path("/home/agent/.codex/auth.json"),
}


def allowed(path: Path) -> bool:
    return ".." not in path.parts and path not in PROTECTED and any(
        path != root and path.is_relative_to(root) for root in ALLOWED_ROOTS
    )


def remove_leaf(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def secure_parents(path: Path) -> None:
    current = Path("/home/agent")
    for part in path.parent.relative_to(current).parts:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            os.chown(current, 1000, 1000)
            continue
        if stat.S_ISDIR(mode) and not stat.S_ISLNK(mode):
            continue
        # Remove somente o componente em si. Nunca atravessa um symlink.
        remove_leaf(current)
        current.mkdir(mode=0o700)
        os.chown(current, 1000, 1000)


def prepare(path: Path) -> None:
    secure_parents(path)
    remove_leaf(path)


def finalize(path: Path) -> None:
    secure_parents(path)
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        raise RuntimeError(f"destino virou symlink durante a copia: {path}")
    if path.is_dir():
        for directory, names, files in os.walk(path, followlinks=False):
            directory_path = Path(directory)
            os.chown(directory_path, 1000, 1000, follow_symlinks=False)
            for name in [*names, *files]:
                child = directory_path / name
                if child.is_symlink():
                    raise RuntimeError(f"symlink inesperado no staging: {child}")
                os.chown(child, 1000, 1000, follow_symlinks=False)
    else:
        os.chown(path, 1000, 1000, follow_symlinks=False)


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"prepare", "finalize"}:
        print("uso: asb-install-config <prepare|finalize> <destino>", file=sys.stderr)
        return 2
    path = Path(sys.argv[2])
    if not path.is_absolute() or not allowed(path):
        print(f"destino recusado: {path}", file=sys.stderr)
        return 1
    try:
        (prepare if sys.argv[1] == "prepare" else finalize)(path)
    except (OSError, RuntimeError) as error:
        print(f"instalacao recusada para {path}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
