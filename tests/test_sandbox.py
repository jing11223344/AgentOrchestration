"""Tests for AgentSandbox — path validation and containment."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from src.agent.sandbox import AgentSandbox


class TestAgentSandbox:
    def test_get_path_returns_valid_path(self):
        """get_path returns the sandbox path when it exists."""
        with tempfile.TemporaryDirectory() as tmp:
            sb = AgentSandbox(base_path=tmp)
            sb.create("agent-1")
            p = sb.get_path("agent-1")
            assert p is not None
            assert p.exists()
            assert str(p).startswith(tmp)

    def test_get_path_returns_none_for_unknown_agent(self):
        """get_path returns None for an agent_id that was never created."""
        with tempfile.TemporaryDirectory() as tmp:
            sb = AgentSandbox(base_path=tmp)
            p = sb.get_path("nonexistent")
            assert p is None

    def test_get_path_returns_none_for_deleted_path(self):
        """get_path returns None when the sandbox directory was deleted externally."""
        with tempfile.TemporaryDirectory() as tmp:
            sb = AgentSandbox(base_path=tmp)
            sb.create("agent-1")
            p = sb.get_path("agent-1")
            assert p is not None
            # Delete the directory externally
            shutil.rmtree(p)
            assert not p.exists()
            # get_path should now return None
            p2 = sb.get_path("agent-1")
            assert p2 is None

    def test_get_path_returns_none_for_containment_violation(self):
        """get_path returns None if the stored path is outside base_path."""
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tempfile.mkdtemp())
            sb = AgentSandbox(base_path=tmp)
            # Manually inject a path outside the sandbox
            sb._sandboxes["rogue"] = outside
            p = sb.get_path("rogue")
            assert p is None
            # Verify it was removed from tracking
            assert "rogue" not in sb._sandboxes
            outside.rmdir()

    def test_get_path_handles_symlink_outside(self):
        """get_path rejects symlinks that resolve outside base_path."""
        with tempfile.TemporaryDirectory() as tmp:
            outside_file = Path(tempfile.mkstemp()[1])
            sb = AgentSandbox(base_path=tmp)
            sb.create("agent-1")
            sandbox_path = sb.get_path("agent-1")
            # Create a symlink inside sandbox pointing outside
            link_path = sandbox_path / "escape"
            link_path.symlink_to(outside_file)
            # Direct access via symlink should fail containment
            sb._sandboxes["escape-artist"] = link_path
            p = sb.get_path("escape-artist")
            assert p is None, "Symlink escaping sandbox should be rejected"
            outside_file.unlink()

    def test_destroy_after_external_deletion(self):
        """destroy handles gracefully when directory was already deleted."""
        with tempfile.TemporaryDirectory() as tmp:
            sb = AgentSandbox(base_path=tmp)
            sb.create("agent-1")
            shutil.rmtree(sb.get_path("agent-1"))
            result = sb.destroy("agent-1")
            assert result is False
