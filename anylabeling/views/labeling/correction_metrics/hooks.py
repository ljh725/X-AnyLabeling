"""Optional statistics observer. Annotation operations always own their result."""

from ..logger import logger


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
