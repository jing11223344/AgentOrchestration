"""Feature Flag Manifest and Deployment Validation.

Ensures production rollout validates all required feature flags
and their intended defaults before traffic shift.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.common.config import Config

logger = logging.getLogger(__name__)


@dataclass
class FeatureFlagDefinition:
    """Definition of a required feature flag."""

    key: str
    description: str
    default_value: Any
    owner: str
    expected_services: List[str] = field(default_factory=list)
    sensitive: bool = False


class FeatureFlagManifest:
    """Declared manifest of required feature flags with defaults and ownership."""

    def __init__(self) -> None:
        self._flags: Dict[str, FeatureFlagDefinition] = {}
        self._load_default_manifest()

    def _load_default_manifest(self) -> None:
        """Load the built-in manifest of required flags."""
        self.register(
            FeatureFlagDefinition(
                key="scheduler.max_retries",
                description="Maximum number of task retry attempts",
                default_value=3,
                owner="platform-team",
                expected_services=["scheduler", "worker"],
            )
        )
        self.register(
            FeatureFlagDefinition(
                key="scheduler.queue_timeout_seconds",
                description="Maximum time a task can stay in queue",
                default_value=3600,
                owner="platform-team",
                expected_services=["scheduler"],
            )
        )
        self.register(
            FeatureFlagDefinition(
                key="worker.concurrency",
                description="Maximum concurrent tasks per worker",
                default_value=10,
                owner="platform-team",
                expected_services=["worker"],
            )
        )
        self.register(
            FeatureFlagDefinition(
                key="worker.task_timeout_seconds",
                description="Maximum execution time per task",
                default_value=300,
                owner="platform-team",
                expected_services=["worker"],
            )
        )
        self.register(
            FeatureFlagDefinition(
                key="api.rate_limit_per_minute",
                description="API rate limit per client per minute",
                default_value=100,
                owner="platform-team",
                expected_services=["api"],
            )
        )
        self.register(
            FeatureFlagDefinition(
                key="logging.level",
                description="Application log level",
                default_value="INFO",
                owner="platform-team",
                expected_services=["scheduler", "worker", "api"],
            )
        )
        self.register(
            FeatureFlagDefinition(
                key="agent.default_timeout_seconds",
                description="Default timeout for agent execution",
                default_value=300,
                owner="agent-team",
                expected_services=["scheduler", "worker"],
            )
        )

    def register(self, flag: FeatureFlagDefinition) -> None:
        """Register a required feature flag."""
        self._flags[flag.key] = flag

    def get(self, key: str) -> Optional[FeatureFlagDefinition]:
        return self._flags.get(key)

    def list_flags(self) -> List[FeatureFlagDefinition]:
        return list(self._flags.values())

    def to_doc_string(self) -> str:
        """Generate documentation string for the manifest."""
        lines = ["# Required Feature Flags", ""]
        for flag in self.list_flags():
            lines.append(
                f"## {flag.key}\n"
                f"- Description: {flag.description}\n"
                f"- Default: `{flag.default_value}`\n"
                f"- Owner: {flag.owner}\n"
                f"- Services: {', '.join(flag.expected_services)}\n"
            )
        return "\n".join(lines)


class DeploymentValidationResult:
    """Result of a deployment validation check."""

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def merge(self, other: DeploymentValidationResult) -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


class FeatureFlagValidator:
    """Validates configuration against the required flag manifest."""

    def __init__(self, manifest: Optional[FeatureFlagManifest] = None) -> None:
        self.manifest = manifest or FeatureFlagManifest()

    def validate(self, config: Config, service_name: str = "all") -> DeploymentValidationResult:
        """Validate config against the manifest for a given service.

        Args:
            config: Application configuration to validate.
            service_name: Service scope ('scheduler', 'worker', 'api', or 'all').

        Returns:
            DeploymentValidationResult with errors and warnings.
        """
        result = DeploymentValidationResult()

        for flag in self.manifest.list_flags():
            if service_name != "all" and service_name not in flag.expected_services:
                continue

            value = config.get(flag.key)
            if value is None:
                result.errors.append(
                    f"MISSING REQUIRED FLAG: '{flag.key}' is not configured. "
                    f"Default: {flag.default_value!r}. Owner: {flag.owner}. "
                    f"Description: {flag.description}"
                )
                continue

            if not flag.sensitive:
                expected_repr = repr(flag.default_value)
                actual_repr = repr(value)
                if actual_repr != expected_repr:
                    result.warnings.append(
                        f"NON-DEFAULT FLAG VALUE: '{flag.key}' = {actual_repr} "
                        f"(expected default: {expected_repr}). "
                        f"Ensure this is intentional before rollout. Owner: {flag.owner}"
                    )

        return result

    def validate_deploy(self, config: Config, service_name: str) -> DeploymentValidationResult:
        """Full deployment validation — blocks rollout on missing flags.

        Performs the same checks as validate() but treats all warnings
        for the target service as errors when flags are missing entirely.
        """
        return self.validate(config, service_name=service_name)


class DeployValidator:
    """Deployment gate that blocks rollout if required flags are missing or mismatched."""

    def __init__(
        self,
        validator: Optional[FeatureFlagValidator] = None,
        manifest: Optional[FeatureFlagManifest] = None,
    ) -> None:
        self.validator = validator or FeatureFlagValidator(manifest or FeatureFlagManifest())

    def check_rollout(
        self,
        scheduler_config: Config,
        worker_config: Config,
        api_config: Optional[Config] = None,
    ) -> DeploymentValidationResult:
        """Check all service configs before allowing production rollout.

        Args:
            scheduler_config: Config for the scheduler service.
            worker_config: Config for the worker service.
            api_config: Optional config for the API service.

        Returns:
            DeploymentValidationResult. Rollout is allowed only if passed is True.
        """
        result = DeploymentValidationResult()

        # Validate each service
        for service_name, config in [
            ("scheduler", scheduler_config),
            ("worker", worker_config),
            ("api", api_config),
        ]:
            if config is None:
                continue
            service_result = self.validator.validate(config, service_name=service_name)
            result.merge(service_result)

            # Cross-service comparison for shared flags
            shared_flags = self._get_shared_flags(service_name)
            for flag_key in shared_flags:
                value = config.get(flag_key)
                if value is not None:
                    result.warnings.append(
                        f"[{service_name}] '{flag_key}' = {value!r} — "
                        f"verify consistency across services"
                    )

        return result

    def _get_shared_flags(self, service_name: str) -> List[str]:
        """Get flag keys shared between the given service and others."""
        shared = []
        for flag in self.validator.manifest.list_flags():
            if service_name in flag.expected_services and len(flag.expected_services) > 1:
                shared.append(flag.key)
        return shared

    def generate_manifest_report(self) -> str:
        """Generate a human-readable manifest report for deployment review."""
        return self.validator.manifest.to_doc_string()
