"""T3.1 auth + service wiring: build Docs + Drive clients from service-account creds.

No real network: a fake credentials factory and a fake discovery build capture
the arguments so we can assert the documented scopes and that both services are
constructed.
"""

from __future__ import annotations

from gdoc_to_medium.drive_client import SCOPES, DriveClient


class _FakeCreds:
    def __init__(self, filename, scopes):
        self.filename = filename
        self.scopes = scopes


def _make_factories():
    calls = {"creds": [], "build": []}

    def credentials_factory(filename, scopes):
        creds = _FakeCreds(filename, scopes)
        calls["creds"].append(creds)
        return creds

    def build_service(name, version, credentials):
        calls["build"].append((name, version, credentials))
        return f"{name}-service"

    return credentials_factory, build_service, calls


def test_builds_both_services_with_documented_scopes():
    credentials_factory, build_service, calls = _make_factories()

    client = DriveClient.from_service_account(
        "C:/secrets/sa.json",
        "ready-folder-id",
        credentials_factory=credentials_factory,
        build_service=build_service,
    )

    # Credentials loaded once from the given file with exactly the documented scopes.
    assert len(calls["creds"]) == 1
    assert calls["creds"][0].filename == "C:/secrets/sa.json"
    assert list(calls["creds"][0].scopes) == list(SCOPES)

    built = {(name, version) for name, version, _ in calls["build"]}
    assert ("docs", "v1") in built
    assert ("drive", "v3") in built
    # Both services were built from the same credential object.
    creds_obj = calls["creds"][0]
    assert all(cred is creds_obj for _, _, cred in calls["build"])

    assert client._docs == "docs-service"
    assert client._drive == "drive-service"
    assert client._ready_folder_id == "ready-folder-id"


def test_scopes_cover_docs_read_and_drive_write():
    # Docs scope enables documents.get + batchUpdate; drive scope enables files.update moves.
    assert "https://www.googleapis.com/auth/documents" in SCOPES
    assert "https://www.googleapis.com/auth/drive" in SCOPES


def test_accepts_pathlike_service_account_file():
    from pathlib import Path

    credentials_factory, build_service, calls = _make_factories()
    DriveClient.from_service_account(
        Path("relative") / "sa.json",
        "fid",
        credentials_factory=credentials_factory,
        build_service=build_service,
    )
    # Path is stringified before reaching google-auth.
    assert isinstance(calls["creds"][0].filename, str)
