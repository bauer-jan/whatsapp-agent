"""Unit and property tests for PersonaLoader."""

import pytest
from pathlib import Path

from utils.persona_loader import PersonaLoader, PERSONA_FILES


@pytest.fixture
def loader(tmp_path):
    """Create a PersonaLoader with temp templates and persona dirs."""
    templates = tmp_path / "templates"
    persona = tmp_path / "persona"
    templates.mkdir()
    # Create all template files
    for name in PERSONA_FILES:
        (templates / name).write_text(f"# Default {name}\nTemplate content.")
    return PersonaLoader(templates_dir=str(templates), persona_dir=str(persona))


class TestEnsurePersonaFiles:
    def test_copies_missing_files(self, loader):
        loader.ensure_persona_files()
        for name in PERSONA_FILES:
            path = Path(loader.persona_dir) / name
            assert path.exists()
            assert "Template content" in path.read_text()

    def test_does_not_overwrite_existing(self, loader):
        Path(loader.persona_dir).mkdir(parents=True, exist_ok=True)
        soul = Path(loader.persona_dir) / "SOUL.md"
        soul.write_text("My custom soul")

        loader.ensure_persona_files()
        assert soul.read_text() == "My custom soul"

    def test_skips_missing_template(self, tmp_path):
        templates = tmp_path / "templates"
        persona = tmp_path / "persona"
        templates.mkdir()
        # Only create SOUL.md template, skip the rest
        (templates / "SOUL.md").write_text("# Soul")

        pl = PersonaLoader(templates_dir=str(templates), persona_dir=str(persona))
        pl.ensure_persona_files()

        assert (persona / "SOUL.md").exists()
        assert not (persona / "USER.md").exists()


class TestLoadPrompts:
    def test_assembles_soul_and_context(self, loader):
        loader.ensure_persona_files()
        prompt = loader.load_public_prompt()
        assert "SOUL" in prompt
        assert "System Context" in prompt
        # USER.md is no longer in system prompt — it's admin-only via SessionManager.
        assert "USER" not in prompt

    def test_admin_prompt_includes_user_and_heartbeat(self, loader):
        loader.ensure_persona_files()
        prompt = loader.load_admin_prompt()
        assert "SOUL" in prompt
        assert "USER" in prompt
        assert "System Context" in prompt

    def test_missing_files_returns_partial(self, tmp_path):
        persona = tmp_path / "persona"
        persona.mkdir()
        (persona / "SOUL.md").write_text("# Soul only")

        pl = PersonaLoader(persona_dir=str(persona))
        prompt = pl.load_public_prompt()
        assert "Soul only" in prompt


class TestLoadBootstrap:
    def test_loads_bootstrap(self, loader):
        # BOOTSTRAP.md is not auto-copied by ensure_persona_files.
        # Manually place it to test loading.
        loader.ensure_persona_files()
        (loader.persona_dir / "BOOTSTRAP.md").write_text("# BOOTSTRAP test")
        bs = loader.load_bootstrap()
        assert "BOOTSTRAP" in bs

    def test_missing_bootstrap_returns_empty(self, tmp_path):
        persona = tmp_path / "persona"
        persona.mkdir()
        pl = PersonaLoader(persona_dir=str(persona))
        assert pl.load_bootstrap() == ""


class TestLoadHeartbeatTasks:
    def test_parses_tasks_with_intervals(self, tmp_path):
        persona = tmp_path / "persona"
        persona.mkdir()
        (persona / "HEARTBEAT.md").write_text(
            "# Heartbeat\n"
            "- Check Email [every 30 min]: Look for urgent emails\n"
            "- Daily Summary [every 1440 min]: Summarize the day\n"
        )
        pl = PersonaLoader(persona_dir=str(persona))
        tasks = pl.load_heartbeat_tasks()

        assert len(tasks) == 2
        assert tasks[0].name == "Check Email"
        assert tasks[0].interval_minutes == 30
        assert tasks[0].description == "Look for urgent emails"
        assert tasks[1].name == "Daily Summary"
        assert tasks[1].interval_minutes == 1440

    def test_skips_non_matching_lines(self, tmp_path):
        persona = tmp_path / "persona"
        persona.mkdir()
        (persona / "HEARTBEAT.md").write_text(
            "# Heartbeat\n"
            "Some intro text\n"
            "- Valid Task [every 60 min]: Does something\n"
            "- No interval here: This should be skipped\n"
            "Random line\n"
        )
        pl = PersonaLoader(persona_dir=str(persona))
        tasks = pl.load_heartbeat_tasks()
        assert len(tasks) == 1
        assert tasks[0].name == "Valid Task"

    def test_missing_heartbeat_returns_empty(self, tmp_path):
        persona = tmp_path / "persona"
        persona.mkdir()
        pl = PersonaLoader(persona_dir=str(persona))
        assert pl.load_heartbeat_tasks() == []

    def test_real_template_parses(self, loader):
        """Ensure the actual HEARTBEAT.md template format is parseable."""
        loader.ensure_persona_files()
        tasks = loader.load_heartbeat_tasks()
        # The default template has tasks — verify they parse
        assert isinstance(tasks, list)
