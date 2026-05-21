"""Convert YOLO pose keypoint confidence values to visibility flags."""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Convert YOLO pose labels from x y conf keypoints to "
            "x y visibility keypoints for X-AnyLabeling import."
        )
    )
    parser.add_argument(
        "--src-dir",
        type=Path,
        required=True,
        help="Directory containing raw YOLO pose .txt label files.",
    )
    parser.add_argument(
        "--dst-dir",
        type=Path,
        required=True,
        help="Directory where converted .txt label files will be saved.",
    )
    parser.add_argument(
        "--num-kpts",
        type=int,
        default=17,
        help="Number of keypoints per pose instance. Default: 17.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Confidence threshold. conf >= threshold becomes visible=2. Default: 0.5.",
    )
    parser.add_argument(
        "--class-id",
        type=int,
        default=None,
        help=(
            "Only convert this input pose class id. "
            "Omit to keep all classes."
        ),
    )
    parser.add_argument(
        "--output-class-id",
        type=int,
        default=None,
        help=(
            "Class id written to the output labels. "
            "Omit to keep the original class id."
        ),
    )
    parser.add_argument(
        "--keep-hidden-xy",
        action="store_true",
        help="Keep x/y for hidden keypoints instead of setting them to 0.",
    )
    parser.add_argument(
        "--box-only-class-ids",
        default="",
        help=(
            "Comma-separated class ids that should keep only class/cx/cy/w/h "
            "and drop keypoints, for example: 1,2."
        ),
    )
    return parser.parse_args()


def parse_class_ids(value: str) -> set[int]:
    """Parse a comma-separated class id list."""
    if not value.strip():
        return set()
    return {int(item.strip()) for item in value.split(",") if item.strip()}


def convert_file(
    txt_path: Path,
    output_path: Path,
    num_kpts: int,
    threshold: float,
    class_id: int,
    output_class_id: int,
    keep_hidden_xy: bool,
    box_only_class_ids: set[int],
) -> tuple[int, int]:
    """Convert one label file and return converted/skipped line counts."""
    converted = 0
    skipped = 0
    expected = 1 + 4 + num_kpts * 3
    new_lines = []

    for line_no, line in enumerate(txt_path.read_text(encoding="utf-8").splitlines(), 1):
        parts = line.strip().split()
        if not parts:
            continue

        try:
            current_class_id = int(float(parts[0]))
        except ValueError:
            print(f"[skip] {txt_path.name}:{line_no}, invalid class id: {parts[0]}")
            skipped += 1
            continue

        if class_id is not None and current_class_id != class_id:
            skipped += 1
            continue

        if len(parts) != expected:
            print(
                f"[skip] {txt_path.name}:{line_no}, "
                f"fields={len(parts)}, expected={expected}"
            )
            skipped += 1
            continue

        out = parts[:5]
        if output_class_id is not None:
            out[0] = str(output_class_id)
        if current_class_id in box_only_class_ids:
            new_lines.append(" ".join(out))
            converted += 1
            continue

        keypoints = parts[5:]
        for i in range(num_kpts):
            x = keypoints[i * 3]
            y = keypoints[i * 3 + 1]
            conf = float(keypoints[i * 3 + 2])
            visible = 2 if conf >= threshold else 0

            if visible == 0 and not keep_hidden_xy:
                x = "0"
                y = "0"

            out.extend([x, y, str(visible)])

        new_lines.append(" ".join(out))
        converted += 1

    output_path.write_text(
        "\n".join(new_lines) + ("\n" if new_lines else ""),
        encoding="utf-8",
    )
    return converted, skipped


def main() -> None:
    """Run the converter."""
    args = parse_args()
    args.dst_dir.mkdir(parents=True, exist_ok=True)
    box_only_class_ids = parse_class_ids(args.box_only_class_ids)

    total_files = 0
    total_converted = 0
    total_skipped = 0

    for txt_path in sorted(args.src_dir.glob("*.txt")):
        converted, skipped = convert_file(
            txt_path=txt_path,
            output_path=args.dst_dir / txt_path.name,
            num_kpts=args.num_kpts,
            threshold=args.threshold,
            class_id=args.class_id,
            output_class_id=args.output_class_id,
            keep_hidden_xy=args.keep_hidden_xy,
            box_only_class_ids=box_only_class_ids,
        )
        total_files += 1
        total_converted += converted
        total_skipped += skipped

    print(
        "Done. "
        f"files={total_files}, converted_lines={total_converted}, "
        f"skipped_lines={total_skipped}, output={args.dst_dir}"
    )


if __name__ == "__main__":
    main()


"""
功能说明：
    这个脚本用来把 YOLO 姿态估计（pose）的标注文件做格式转换。
    YOLO pose 的每个关键点通常是 x y conf（坐标+置信度），
    但 X-AnyLabeling 导入时需要 x y visibility（坐标+可见性标志）。
    这个脚本就是把 conf 按阈值转成 visibility：
    置信度大于等于阈值（默认 0.5）的点标为 2（可见），
    小于阈值的点标为 0（不可见）。
    对于不可见的点，默认会把它们的 x、y 坐标也清零，
    除非加 --keep-hidden-xy 参数保留原坐标。
    脚本还可以只转换指定的类别、修改输出类别号，
    或者让某些类别只保留检测框、去掉关键点。

运行命令样例：

  # 基础转换：把 yolo_labels 里的所有 .txt 文件转换后存到 output_labels
  python scripts/convert_yolo_pose_conf_to_visibility.py \
      --src-dir ./yolo_labels \
      --dst-dir ./output_labels

  # 只转换 class_id 为 0 的文件，并把输出 class_id 改成 1
  python scripts/convert_yolo_pose_conf_to_visibility.py \
      --src-dir ./yolo_labels \
      --dst-dir ./output_labels \
      --class-id 0 \
      --output-class-id 1

  # 关键点数量不是 17 个时（比如 23 个关键点）
  python scripts/convert_yolo_pose_conf_to_visibility.py \
      --src-dir ./yolo_labels \
      --dst-dir ./output_labels \
      --num-kpts 23

  # 保留隐藏关键点的原始坐标（不置零）
  python scripts/convert_yolo_pose_conf_to_visibility.py \
      --src-dir ./yolo_labels \
      --dst-dir ./output_labels \
      --keep-hidden-xy

  # 让 class_id 1 和 2 只保留检测框，去掉关键点
  python scripts/convert_yolo_pose_conf_to_visibility.py \
      --src-dir ./yolo_labels \
      --dst-dir ./output_labels \
      --box-only-class-ids "1,2"
"""
