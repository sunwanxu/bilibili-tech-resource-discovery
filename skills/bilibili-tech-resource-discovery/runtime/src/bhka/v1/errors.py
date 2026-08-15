"""Shared application failures used by ports, adapters, and orchestration."""

from __future__ import annotations


class CodedFailure(RuntimeError):
    """Failure with a stable machine-readable code and optional safe detail."""

    def __init__(self, code: str, detail: str | None = None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class PlatformCircuitBreak(CodedFailure):
    """Signal after which no new Bilibili request is allowed in the run."""


class CandidateReadError(CodedFailure):
    """Bounded failure for one candidate that must not abort the full run."""


class DiscoveryFailure(CodedFailure):
    """Bounded failure of one discovery adapter."""


class ResourceVerificationFailure(CodedFailure):
    """Bounded failure while checking one external resource."""
