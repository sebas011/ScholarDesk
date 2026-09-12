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
    assert "portable-build:" in workflow
    assert "runs-on: windows-latest" in workflow
    assert "python -m venv .venv" in workflow
    assert "cmd /c build.bat" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "dist/ScholarDesk.exe" in workflow
    assert "dist/ScholarDeskAdmin.exe" in workflow
    assert "if-no-files-found: error" in workflow
