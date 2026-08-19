"""Regression checks for virtual-review shortcut defaults."""

from pathlib import Path

import yaml


def test_virtual_review_shortcuts_keep_f1_digit_page_compatibility():
    """F1 remains the digit page action while F2 navigates virtual tasks."""
    config_path = Path("anylabeling/configs/xanylabeling_config.yaml")
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    shortcuts = config["shortcuts"]

    assert shortcuts["switch_digit_page"] == "F1"
    assert shortcuts["virtual_review_next"] == "F2"
    assert shortcuts["virtual_review_prev"] == "Shift+F2"
