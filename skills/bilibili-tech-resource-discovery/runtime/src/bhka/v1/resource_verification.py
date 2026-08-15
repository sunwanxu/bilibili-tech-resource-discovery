from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .contracts import (
    NetworkBudget,
    ResourceAccessStatus,
    ResourceKind,
    ResourceLicenseStatus,
    ResourceRecord,
    VerificationScope,
)
from .pipeline import ResourceVerificationFailure


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes = b""
    final_url: str = ""
    content_type: str = ""


class HttpTransport(Protocol):
    def __call__(self, request: Request, timeout_seconds: int) -> HttpResponse: ...


def _default_transport(request: Request, timeout_seconds: int) -> HttpResponse:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return HttpResponse(
                status=response.status,
                body=response.read(1_000_000),
                final_url=response.url,
                content_type=response.headers.get("Content-Type", ""),
            )
    except HTTPError as exc:
        return HttpResponse(
            status=exc.code,
            body=exc.read(64_000),
            final_url=exc.url,
            content_type=exc.headers.get("Content-Type", "") if exc.headers else "",
        )


class ResourceVerificationError(ResourceVerificationFailure):
    pass


def _artifact_categories(rows: list[dict[str, Any]]) -> list[str]:
    categories = set()
    for row in rows:
        name = str(row.get("name") or "").casefold()
        kind = str(row.get("type") or "").casefold()
        if name in {"readme", "readme.md", "readme.rst"}:
            categories.add("readme")
        if name.startswith(("license", "copying")):
            categories.add("license_file")
        if name.endswith((".kicad_pcb", ".pcbdoc", ".brd")) or "gerber" in name:
            categories.add("pcb_files")
        if name.endswith((".kicad_sch", ".schdoc", ".sch")):
            categories.add("schematic_files")
        if name.endswith((".step", ".stp", ".3mf", ".stl")):
            categories.add("mechanical_files")
        if name in {"src", "source", "firmware", "software", "code"} and kind == "dir":
            categories.add("source_code")
        if name in {"docs", "doc", "documentation"} and kind == "dir":
            categories.add("documentation")
    return sorted(categories)


class GitHubResourceVerifier:
    def __init__(
        self,
        *,
        token: str | None = None,
        timeout_seconds: int = 15,
        transport: HttpTransport | None = None,
    ):
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.transport = transport or _default_transport

    def _get_json(self, url: str, budget: NetworkBudget) -> tuple[int, Any]:
        budget.consume_external()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "bhka-v1-resource-verifier",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = self.transport(Request(url, headers=headers), self.timeout_seconds)
        try:
            payload = json.loads(response.body) if response.body else None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResourceVerificationError("invalid_response", "GitHub returned invalid JSON") from exc
        return response.status, payload

    def verify(
        self,
        resource: ResourceRecord,
        *,
        budget: NetworkBudget,
        scope: VerificationScope,
    ) -> ResourceRecord:
        result = resource.model_copy(deep=True)
        root = result.repository_root
        if root is None or urlparse(root).hostname != "github.com":
            raise ValueError("GitHub verifier requires a canonical github.com repository root")
        if not budget.allow_external():
            result.verification_notes.append("External verification budget exhausted")
            return result
        owner, repository = [segment for segment in urlparse(root).path.split("/") if segment][:2]
        api_root = f"https://api.github.com/repos/{quote(owner)}/{quote(repository)}"
        try:
            status, payload = self._get_json(api_root, budget)
        except (TimeoutError, URLError) as exc:
            raise ResourceVerificationError("network_error", "GitHub could not be reached") from exc
        if status in {404, 410}:
            result.access_status = ResourceAccessStatus.DEAD
            result.license_status = ResourceLicenseStatus.DEAD
            result.verification_notes.append("GitHub repository was not found")
            return result
        if status in {401, 403}:
            result.access_status = ResourceAccessStatus.LOGIN_OR_MANUAL
            result.license_status = ResourceLicenseStatus.LOGIN_OR_MANUAL
            result.verification_notes.append("GitHub requires authentication or rate limit recovery")
            return result
        if status != 200 or not isinstance(payload, dict):
            result.access_status = ResourceAccessStatus.BLOCKED
            result.verification_notes.append(f"GitHub returned HTTP {status}")
            return result

        result.access_status = ResourceAccessStatus.ACCESSIBLE
        license_payload = payload.get("license") or {}
        spdx = str(license_payload.get("spdx_id") or "").strip()
        if spdx and spdx.casefold() not in {"noassertion", "other"}:
            result.license_status = ResourceLicenseStatus.VERIFIED
            result.license_name = spdx
            result.license_scope = f"repository:{owner}/{repository}"
            result.verification_notes.append("License identified by GitHub repository metadata")
        else:
            result.license_status = ResourceLicenseStatus.PUBLIC_NO_LICENSE
            result.license_scope = f"repository:{owner}/{repository}"
            result.verification_notes.append("Public repository; no verified SPDX license")
        if payload.get("archived"):
            result.verification_notes.append("Repository is archived")
        if payload.get("disabled"):
            result.verification_notes.append("Repository is disabled")

        if scope == VerificationScope.ALL and budget.allow_external():
            try:
                contents_status, contents = self._get_json(f"{api_root}/contents", budget)
            except (TimeoutError, URLError, ResourceVerificationError):
                result.verification_notes.append("Root artifact inspection failed")
            else:
                if contents_status == 200 and isinstance(contents, list):
                    result.artifacts = _artifact_categories(
                        [row for row in contents if isinstance(row, dict)]
                    )
                else:
                    result.verification_notes.append(
                        f"Root artifact inspection returned HTTP {contents_status}"
                    )
        return result


