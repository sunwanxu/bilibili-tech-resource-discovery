import inspect

from bhka.v1 import evidence_reader, resource_verification, search_session
from bhka.v1.errors import (
    CandidateReadError,
    DiscoveryFailure,
    PlatformCircuitBreak,
    ResourceVerificationFailure,
)
from bhka.v1.pipeline import (
    CandidateReadError as LegacyCandidateReadError,
)
from bhka.v1.pipeline import (
    DiscoveryFailure as LegacyDiscoveryFailure,
)
from bhka.v1.pipeline import (
    PlatformCircuitBreak as LegacyPlatformCircuitBreak,
)
from bhka.v1.pipeline import (
    ResourceVerificationFailure as LegacyResourceVerificationFailure,
)
from bhka.v1.ports import QueryPlanner


def test_adapters_do_not_depend_on_pipeline_module():
    for module in (evidence_reader, resource_verification, search_session):
        assert "from .pipeline import" not in inspect.getsource(module)


def test_shared_failures_keep_legacy_pipeline_import_compatibility():
    assert LegacyCandidateReadError is CandidateReadError
    assert LegacyDiscoveryFailure is DiscoveryFailure
    assert LegacyPlatformCircuitBreak is PlatformCircuitBreak
    assert LegacyResourceVerificationFailure is ResourceVerificationFailure


def test_query_planner_is_owned_by_ports_module():
    assert QueryPlanner.__module__ == "bhka.v1.ports"
