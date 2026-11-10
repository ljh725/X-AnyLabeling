"""Tasks 4.1 + 4.2 -- optional prediction provenance and single-image apply.

Qt-free: the model manager is inspected through its pure helpers, and the
controller is driven with plain namespace objects.

Spec points: BASE-2/BASE-3 (unknown source stays unknown, additive vs
replacement boundaries), EVT-5 (AI application is not a manual creation),
ORIGIN allow-list (no keys, auth headers or credentialed URLs).
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from anylabeling.services.auto_labeling.types import AutoLabelingResult
from anylabeling.services.correction_metrics.core import ORIGIN_FIELDS
from anylabeling.views.labeling.correction_metrics.controller import (
    CorrectionMetricsController,
)

from . import synthetic

SECRET_KEYS = ("api_key", "apikey", "authorization", "auth", "token",
               "secret", "password", "endpoint", "base_url")


# ---------------------------------------------------------------------------
# 4.1 -- the result object stays backward compatible
# ---------------------------------------------------------------------------
def test_legacy_constructor_still_works_and_starts_without_provenance():
    """旧式构造 `AutoLabelingResult(shapes, replace=False)` 行为不变、来源为空。"""
    result = AutoLabelingResult([], replace=False)

    assert result.shapes == []
    assert result.replace is False
    assert result.description == ""
    assert result.image_path is None
    assert result.tags is None and result.flags is None
    assert result.provenance is None


def test_provenance_is_optional_and_never_implicit():
    """没有来源时必须是 None/空，不能伪造一个。"""
    explicit = AutoLabelingResult([{"label": "cat"}], replace=True,
                                  provenance={"run_id": "abc"})
    assert explicit.provenance == {"run_id": "abc"}
    # A positional legacy call still lands in `shapes`, not in `provenance`.
    positional = AutoLabelingResult([{"label": "cat"}], False)
    assert positional.replace is False and positional.provenance is None


# ---------------------------------------------------------------------------
# 4.1 -- collection only keeps documented fields
# ---------------------------------------------------------------------------
def _config(**overrides):
    model = SimpleNamespace(
        current_model_id="yolov8n", conf_thres=0.25, iou_thres=0.45,
        classes=["cat", "dog"], api_key="sk-should-never-appear",
        authorization="Bearer secret", token="tok",
        endpoint="https://user:pw@host/infer",
    )
    config = {
        "type": "yolov8", "model": model,
        "conf_threshold": 0.25, "iou_threshold": 0.45,
        "api_key": "sk-config-secret", "authorization": "Bearer cfg-secret",
        "base_url": "https://user:pw@host", "token": "cfg-token",
    }
    config.update(overrides)
    return config


def _source(config=None, prompt="cat, dog"):
    from anylabeling.services.auto_labeling.model_manager import (
        _prediction_source,
    )

    return _prediction_source(config or _config(), prompt)


def test_source_collects_the_documented_fields():
    """run_id/model/model_type/thresholds/prompt/config_digest 均被采集。"""
    source = _source()

    assert re.fullmatch(r"[0-9a-f]{32}", source["run_id"])
    assert source["model_name"] == "yolov8n"
    assert source["model_type"] == "yolov8"
    assert source["prompt"] == "cat, dog"
    assert source["thresholds"] == {"conf_threshold": 0.25, "iou_threshold": 0.45}
    assert isinstance(source["config_digest"], str) and source["config_digest"]
    assert isinstance(source["started_at"], (int, float))
    # A display name must never be reported as a weights version.
    assert "weight_version" not in source or source["weight_version"]


def test_missing_fields_are_absent_not_empty_strings():
    """拿不到的字段留空（缺键/None），不能用空字符串冒充。"""
    source = _source(_config(model_version=None, category_version=None))

    for key in ("model_version", "weight_version"):
        assert source.get(key) in (None, ""), key
        assert source.get(key) != "", key
    assert "" not in [value for value in source.values() if isinstance(value, str)
                      ] or "prompt" in source


def test_secrets_and_credentialed_urls_are_dropped():
    """白名单剔除 key/authorization/token，丢弃带凭据 URL 的字符串。"""
    source = _source()
    keys = {key.casefold() for key in source}
    for name in SECRET_KEYS:
        assert name not in keys, name
    for value in source.values():
        assert "secret" not in str(value).casefold()
        assert "user:pw@" not in str(value)
    assert keys <= {key.casefold() for key in ORIGIN_FIELDS}


def test_prompt_carrying_a_credential_is_not_recorded():
    """prompt 里出现凭据形态时整段丢弃，而不是截断后保留。"""
    source = _source(prompt="authorization: Bearer abc123")
    assert "prompt" not in source


# ---------------------------------------------------------------------------
# 4.2 -- outcome fields: status / mode / elapsed
# ---------------------------------------------------------------------------
def test_additive_result_is_finalised_as_additive():
    """replace=False 的预测必须以 additive 记录，而不是默认 replacement。"""
    from anylabeling.services.auto_labeling import model_manager as mm

    finalise = getattr(mm, "_finalise_source", None)
    assert finalise is not None, (
        "model_manager must expose _finalise_source so an additive run is not "
        "recorded as a replacement"
    )
    source = _source()
    result = AutoLabelingResult([], replace=False)

    finalised = finalise(source, result, 0.0)

    assert finalised["mode"] == "additive"
    assert finalised["status"] == "success"
    assert finalised["inference_seconds"] >= 0
    assert finalised["elapsed_s"] >= 0


def test_replacement_result_is_finalised_as_replacement():
    """replace=True 推导为 replacement。"""
    from anylabeling.services.auto_labeling.model_manager import _finalise_source

    finalised = _finalise_source(_source(), AutoLabelingResult([], replace=True), 0.0)

    assert finalised["mode"] == "replacement"


def test_collection_can_be_switched_on_and_defaults_off():
    """采集默认关闭；开启入口存在且幂等。"""
    from anylabeling.services.auto_labeling.model_manager import (
        enable_prediction_provenance,
    )

    manager = SimpleNamespace(collect_prediction_provenance=False)
    assert enable_prediction_provenance(manager) is True
    assert manager.collect_prediction_provenance is True
    assert enable_prediction_provenance(manager, False) is True
    assert manager.collect_prediction_provenance is False


# ---------------------------------------------------------------------------
# 4.2 -- controller side reads the provenance
# ---------------------------------------------------------------------------
def _controller(work, shapes):
    image = work / "images" / "scene.jpg"
    labels = work / "labels"
    image.parent.mkdir(parents=True, exist_ok=True)
    labels.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"synthetic-image")
    host = SimpleNamespace(
        filename=str(image), output_dir=str(labels),
        canvas=SimpleNamespace(shapes=shapes),
        _config={"language": "zh_CN"},
    )
    controller = CorrectionMetricsController(host, language="zh_CN",
                                             storage_root=work / "db")
    assert controller.start_scope(str(image.parent), str(labels)) is True
    return controller


def test_applied_prediction_becomes_the_round_origin(tmp_path):
    """prediction_applied 后 row 的 origin/run_id/model/ai_count 正确。"""
    shapes = [synthetic.rect("a-001", "cat", (10, 10, 60, 60)),
              synthetic.rect("a-002", "dog", (80, 10, 130, 60))]
    controller = _controller(tmp_path, shapes)
    result = SimpleNamespace(
        replace=True,
        provenance={"run_id": "run-1", "model_name": "yolov8n",
                    "mode": "additive"},
    )
    try:
        assert controller.prediction_applied(result) is True
        row = controller.current_row(draft=True)
        assert row["origin"] == "additive"
        assert row["run_id"] == "run-1"
        assert row["model"] == "yolov8n"
        assert row["ai_count"] == 2
    finally:
        controller.stop()


def test_replacement_provenance_is_recorded_as_replacement(tmp_path):
    """mode=replacement 时 origin 为 replacement。"""
    shapes = [synthetic.rect("a-001", "cat", (10, 10, 60, 60))]
    controller = _controller(tmp_path, shapes)
    result = SimpleNamespace(replace=True,
                             provenance={"run_id": "run-2", "mode": "replacement"})
    try:
        assert controller.prediction_applied(result) is True
        assert controller.current_row(draft=True)["origin"] == "replacement"
    finally:
        controller.stop()


def test_unknown_provenance_fields_stay_none(tmp_path):
    """缺失字段在行里是 None，不是空字符串。"""
    shapes = [synthetic.rect("a-001", "cat", (10, 10, 60, 60))]
    controller = _controller(tmp_path, shapes)
    result = SimpleNamespace(replace=True, provenance={"run_id": "run-3"})
    try:
        assert controller.prediction_applied(result) is True
        row = controller.current_row(draft=True)
        for field in ("model", "model_version", "config_digest", "prompt",
                      "thresholds", "category_version", "inference_seconds"):
            assert row[field] is None, field
    finally:
        controller.stop()


def test_result_without_provenance_falls_back_to_replacement(tmp_path):
    """旧模型不提供来源时按 replacement 起点处理且不伪造字段。"""
    shapes = [synthetic.rect("a-001", "cat", (10, 10, 60, 60))]
    controller = _controller(tmp_path, shapes)
    try:
        assert controller.prediction_applied(AutoLabelingResult(shapes, replace=False)) is True
        row = controller.current_row(draft=True)
        assert row["origin"] == "replacement"
        assert row["run_id"] is None and row["model"] is None
    finally:
        controller.stop()
