import pytest
from src.sdk.decorators import task, agent, on_event


class TestTaskDecorator:
    def test_valid_timeout(self):
        """Valid timeout values should work."""
        @task(timeout=30)
        async def my_task():
            return "done"
        assert my_task.__task_config__["timeout"] == 30

    def test_default_timeout(self):
        """Default timeout should be 300."""
        @task()
        async def my_task():
            return "done"
        assert my_task.__task_config__["timeout"] == 300

    def test_zero_timeout_raises(self):
        """timeout=0 should raise ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            @task(timeout=0)
            async def my_task():
                pass

    def test_negative_timeout_raises(self):
        """Negative timeout should raise ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            @task(timeout=-1)
            async def my_task():
                pass

    def test_none_timeout_raises(self):
        """None timeout should raise ValueError."""
        with pytest.raises(ValueError, match="timeout must be a positive number"):
            @task(timeout=None)  # type: ignore
            async def my_task():
                pass

    def test_valid_retries(self):
        """Valid retries values should work."""
        @task(retries=3)
        async def my_task():
            return "done"
        assert my_task.__task_config__["retries"] == 3

    def test_default_retries(self):
        """Default retries should be 0."""
        @task()
        async def my_task():
            return "done"
        assert my_task.__task_config__["retries"] == 0

    def test_negative_retries_raises(self):
        """Negative retries should raise ValueError."""
        with pytest.raises(ValueError, match="retries must be a non-negative integer"):
            @task(retries=-1)
            async def my_task():
                pass

    def test_task_config_values(self):
        """Task config should store all values correctly."""
        @task(name="test-task", retries=2, timeout=60)
        async def my_task():
            return "done"
        config = my_task.__task_config__
        assert config["name"] == "test-task"
        assert config["retries"] == 2
        assert config["timeout"] == 60

    def test_task_name_defaults_to_func_name(self):
        """Task name should default to function name."""
        @task()
        async def my_custom_task():
            return "done"
        assert my_custom_task.__task_config__["name"] == "my_custom_task"


class TestAgentDecorator:
    def test_agent_config(self):
        """Agent decorator should set config correctly."""
        @agent(name="TestAgent", version="2.0.0", description="A test agent")
        class MyAgent:
            pass
        config = MyAgent.__agent_config__
        assert config["name"] == "TestAgent"
        assert config["version"] == "2.0.0"
        assert config["description"] == "A test agent"

    def test_agent_defaults(self):
        """Agent decorator should use default values."""
        @agent(name="DefaultAgent")
        class MyAgent:
            pass
        config = MyAgent.__agent_config__
        assert config["version"] == "1.0.0"
        assert config["description"] == ""


class TestOnEventDecorator:
    def test_event_handler(self):
        """on_event should set event type."""
        @on_event("task.completed")
        async def handler():
            pass
        assert handler.__event_handler__ == "task.completed"
