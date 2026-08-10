"""Regenerate the checked-in sample report from structured fixtures."""

from pathlib import Path

from src.pipeline import SampleResearchRepository


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "sample" / "strategy_report.md"


def main() -> None:
    artifact = SampleResearchRepository().render_current()
    if not artifact.audit.is_valid or not artifact.length_target_met:
        raise RuntimeError("sample report failed citation or length validation")
    OUTPUT.write_text(artifact.markdown, encoding="utf-8")
    print(f"wrote {OUTPUT} ({artifact.character_count} characters)")


if __name__ == "__main__":
    main()
