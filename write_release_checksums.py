"""Write a SHA-256 manifest for the portable ScholarDesk release."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Sequence


RELEASE_EXECUTABLES = ("ScholarDesk.exe", "ScholarDeskAdmin.exe")
MANIFEST_FILENAME = "SHA256SUMS.txt"
CHUNK_SIZE_BYTES = 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(CHUNK_SIZE_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_release_checksums(release_directory: Path) -> Path:
    """Write checksums for the exact executable set distributed to users."""
    directory = release_directory.resolve()
    if not directory.is_dir():
        raise ValueError(f"Release directory not found: {directory}")

    manifest_entries: list[str] = []
    for filename in RELEASE_EXECUTABLES:
        artifact = directory / filename
        if not artifact.is_file():
            raise ValueError(f"Release executable not found: {artifact}")
        manifest_entries.append(f"{_sha256_file(artifact)}  {filename}")

    manifest = directory / MANIFEST_FILENAME
    temporary_manifest = manifest.with_suffix(".tmp")
    temporary_manifest.write_text("\n".join(manifest_entries) + "\n", encoding="ascii")
    temporary_manifest.replace(manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_directory", type=Path)
    arguments = parser.parse_args(argv)

    try:
        manifest = write_release_checksums(arguments.release_directory)
    except ValueError as error:
        parser.error(str(error))

    print(f"Wrote {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