class GenericResourceVerifier:
    def __init__(
        self,
        *,
        timeout_seconds: int = 15,
        transport: HttpTransport | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.transport = transport or _default_transport

    def verify(
        self,
        resource: ResourceRecord,
        *,
        budget: NetworkBudget,
        scope: VerificationScope,
    ) -> ResourceRecord:
        result = resource.model_copy(deep=True)
        if result.kind == ResourceKind.COMMUNITY:
            result.access_status = ResourceAccessStatus.LOGIN_OR_MANUAL
            result.license_status = ResourceLicenseStatus.LOGIN_OR_MANUAL
            result.verification_notes.append("Community link requires user interaction")
            return result
        if not budget.allow_external():
            result.verification_notes.append("External verification budget exhausted")
            return result
        budget.consume_external()
        request = Request(
            result.locator,
            headers={
                "User-Agent": "Mozilla/5.0 bhka-v1-resource-verifier",
                "Range": "bytes=0-65535",
            },
        )
        try:
            response = self.transport(request, self.timeout_seconds)
        except (TimeoutError, URLError) as exc:
            raise ResourceVerificationError(
                "network_error", "Resource host could not be reached"
            ) from exc
        if response.status in {404, 410}:
            result.access_status = ResourceAccessStatus.DEAD
            result.license_status = ResourceLicenseStatus.DEAD
        elif response.status in {401, 403}:
            result.access_status = ResourceAccessStatus.LOGIN_OR_MANUAL
            result.license_status = ResourceLicenseStatus.LOGIN_OR_MANUAL
        elif 200 <= response.status < 400:
            result.access_status = ResourceAccessStatus.ACCESSIBLE
            if result.kind == ResourceKind.REPOSITORY:
                result.license_status = ResourceLicenseStatus.PUBLIC_NO_LICENSE
            elif result.kind in {ResourceKind.SHARED_FILE, ResourceKind.PCB_PROJECT}:
                result.license_status = ResourceLicenseStatus.AUTHORIZATION_UNCLEAR
            else:
                result.license_status = ResourceLicenseStatus.NO_EVIDENCE
        else:
            result.access_status = ResourceAccessStatus.BLOCKED
        result.verification_notes.append(f"Host returned HTTP {response.status}")
        return result


class ResourceVerifierRouter:
    def __init__(
        self,
        *,
        github: GitHubResourceVerifier | None = None,
        generic: GenericResourceVerifier | None = None,
    ):
        self.github = github or GitHubResourceVerifier()
        self.generic = generic or GenericResourceVerifier()

    def verify(
        self,
        resource: ResourceRecord,
        *,
        budget: NetworkBudget,
        scope: VerificationScope,
    ) -> ResourceRecord:
        if resource.repository_root and urlparse(resource.repository_root).hostname == "github.com":
            return self.github.verify(resource, budget=budget, scope=scope)
        return self.generic.verify(resource, budget=budget, scope=scope)
