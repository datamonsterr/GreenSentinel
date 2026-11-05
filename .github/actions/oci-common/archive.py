"""Pack explicit workflow paths and safely restore private CI archives."""

import fnmatch
import os
import sys
import tarfile
from pathlib import Path, PurePosixPath


def pack(archive: str, paths: str) -> None:
    requested = [Path(line.strip()).absolute() for line in paths.splitlines() if line.strip()]
    roots = [path if path.is_dir() else path.parent for path in requested]
    root = Path(os.path.commonpath(roots)) if roots else Path.cwd()
    hidden = os.environ.get("OCI_INCLUDE_HIDDEN", "false").lower() == "true"
    exclusions = [
        line.strip().removeprefix("./") for line in os.environ.get("OCI_EXCLUDE", "").splitlines() if line.strip()
    ]
    files = {}
    for path in requested:
        if not path.exists():
            continue
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        for candidate in candidates:
            relative = candidate.relative_to(root)
            parts = relative.parts
            if not hidden and any(part.startswith(".") for part in parts):
                continue
            if any(fnmatch.fnmatch(relative.as_posix(), pattern) or pattern in parts for pattern in exclusions):
                continue
            # Never traverse/upload links outside the requested report/build paths.
            if candidate.is_symlink():
                raise ValueError(f"unsafe OCI artifact source: {relative}")
            if candidate.is_file():
                files[relative.as_posix()] = candidate
    if not files:
        policy = os.environ.get("OCI_MISSING", "error")
        message = "OCI artifact upload: no files found"
        if policy == "error":
            raise ValueError(message)
        if policy not in {"warn", "ignore"}:
            raise ValueError("Invalid if-no-files-found policy")
        if policy == "warn":
            print(f"::warning::{message}")
        return
    with tarfile.open(archive, "w:gz") as stream:
        for name, path in sorted(files.items()):
            stream.add(path, arcname=name, recursive=False)


def extract(archive: str, target: str) -> None:
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f"unsafe OCI artifact member: {member.name}")
        Path(target).mkdir(parents=True, exist_ok=True)
        stream.extractall(target, filter="data")


if __name__ == "__main__":
    operation, artifact, location = sys.argv[1:]
    try:
        {"pack": pack, "extract": extract}[operation](artifact, location)
    except (OSError, ValueError, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
