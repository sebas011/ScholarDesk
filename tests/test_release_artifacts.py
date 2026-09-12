import hashlib

import pytest

from write_release_checksums import MANIFEST_FILENAME, write_release_checksums


def test_release_checksum_manifest_contains_each_portable_executable(tmp_path):
    release_directory = tmp_path / "dist"
    release_directory.mkdir()
    scholar_desk = release_directory / "ScholarDesk.exe"
    admin = release_directory / "ScholarDeskAdmin.exe"
    scholar_desk.write_bytes(b"scholar-desk")
    admin.write_bytes(b"scholar-desk-admin")

    manifest = write_release_checksums(release_directory)

    assert manifest == release_directory / MANIFEST_FILENAME
    assert manifest.read_text(encoding="ascii") == (
        f"{hashlib.sha256(b'scholar-desk').hexdigest()}  ScholarDesk.exe\n"
        f"{hashlib.sha256(b'scholar-desk-admin').hexdigest()}  ScholarDeskAdmin.exe\n"
    )


def test_release_checksum_manifest_rejects_an_incomplete_release(tmp_path):
    release_directory = tmp_path / "dist"
    release_directory.mkdir()
    (release_directory / "ScholarDesk.exe").write_bytes(b"scholar-desk")

    with pytest.raises(ValueError, match="ScholarDeskAdmin.exe"):
        write_release_checksums(release_directory)

    assert not (release_directory / MANIFEST_FILENAME).exists()
