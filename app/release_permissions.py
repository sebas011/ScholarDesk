"""Read-only Windows ACL checks for a private ScholarDesk release folder."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess


class ReleasePermissionError(RuntimeError):
    """Raised when release-folder permissions cannot be verified safely."""


_BROAD_ACCESS_SIDS = (
    "S-1-1-0",  # Everyone
    "S-1-5-11",  # Authenticated Users
    "S-1-5-32-545",  # BUILTIN\\Users
    "S-1-5-32-546",  # BUILTIN\\Guests
)
USERS_REGISTRY_FILENAME = "users.json"
_POWERSHELL_ACL_CHECK = r"""
$paths = ConvertFrom-Json ([Environment]::GetEnvironmentVariable('SCHOLARDESK_ACL_PATHS'))
$broadSids = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545', 'S-1-5-32-546')
$findings = @()
foreach ($path in $paths) {
    $acl = Get-Acl -LiteralPath $path -ErrorAction Stop
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) {
            continue
        }
        try {
            $sid = $rule.IdentityReference.Translate(
                [System.Security.Principal.SecurityIdentifier]
            ).Value
        } catch {
            continue
        }
        if ($broadSids -contains $sid) {
            $findings += [PSCustomObject]@{
                path = $path
                sid = $sid
                rights = $rule.FileSystemRights.ToString()
            }
        }
    }
}
[PSCustomObject]@{
    valid = ($findings.Count -eq 0)
    findings = @($findings)
} | ConvertTo-Json -Compress -Depth 3
"""


def _is_windows() -> bool:
    return os.name == "nt"


def check_release_directory_permissions(release_directory: Path) -> None:
    """Reject a release folder readable by broad local Windows groups.

    This is intentionally diagnostic only. It never changes ACLs because the
    correct allowed local accounts are deployment-specific.
    """
    release_directory = release_directory.resolve()
    if not _is_windows():
        raise ReleasePermissionError("Release permission checks are supported on Windows only.")
    if not release_directory.is_dir():
        raise ReleasePermissionError(f"Release directory not found: {release_directory}")

    encoded_script = base64.b64encode(
        _POWERSHELL_ACL_CHECK.encode("utf-16-le")
    ).decode("ascii")
    protected_paths = [release_directory]
    protected_paths.extend(
        path
        for path in (
            release_directory / "grants.db",
            release_directory / "auth.txt",
            release_directory / USERS_REGISTRY_FILENAME,
            release_directory / "backups",
        )
        if path.exists()
    )
    environment = os.environ.copy()
    environment["SCHOLARDESK_ACL_PATHS"] = json.dumps(
        [str(path) for path in protected_paths]
    )
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded_script,
            ],
            capture_output=True,
            check=False,
            encoding="utf-8",
            env=environment,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ReleasePermissionError(f"Could not inspect release permissions: {error}") from error

    if result.returncode != 0:
        raise ReleasePermissionError(
            f"Could not inspect release permissions: {result.stderr.strip()}"
        )
    try:
        report = json.loads(result.stdout)
        findings = report["findings"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ReleasePermissionError(
            "Release permission check returned an invalid report."
        ) from error

    if report.get("valid") is not True or findings:
        rendered_findings = ", ".join(
            f"{finding['sid']} ({finding['rights']})" for finding in findings
        )
        raise ReleasePermissionError(
            "Release directory allows broad local access: "
            f"{rendered_findings}. Restrict its Windows ACL before release."
        )
