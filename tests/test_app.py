from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_streamlit_workbench_renders() -> None:
    app = AppTest.from_file(ROOT / "app.py").run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "企业战略研究助手"
    assert app.segmented_control[0].value == "样例模式"
    assert app.sidebar.subheader[0].value == "运行设置"
    assert app.sidebar.button[0].label == "测试豆包连接"
    assert app.sidebar.button[0].disabled
    assert any(item.value == "研究参数" for item in app.subheader)


def test_doubao_connection_button_requires_realtime_key() -> None:
    app = AppTest.from_file(ROOT / "app.py").run(timeout=10)

    app.segmented_control[0].set_value("实时模式").run(timeout=10)
    assert app.sidebar.button[0].disabled

    app.sidebar.text_input[0].set_value("not-a-real-key").run(timeout=10)
    assert not app.sidebar.button[0].disabled
