"""Capture exact source locations and fingerprints for beta.4 crosshairs."""
import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "beta4_crosshair"
VERSIONS = {
    "original_beta4": Path("D:/X-AnyLabeling-4.0.0-beta.4"),
    "personal_beta4": Path("D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4"),
    "current_421": ROOT,
}
SPECS = {
    "anylabeling/configs/xanylabeling_config.yaml": {"crosshair"},
    "anylabeling/views/labeling/widgets/canvas.py": {
        "_draw_crosshair", "_rectangle_creation_crosshair_enabled", "set_cross_line", "_cross_line_pen"
    },
    "anylabeling/views/labeling/widgets/rectangle_guide_overlay.py": {
        "RectangleGuidePalette", "RectangleGuideOverlayRenderer"
    },
    "anylabeling/views/labeling/widgets/rectangle_crosshair.py": {
        "_draw_rectangle_crosshair", "_native_crosshair_enabled"
    },
    "anylabeling/views/labeling/widgets/crosshair_settings_dialog.py": {"choose_color", "get_settings"},
    "anylabeling/views/labeling/settings/runtime_applier.py": {"apply_canvas_crosshair"},
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    evidence = []
    for version, root in VERSIONS.items():
        for relative, selected in SPECS.items():
            path = root / relative
            if not path.is_file():
                continue
            payload = path.read_bytes()
            source = payload.decode("utf-8-sig")
            lines = source.splitlines()
            snippets = []
            if path.suffix == ".yaml":
                for index, line in enumerate(lines):
                    if line == "  crosshair:":
                        end = index + 1
                        while end < len(lines) and (lines[end].startswith("    ") or not lines[end].strip()):
                            end += 1
                        snippets.append({"name": "canvas.crosshair", "line": index + 1, "end": end, "source": "\n".join(lines[index:end])})
            else:
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in selected:
                        snippets.append({"name": node.name, "line": node.lineno, "end": node.end_lineno,
                                         "source": "\n".join(lines[node.lineno - 1:node.end_lineno])})
                if relative.endswith("rectangle_crosshair.py"):
                    snippets.insert(0, {"name": "guide_constants", "line": 7, "end": 8, "source": "\n".join(lines[6:8])})
            evidence.append({"version": version, "path": str(path), "sha256": hashlib.sha256(payload).hexdigest(), "snippets": snippets})
            if version == "personal_beta4" and path.name == "rectangle_guide_overlay.py":
                (OUT / path.name).write_bytes(payload)
    (OUT / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Captured {len(evidence)} source files")


if __name__ == "__main__":
    main()
