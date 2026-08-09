from pathlib import Path

from src.config import APP_NAME, APP_VERSION, DEFAULT_ARK_BASE_URL


ROOT = Path(__file__).resolve().parents[1]


def test_application_metadata() -> None:
    assert APP_NAME == "Enterprise AI Strategy Research Agent"
    assert APP_VERSION.startswith("v0.1.0")
    assert DEFAULT_ARK_BASE_URL.startswith("https://")


def test_required_project_paths_exist() -> None:
    required_paths = [
        ROOT / "app.py",
        ROOT / "requirements.txt",
        ROOT / ".env.example",
        ROOT / "prompts",
        ROOT / "data" / "sample",
        ROOT / "docs",
    ]
    assert all(path.exists() for path in required_paths)


def test_secret_files_are_ignored() -> None:
    ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in ignore_rules
    assert ".streamlit/secrets.toml" in ignore_rules
