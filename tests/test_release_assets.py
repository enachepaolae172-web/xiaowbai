import re
from pathlib import Path

from PIL import Image

from src.config import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs" / "assets"


def test_release_version_and_public_files_exist() -> None:
    assert APP_VERSION == "v0.1.0"
    for relative_path in (
        "README.md",
        "README.zh-CN.md",
        "LICENSE",
        "SECURITY.md",
        "CHANGELOG.md",
        "runtime.txt",
        ".github/workflows/tests.yml",
        "docs/architecture.md",
        "docs/deployment.md",
        "docs/assets/demo.gif",
        "docs/assets/workbench-desktop.png",
        "docs/assets/workbench-mobile.png",
    ):
        path = ROOT / relative_path
        assert path.is_file() and path.stat().st_size > 0, relative_path


def test_local_markdown_links_resolve() -> None:
    documents = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        ROOT / "docs" / "README.md",
    ]
    for document in documents:
        content = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", content):
            if target.startswith(("http://", "https://", "#", "<")):
                continue
            resolved = (document.parent / target).resolve()
            assert resolved.exists(), f"broken link in {document.name}: {target}"


def test_release_images_have_verified_dimensions() -> None:
    with Image.open(ASSETS / "workbench-desktop.png") as desktop:
        assert desktop.size == (1440, 1000)
    with Image.open(ASSETS / "workbench-mobile.png") as mobile:
        assert mobile.size == (390, 844)


def test_demo_gif_is_one_minute_and_small_enough_for_readme() -> None:
    path = ASSETS / "demo.gif"
    with Image.open(path) as demo:
        frame_count = getattr(demo, "n_frames", 1)
        durations = []
        for index in range(frame_count):
            demo.seek(index)
            durations.append(int(demo.info.get("duration", 0)))

    assert frame_count == 6
    assert sum(durations) >= 60_000
    assert path.stat().st_size < 2_000_000


def test_runtime_and_workflow_are_release_safe() -> None:
    assert (ROOT / "runtime.txt").read_text(encoding="utf-8").strip() == "python-3.12"
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )
    assert "python -m pytest" in workflow
    assert "secrets." not in workflow
