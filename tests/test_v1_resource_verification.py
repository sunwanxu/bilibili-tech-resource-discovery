import json

from bhka.v1.contracts import (
    NetworkBudget,
    ResourceAccessStatus,
    ResourceKind,
    ResourceLicenseStatus,
    ResourceRecord,
    VerificationScope,
)
from bhka.v1.resource_verification import (
    GenericResourceVerifier,
    GitHubResourceVerifier,
    HttpResponse,
)


def github_resource():
    return ResourceRecord(
        locator="https://github.com/acme/board/tree/main/hardware",
        repository_root="https://github.com/acme/board",
        host="github.com",
        kind=ResourceKind.REPOSITORY,
    )


def test_github_core_verification_uses_metadata_license_without_extra_request():
    calls = []

    def transport(request, timeout):
        calls.append(request.full_url)
        return HttpResponse(
            status=200,
            body=json.dumps(
                {"license": {"spdx_id": "MIT"}, "archived": False, "disabled": False}
            ).encode(),
        )

    budget = NetworkBudget(external_requests_limit=2)
    result = GitHubResourceVerifier(transport=transport).verify(
        github_resource(),
        budget=budget,
        scope=VerificationScope.CORE,
    )

    assert len(calls) == 1
    assert result.access_status == ResourceAccessStatus.ACCESSIBLE
    assert result.license_status == ResourceLicenseStatus.VERIFIED
    assert result.license_name == "MIT"
    assert result.license_scope == "repository:acme/board"


def test_full_github_verification_detects_hardware_artifacts():
    def transport(request, timeout):
        if request.full_url.endswith("/contents"):
            return HttpResponse(
                status=200,
                body=json.dumps(
                    [
                        {"name": "README.md", "type": "file"},
                        {"name": "main.kicad_pcb", "type": "file"},
                        {"name": "main.kicad_sch", "type": "file"},
                        {"name": "firmware", "type": "dir"},
                    ]
                ).encode(),
            )
        return HttpResponse(status=200, body=b'{"license": null}')

    budget = NetworkBudget(external_requests_limit=3)
    result = GitHubResourceVerifier(transport=transport).verify(
        github_resource(),
        budget=budget,
        scope=VerificationScope.ALL,
    )

    assert result.license_status == ResourceLicenseStatus.PUBLIC_NO_LICENSE
    assert result.artifacts == ["pcb_files", "readme", "schematic_files", "source_code"]
    assert budget.external_requests_used == 2


def test_generic_shared_file_is_not_promoted_to_open_source():
    verifier = GenericResourceVerifier(
        transport=lambda request, timeout: HttpResponse(status=200)
    )
    resource = ResourceRecord(
        locator="https://pan.baidu.com/s/example",
        host="pan.baidu.com",
        kind=ResourceKind.SHARED_FILE,
    )

    result = verifier.verify(
        resource,
        budget=NetworkBudget(),
        scope=VerificationScope.CORE,
    )

    assert result.access_status == ResourceAccessStatus.ACCESSIBLE
    assert result.license_status == ResourceLicenseStatus.AUTHORIZATION_UNCLEAR


def test_community_link_is_preserved_without_network_request():
    calls = 0

    def transport(request, timeout):
        nonlocal calls
        calls += 1
        return HttpResponse(status=200)

    verifier = GenericResourceVerifier(transport=transport)
    resource = ResourceRecord(
        locator="https://qm.qq.com/example",
        host="qm.qq.com",
        kind=ResourceKind.COMMUNITY,
    )
    budget = NetworkBudget()

    result = verifier.verify(resource, budget=budget, scope=VerificationScope.CORE)

    assert calls == 0
    assert budget.external_requests_used == 0
    assert result.access_status == ResourceAccessStatus.LOGIN_OR_MANUAL

