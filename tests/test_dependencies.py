from pathlib import Path


def test_requirements_use_supported_starlette_testclient_dependency():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()

    assert "httpx2==2.12.0" in requirements
    assert not any(
        requirement.startswith("httpx") and not requirement.startswith("httpx2")
        for requirement in requirements
    )


def test_ci_builds_and_preserves_the_windows_portable_release_artifact():
    workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in workflow
    assert "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5" in workflow
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6" in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7" in workflow
    assert "uses: actions/checkout@v" not in workflow
    assert "uses: actions/setup-python@v" not in workflow
    assert "uses: actions/upload-artifact@v" not in workflow
    assert "portable-build:" in workflow
    assert "runs-on: windows-latest" in workflow
    assert "python -m venv .venv" in workflow
    assert "cmd /c build.bat" in workflow
    assert "Smoke test packaged release" in workflow
    assert "SCHOLARDESK_HEADLESS = \"1\"" in workflow
    assert "http://127.0.0.1:8000/health" in workflow
    assert "grants.db in the clean release directory" in workflow
    assert "dist/ScholarDesk.exe" in workflow
    assert "dist/ScholarDeskAdmin.exe" in workflow
    assert "dist/SHA256SUMS.txt" in workflow
    assert "if-no-files-found: error" in workflow
