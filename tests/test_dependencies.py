from pathlib import Path


def test_requirements_use_supported_starlette_testclient_dependency():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()

    assert "httpx2==2.12.0" in requirements
    assert not any(
        requirement.startswith("httpx") and not requirement.startswith("httpx2")
        for requirement in requirements
    )
