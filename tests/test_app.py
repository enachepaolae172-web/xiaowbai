from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def button_by_label(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def test_sample_mode_renders_complete_research_workspace() -> None:
    app = AppTest.from_file(ROOT / "app.py").run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "企业战略研究助手"
    assert app.segmented_control[0].value == "样例模式"
    assert app.sidebar.subheader[0].value == "运行设置"
    assert button_by_label(app, "测试豆包连接").disabled
    assert not button_by_label(app, "恢复预置样例").disabled
    assert any("样例报告已预加载" in item.value for item in app.caption)
    assert [item.label for item in app.tabs] == [
        "核心结论",
        "宏观与市场",
        "行业结构",
        "战略建议",
        "来源与未知项",
    ]
    assert len(app.download_button) == 1
    assert app.download_button[0].label == "下载 Markdown"
    assert [item.label for item in app.metric] == [
        "证据来源",
        "启用扩展模块",
        "报告字符",
        "引用核验",
    ]


def test_restoring_sample_shows_visible_confirmation() -> None:
    app = AppTest.from_file(ROOT / "app.py").run(timeout=10)

    button_by_label(app, "恢复预置样例").click().run(timeout=10)

    assert not app.exception
    assert any("预置样例已恢复" in item.value for item in app.success)


def test_realtime_mode_requires_both_keys_before_research() -> None:
    app = AppTest.from_file(ROOT / "app.py").run(timeout=10)

    app.segmented_control[0].set_value("实时模式").run(timeout=10)
    assert button_by_label(app, "开始研究").disabled
    assert button_by_label(app, "测试豆包连接").disabled

    app.sidebar.text_input[0].set_value("not-a-real-doubao-key").run(timeout=10)
    assert button_by_label(app, "开始研究").disabled
    assert not button_by_label(app, "测试豆包连接").disabled

    app.sidebar.text_input[1].set_value("not-a-real-tavily-key").run(timeout=10)
    assert not button_by_label(app, "开始研究").disabled
