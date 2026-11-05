"""Extract the official CLI ZIP using stdlib, retaining executable file modes."""

import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath


def extract_installer(archive: str, destination: str) -> None:
    with zipfile.ZipFile(archive) as package:
        # Validate the entire package before writing any files.
        for member in package.infolist():
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if path.is_absolute() or ".." in path.parts or stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise ValueError(f"unsafe AWS CLI installer member: {member.filename}")
        for member in package.infolist():
            target = Path(package.extract(member, destination))
            # ZIP extraction drops executable bits; the installer and CLI need them.
            target.chmod(0o755 if member.is_dir() or (member.external_attr >> 16) & 0o111 else 0o644)


if __name__ == "__main__":
    extract_installer(*sys.argv[1:])
