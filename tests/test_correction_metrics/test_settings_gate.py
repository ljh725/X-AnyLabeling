"""Task 7.1 -- the workflow entry is off by default and costs nothing.

Zero-burden claim: with the setting off, opening the entry must not create a
controller, a SQLite database, a timer or a single event; disabling it at
runtime stops an existing session instead of leaving it recording.

Qt-free where possible: the dialog entry is driven through a fake host and the
runtime applier is exercised without a QApplication.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from anylabeling.views.labeling.settings import schema
from anylabeling.views.labeling.settings.runtime_applier import (
    SettingsRuntimeApplier,
)

from . import synthetic

KEY = "correction_metrics_enabled"


def _host(config=None, **extra):
    statuses = []

    host = SimpleNamespace(
        _config={KEY: False, "language": "en_US"},
        correction_metrics=None,
        actions=SimpleNamespace(),
        status=lambda text, timeout=0: statuses.append(text),
        tr=lambda text: text,
        filename=None,
        output_dir=None,
        canvas=SimpleNamespace(shapes=[]),
        _statuses=statuses,
    )
    if config:
        host._config.update(config)
    for name, value in extra.items():
        setattr(host, name, value)
    return host


def _entry():
    from anylabeling.views.labeling.label_widget import LabelingWidget

    return LabelingWidget.open_correction_metrics


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------
def test_schema_declares_a_disabled_boolean_setting():
    """键存在、是布尔控件、默认 False、归入 General 页。"""
    assert KEY in schema.SETTINGS_KEYS
    field = schema.SETTING_FIELD_MAP[KEY]
    assert field.control == "bool"
    assert field.primary == "General"
    assert KEY in schema.SETTINGS_GENERAL_KEYS
    assert isinstance(field.label, str) and field.label


def test_template_default_is_off():
    """模板默认值是 False（不是缺失、不是空串）。"""
    template = schema.load_template_config()
    assert template[KEY] is False
    assert schema.defaults_map()[KEY] is False


# ---------------------------------------------------------------------------
# 7.1 -- the entry is inert while disabled
# ---------------------------------------------------------------------------
def test_disabled_entry_creates_nothing(tmp_path, monkeypatch):
    """未启用：不建 controller、不建 sqlite、无计时器、不启动会话。"""
    started = []
    monkeypatch.setattr(
        "anylabeling.views.labeling.correction_metrics.controller.start_metrics",
        lambda host: started.append(host),
    )
    metrics_dir = tmp_path / "metrics"
    monkeypatch.setenv("XANYLABELING_METRICS_DIR", str(metrics_dir))
    host = _host()

    assert _entry()(host) is None       # returns quietly

    assert started == []
    assert host.correction_metrics is None
    assert getattr(host, "_metrics_timer", None) is None
    assert host._statuses, "the operator must be told how to enable it"
    text = host._statuses[-1]
    assert "未启用" in text or "disabled" in text.lower()
    assert not metrics_dir.exists() or not list(metrics_dir.iterdir())


def test_disabled_message_is_localised():
    """提示按语言给出（zh/ja/ko + 英文兜底）。"""
    for language, needle in (
        ("zh_CN", "未启用"), ("ja_JP", "無効"), ("ko_KR", "비활성화"),
        ("en_US", "disabled"),
    ):
        host = _host(config={"language": language})
        _entry()(host)
        assert needle in host._statuses[-1], language


def test_enabled_entry_starts_the_session_once(monkeypatch):
    """启用后按现有流程 start_metrics(host)，并显示启动范围。"""
    calls = []
    controller = SimpleNamespace(
        _scope=("D:/data/images", "D:/data/labels"),
        show_panel=lambda: calls.append("panel"),
    )

    def fake_start(host):
        calls.append(host)
        return controller

    monkeypatch.setattr(
        "anylabeling.views.labeling.correction_metrics.controller.start_metrics",
        fake_start,
    )
    host = _host(config={KEY: True})

    _entry()(host)

    assert calls and calls[0] is host
    assert any("Statistics scope" in text for text in host._statuses)


# ---------------------------------------------------------------------------
# runtime applier
# ---------------------------------------------------------------------------
def test_disabling_stops_the_session_and_drops_the_reference():
    """停用：调用 stop() 且引用清空。"""
    stopped = []
    controller = SimpleNamespace(
        stop=lambda: stopped.append(True), enabled=True
    )
    host = SimpleNamespace(correction_metrics=controller)
    applier = SettingsRuntimeApplier(host)

    applier.apply_change(KEY, False)

    assert stopped == [True]
    assert host.correction_metrics is None


def test_disabling_without_a_session_is_a_noop():
    """没有会话时停用不抛异常、不新建任何对象。"""
    host = SimpleNamespace(correction_metrics=None)
    applier = SettingsRuntimeApplier(host)

    applier.apply_change(KEY, False)

    assert host.correction_metrics is None


def test_stop_failure_never_escapes_into_the_settings_dialog():
    """stop() 抛异常时只记录告警，设置保存继续。"""
    class Boom:
        enabled = True

        def stop(self):
            raise RuntimeError("boom")

    host = SimpleNamespace(correction_metrics=Boom())
    applier = SettingsRuntimeApplier(host)

    applier.apply_change(KEY, False)

    assert host.correction_metrics is None


def test_enabling_does_not_create_an_implicit_session():
    """启用本身不创建会话（仍需用户从菜单启动）。"""
    host = SimpleNamespace(correction_metrics=None)
    applier = SettingsRuntimeApplier(host)

    applier.apply_change(KEY, True)

    assert host.correction_metrics is None
