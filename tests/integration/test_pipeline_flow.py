"""Integration tests for pipeline flow and persistence wiring."""

from tce.orchestrator.engine import PipelineOrchestrator
from tce.orchestrator.workflows import WORKFLOWS
from tce.services.publishing import (
    FacebookAdapter,
    LinkedInAdapter,
    ManualExportAdapter,
    get_adapter,
)
from tce.services.scheduler import Scheduler

# --- Publishing adapter tests ---


def test_manual_export_adapter():
    """ManualExportAdapter should be the default."""
    adapter = get_adapter("manual")
    assert isinstance(adapter, ManualExportAdapter)


def test_facebook_adapter_stub():
    """Facebook adapter should be available as a stub."""
    adapter = get_adapter("facebook")
    assert isinstance(adapter, FacebookAdapter)


def test_linkedin_adapter_stub():
    """LinkedIn adapter should be available as a stub."""
    adapter = get_adapter("linkedin")
    assert isinstance(adapter, LinkedInAdapter)


def test_unknown_adapter_falls_back():
    """Unknown platform should fall back to manual."""
    adapter = get_adapter("tiktok")
    assert isinstance(adapter, ManualExportAdapter)


# --- Scheduler tests ---


def test_scheduler_default_jobs():
    """Scheduler should have 3 default jobs."""
    s = Scheduler()
    assert "daily_content" in s.jobs
    assert "weekly_planning" in s.jobs
    assert "weekly_learning" in s.jobs


def test_daily_content_weekdays():
    """Daily content should run Mon-Fri."""
    s = Scheduler()
    job = s.jobs["daily_content"]
    assert job.weekdays == [0, 1, 2, 3, 4]


def test_weekly_planning_monday():
    """Weekly planning should run on Monday."""
    s = Scheduler()
    job = s.jobs["weekly_planning"]
    assert job.weekdays == [0]


def test_weekly_learning_friday():
    """Weekly learning should run on Friday."""
    s = Scheduler()
    job = s.jobs["weekly_learning"]
    assert job.weekdays == [4]


def test_scheduler_status():
    """Scheduler status should report all jobs."""
    s = Scheduler()
    status = s.get_status()
    assert "running" in status
    assert "jobs" in status
    assert len(status["jobs"]) == 4  # daily, weekly_planning, weekly_learning, quarterly_nudge


def test_job_to_dict():
    """Job serialization should include all fields."""
    s = Scheduler()
    job_dict = s.jobs["daily_content"].to_dict()
    assert "name" in job_dict
    assert "workflow" in job_dict
    assert "run_time" in job_dict
    assert "weekdays" in job_dict
    assert "next_run" in job_dict


# --- Orchestrator persistence hook tests ---


def test_orchestrator_has_persist_method():
    """Orchestrator should have _persist_step_result method."""
    assert hasattr(PipelineOrchestrator, "_persist_step_result")


def test_orchestrator_has_saver():
    """Orchestrator __init__ should set up a _saver."""
    # Can't instantiate without a real DB session, but check the code path
    import inspect

    source = inspect.getsource(PipelineOrchestrator.__init__)
    assert "_saver" in source
    assert "PipelineResultSaver" in source


# --- Workflow completeness ---


def test_all_workflows_have_valid_agents():
    """Every step in every workflow should reference a registered agent."""
    import tce.agents.corpus_analyst  # noqa: F401
    import tce.agents.creative_director  # noqa: F401
    import tce.agents.cta_agent  # noqa: F401
    import tce.agents.docx_guide_builder  # noqa: F401
    import tce.agents.engagement_scorer  # noqa: F401
    import tce.agents.learning_loop  # noqa: F401
    import tce.agents.pattern_miner  # noqa: F401
    import tce.agents.platform_writer  # noqa: F401
    import tce.agents.qa_agent  # noqa: F401
    import tce.agents.research_agent  # noqa: F401
    import tce.agents.story_strategist  # noqa: F401
    import tce.agents.trend_scout  # noqa: F401
    from tce.agents.registry import agent_registry

    registry = agent_registry()
    for wf_name, steps in WORKFLOWS.items():
        for step in steps:
            assert step.agent_name in registry, (
                f"Workflow '{wf_name}' references unregistered agent "
                f"'{step.agent_name}'"
            )
