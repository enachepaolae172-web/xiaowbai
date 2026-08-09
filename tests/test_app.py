from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_workbench_renders() -> None:
    app = AppTest.from_file(ROOT / "app.py").run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "企业战略研究助手"
    assert app.segmented_control[0].value == "样例模式"
    assert app.sidebar.subheader[0].value == "运行设置"
    assert any(item.value == "研究参数" for item in app.subheader)
