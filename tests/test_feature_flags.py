"""Tests for Feature Flag validation and deployment gate."""

import pytest
from src.common.config import Config
from src.common.feature_flags import (
    FeatureFlagDefinition,
    FeatureFlagManifest,
    FeatureFlagValidator,
    DeployValidator,
    DeploymentValidationResult,
)


class TestFeatureFlagManifest:
    def test_default_manifest_loaded(self):
        manifest = FeatureFlagManifest()
        flags = manifest.list_flags()
        assert len(flags) > 0
        # Check key flags exist
        assert manifest.get("scheduler.max_retries") is not None
        assert manifest.get("worker.concurrency") is not None
        assert manifest.get("logging.level") is not None

    def test_register_custom_flag(self):
        manifest = FeatureFlagManifest()
        custom = FeatureFlagDefinition(
            key="custom.feature_x",
            description="My custom feature",
            default_value=False,
            owner="me",
        )
        manifest.register(custom)
        assert manifest.get("custom.feature_x") == custom

    def test_to_doc_string(self):
        manifest = FeatureFlagManifest()
        doc = manifest.to_doc_string()
        assert "Required Feature Flags" in doc
        assert "scheduler.max_retries" in doc
        assert "platform-team" in doc


class TestFeatureFlagValidator:
    def test_missing_flag_returns_error(self):
        manifest = FeatureFlagManifest()
        validator = FeatureFlagValidator(manifest)
        config = Config()
        result = validator.validate(config)
        assert not result.passed
        assert any("MISSING" in e for e in result.errors)

    def test_configured_flag_passes(self):
        manifest = FeatureFlagManifest()
        validator = FeatureFlagValidator(manifest)
        config = Config()
        config.set("scheduler.max_retries", 3)
        config.set("scheduler.queue_timeout_seconds", 3600)
        config.set("worker.concurrency", 10)
        config.set("worker.task_timeout_seconds", 300)
        config.set("api.rate_limit_per_minute", 100)
        config.set("logging.level", "INFO")
        config.set("agent.default_timeout_seconds", 300)
        result = validator.validate(config)
        # May have warnings about flag consistency but no missing errors
        missing_errors = [e for e in result.errors if "MISSING" in e]
        assert len(missing_errors) == 0

    def test_service_scoped_validation(self):
        manifest = FeatureFlagManifest()
        validator = FeatureFlagValidator(manifest)
        config = Config()
        config.set("worker.concurrency", 10)
        config.set("worker.task_timeout_seconds", 300)

        # Scheduler-specific flag missing
        scheduler_result = validator.validate(config, service_name="scheduler")
        assert not scheduler_result.passed
        assert any("scheduler.max_retries" in e for e in scheduler_result.errors)

        # Worker-specific flags present
        worker_result = validator.validate(config, service_name="worker")
        worker_missing = [e for e in worker_result.errors if "MISSING" in e]
        # Worker flags are present
        assert all("worker" not in e for e in worker_missing)

    def test_non_default_value_warning(self):
        manifest = FeatureFlagManifest()
        validator = FeatureFlagValidator(manifest)
        config = Config()
        config.set("scheduler.max_retries", 3)
        config.set("scheduler.queue_timeout_seconds", 3600)
        config.set("worker.concurrency", 10)
        config.set("worker.task_timeout_seconds", 300)
        config.set("api.rate_limit_per_minute", 100)
        config.set("logging.level", "DEBUG")  # Non-default
        config.set("agent.default_timeout_seconds", 300)
        result = validator.validate(config)
        warnings = [w for w in result.warnings if "NON-DEFAULT" in w]
        assert len(warnings) >= 1
        assert "logging.level" in warnings[0]


class TestDeployValidator:
    def test_rollout_blocked_on_missing_flags(self):
        manifest = FeatureFlagManifest()
        deploy = DeployValidator(manifest=manifest)

        scheduler_cfg = Config()
        worker_cfg = Config()

        result = deploy.check_rollout(scheduler_cfg, worker_cfg)
        assert not result.passed
        assert len(result.errors) > 0

    def test_rollout_allowed_with_all_flags(self):
        manifest = FeatureFlagManifest()
        deploy = DeployValidator(manifest=manifest)

        scheduler_cfg = Config()
        worker_cfg = Config()
        api_cfg = Config()

        for cfg in [scheduler_cfg, worker_cfg]:
            cfg.set("scheduler.max_retries", 3)
            cfg.set("scheduler.queue_timeout_seconds", 3600)
            cfg.set("worker.concurrency", 10)
            cfg.set("worker.task_timeout_seconds", 300)
            cfg.set("api.rate_limit_per_minute", 100)
            cfg.set("logging.level", "INFO")
            cfg.set("agent.default_timeout_seconds", 300)

        api_cfg.set("api.rate_limit_per_minute", 100)
        api_cfg.set("logging.level", "INFO")

        result = deploy.check_rollout(scheduler_cfg, worker_cfg, api_cfg)
        assert result.passed

    def test_cross_service_comparison(self):
        manifest = FeatureFlagManifest()
        deploy = DeployValidator(manifest=manifest)

        scheduler_cfg = Config()
        worker_cfg = Config()

        for cfg in [scheduler_cfg, worker_cfg]:
            cfg.set("scheduler.max_retries", 3)
            cfg.set("scheduler.queue_timeout_seconds", 3600)
            cfg.set("worker.concurrency", 10)
            cfg.set("worker.task_timeout_seconds", 300)
            cfg.set("api.rate_limit_per_minute", 100)
            cfg.set("logging.level", "INFO")
            cfg.set("agent.default_timeout_seconds", 300)

        result = deploy.check_rollout(scheduler_cfg, worker_cfg)
        assert result.passed


class TestDeploymentValidationResult:
    def test_merge(self):
        r1 = DeploymentValidationResult()
        r1.errors.append("error1")
        r2 = DeploymentValidationResult()
        r2.errors.append("error2")
        r2.warnings.append("warn1")
        r1.merge(r2)
        assert len(r1.errors) == 2
        assert len(r1.warnings) == 1

    def test_passed_without_errors(self):
        r = DeploymentValidationResult()
        assert r.passed
        r.errors.append("something")
        assert not r.passed
