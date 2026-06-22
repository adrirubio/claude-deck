from pathlib import Path


def test_discover_projects_includes_plain_directory(tmp_path):
    from app.services.project_service import ProjectService

    project_dir = tmp_path / "regular-project"
    project_dir.mkdir()

    discovered = ProjectService(db=None).discover_projects(str(project_dir))

    assert [(project.name, project.path, project.source) for project in discovered] == [
        ("regular-project", str(project_dir), "directory")
    ]


def test_discover_projects_includes_plain_child_directories(tmp_path):
    from app.services.project_service import ProjectService

    child = tmp_path / "child-project"
    hidden = tmp_path / ".hidden-project"
    child.mkdir()
    hidden.mkdir()

    discovered = ProjectService(db=None).discover_projects(str(tmp_path))
    by_path = {project.path: project for project in discovered}

    assert str(tmp_path) in by_path
    assert by_path[str(tmp_path)].source == "directory"
    assert str(child) in by_path
    assert by_path[str(child)].source == "directory"
    assert str(hidden) not in by_path


def test_discover_projects_preserves_configured_source_without_duplicates(tmp_path):
    from app.services.project_service import ProjectService

    project_dir = tmp_path / "configured-project"
    (project_dir / ".claude").mkdir(parents=True)

    discovered = ProjectService(db=None).discover_projects(str(project_dir))
    matching = [project for project in discovered if Path(project.path) == project_dir]

    assert len(matching) == 1
    assert matching[0].source == "configured"


def test_discover_projects_preserves_session_history_source(monkeypatch, tmp_path):
    from app.services import project_service
    from app.services.project_service import ProjectService
    from app.utils.path_utils import convert_path_to_folder_name

    project_dir = tmp_path / "history-project"
    project_dir.mkdir()
    claude_projects_dir = tmp_path / "claude-projects"
    claude_projects_dir.mkdir()
    (claude_projects_dir / convert_path_to_folder_name(str(project_dir))).mkdir()
    monkeypatch.setattr(project_service, "get_claude_projects_dir", lambda: claude_projects_dir)

    discovered = ProjectService(db=None).discover_projects(str(project_dir))
    matching = [project for project in discovered if Path(project.path) == project_dir]

    assert len(matching) == 1
    assert matching[0].source == "session_history"
