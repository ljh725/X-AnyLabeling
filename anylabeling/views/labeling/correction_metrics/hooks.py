"""Optional statistics observer and workspace availability."""

from importlib.util import find_spec

from ..logger import logger


def metrics_available():
    """Detect modules in both source installations and frozen builds."""
    return all(
        find_spec(f"{__package__}.{name}") is not None
        for name in ("controller", "panel", "report_dialog")
    )


def metrics_pending_message(language):
    return {
        "zh_CN": "修正成本统计正在开发中，完整工作区尚待接入。",
        "ja_JP": "修正コスト統計は開発中です。ワークスペースの統合をお待ちください。",
        "ko_KR": "수정 비용 통계는 개발 중이며 작업 공간 연결이 필요합니다.",
    }.get(
        language, "Correction cost statistics workspace is under development."
    )


def notify_metrics(host, operation, *args, **kwargs):
    controller = getattr(host, "correction_metrics", None)
    if controller is None:
        return None
    try:
        return getattr(controller, operation)(*args, **kwargs)
    except Exception as error:
        # Observer failures (including malformed imported shapes) must never
        # turn a successful annotation save into a failure.
        logger.warning("Correction statistics %s: %s", operation, error)
        controller.degrade(operation, error)
        return None
