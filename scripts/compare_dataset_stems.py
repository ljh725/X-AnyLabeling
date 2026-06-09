"""Compare filename stems between two dataset directories (with progress bar and thread pool).

功能说明：
    这个脚本用于对比两个目录中的文件名（去掉扩展名后的 stem），
    找出只在目录A中存在、只在目录B中存在、以及两边都存在的文件名。

    适用于标注项目的数据集检查场景，例如：
    - 对比图片文件夹和标签文件夹，找出没有对应标签的图片
    - 对比两个标注批次，找出差异文件
    - 检查数据完整性

支持的文件类型：
    - 图片：.jpg, .jpeg, .png, .bmp, .gif, .webp, .tiff, .tif
    - 标签：.txt, .json, .xml
    - 其他：会归类为 other

输出报告：
    生成 Markdown 格式的报告，包含：
    - 统计摘要（总数、只在A、只在B、共有）
    - 只在A中的文件列表（按图片/标签/其他分类）
    - 只在B中的文件列表
    - 共有的文件列表（分别展示A和B中的对应文件）

性能优化：
    - 文件数 <= 500：单线程处理，避免线程开销
    - 文件数 > 500：自动启用多线程池加速
    - 支持 --workers 参数自定义线程数
    - 使用 tqdm 进度条显示处理进度（可禁用）

依赖：
    pip install tqdm
"""

from __future__ import annotations

import argparse
import os
import os.path as osp
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from tqdm import tqdm
except ModuleNotFoundError:
    class _TqdmFallback:
        """No-op tqdm replacement when tqdm is not installed."""

        def __init__(self, iterable=None, *args, **kwargs):
            self.iterable = iterable

        def __iter__(self):
            return iter(self.iterable or [])

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def update(self, value: int = 1) -> None:
            """Accept update calls for context-manager progress bars."""

    def tqdm(iterable=None, *args, **kwargs):
        """Return a no-op progress wrapper."""
        return _TqdmFallback(iterable, *args, **kwargs)


IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff", ".tif"}
)
LABEL_EXTENSIONS = frozenset({".txt", ".json", ".xml"})


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Compare filename stems (without extension) between two "
            "directories. Reports stems found only in A, only in B, and "
            "common to both.\n\n"
            "Features:\n"
            "  - Auto-classifies files as images, labels, or other\n"
            "  - Progress bar for large directories (tqdm)\n"
            "  - Multi-threading for directories with >500 files\n"
            "  - Generates a Markdown report with detailed breakdown\n\n"
            "Supported extensions:\n"
            "  Images: .jpg, .jpeg, .png, .bmp, .gif, .webp, .tiff, .tif\n"
            "  Labels: .txt, .json, .xml"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  # 基础对比：两个数据集目录
  %(prog)s --dir-a ./dataset_a --dir-b ./dataset_b --output report.md

  # 对比图片和标签文件夹（检查是否有图片缺少标签）
  %(prog)s --dir-a ./images --dir-b ./labels --output ./missing_labels.md

  # 指定线程数（处理大目录时有用）
  %(prog)s --dir-a ./batch1 --dir-b ./batch2 --output diff.md --workers 16

  # 服务器环境禁用进度条（输出到日志文件时）
  %(prog)s --dir-a /data/images --dir-b /data/labels --output report.md --no-progress

  # Windows 路径示例
  %(prog)s --dir-a D:\\images --dir-b D:\\labels --output D:\\report.md
""",
    )
    parser.add_argument(
        "--dir-a",
        required=True,
        type=Path,
        help="First directory to compare.",
    )
    parser.add_argument(
        "--dir-b",
        required=True,
        type=Path,
        help="Second directory to compare.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output report file path (e.g., report.md).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=min(8, os.cpu_count() or 4),
        help="Number of worker threads (default: min(8, CPU_COUNT)).",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bars (useful for server/CI environments).",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help=(
            "Only write the summary table. Useful for very large datasets "
            "or slow network shares."
        ),
    )
    return parser.parse_args()


def validate_directories(dir_a: Path, dir_b: Path) -> None:
    """Ensure both paths are existing directories."""
    if not dir_a.is_dir():
        print(f"Error: --dir-a is not a directory: {dir_a}", file=sys.stderr)
        sys.exit(1)
    if not dir_b.is_dir():
        print(f"Error: --dir-b is not a directory: {dir_b}", file=sys.stderr)
        sys.exit(1)


def classify_file(path: Path) -> str:
    """Classify a file as image, label, or other based on extension."""
    ext = path.suffix.lower()
    return classify_extension(ext)


def classify_extension(ext: str) -> str:
    """Classify a file by extension."""
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in LABEL_EXTENSIONS:
        return "label"
    return "other"


def _scan_file_names(directory: Path) -> tuple[list[str], int, int]:
    """Return file names in a directory using cached scandir metadata."""
    file_names: list[str] = []
    skipped_entries = 0
    failed_entries = 0

    with os.scandir(directory) as entries:
        for entry in entries:
            try:
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                failed_entries += 1
                continue
            if not is_file:
                skipped_entries += 1
                continue
            file_names.append(entry.name)

    return file_names, skipped_entries, failed_entries


def collect_stems(
    directory: Path, workers: int = 4, disable_progress: bool = False
) -> dict[str, dict[str, list[str]]]:
    """Collect stems and their associated files from a directory.

    Returns a dict mapping stem -> {category -> [filenames]}.
    """
    print(f"[INFO] Scanning directory: {directory}")
    start_time = time.time()

    file_names, skipped_entries, failed_entries = _scan_file_names(directory)
    total_files = len(file_names)

    if not file_names:
        print(f"[INFO] Directory is empty: {directory}")
        return {}

    print(
        f"[INFO] Found {total_files} files in {directory.name} "
        f"(skipped={skipped_entries}, inaccessible={failed_entries})"
    )

    stems: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for file_name in tqdm(
        sorted(file_names, key=str.lower),
        desc=f"Scanning {directory.name}",
        unit="file",
        disable=disable_progress,
        file=sys.stdout,
        miniters=max(1, total_files // 100),
    ):
        stem, ext = osp.splitext(file_name)
        category = classify_extension(ext.lower())
        stems[stem][category].append(file_name)

    elapsed = time.time() - start_time
    print(
        f"[INFO] Scanned {directory.name}: "
        f"{len(stems)} stems from {total_files} files "
        f"({elapsed:.2f}s)"
    )
    return dict(stems)


def _format_stem_entry(stem: str, source: dict) -> list[str]:
    """Format a single stem entry for the report."""
    lines: list[str] = []
    files = source.get(stem, {})
    image_files = files.get("image", [])
    label_files = files.get("label", [])
    other_files = files.get("other", [])
    lines.append(f"- `{stem}`")
    if image_files:
        lines.append(f"  - Images: {', '.join(f'`{f}`' for f in image_files)}")
    if label_files:
        lines.append(f"  - Labels: {', '.join(f'`{f}`' for f in label_files)}")
    if other_files:
        lines.append(f"  - Other: {', '.join(f'`{f}`' for f in other_files)}")
    return lines


def _format_common_entry(stem: str, stems_a: dict, stems_b: dict) -> list[str]:
    """Format a single common stem entry for the report."""
    lines: list[str] = []
    files_a = stems_a.get(stem, {})
    files_b = stems_b.get(stem, {})
    a_images = files_a.get("image", [])
    a_labels = files_a.get("label", [])
    b_images = files_b.get("image", [])
    b_labels = files_b.get("label", [])
    lines.append(f"- `{stem}`")
    if a_images or a_labels:
        parts = []
        if a_images:
            parts.append(f"images: {', '.join(f'`{f}`' for f in a_images)}")
        if a_labels:
            parts.append(f"labels: {', '.join(f'`{f}`' for f in a_labels)}")
        lines.append(f"  - A: {'; '.join(parts)}")
    if b_images or b_labels:
        parts = []
        if b_images:
            parts.append(f"images: {', '.join(f'`{f}`' for f in b_images)}")
        if b_labels:
            parts.append(f"labels: {', '.join(f'`{f}`' for f in b_labels)}")
        lines.append(f"  - B: {'; '.join(parts)}")
    return lines


def _format_batch(
    stems: list[str], source: dict, formatter
) -> list[str]:
    """Format a batch of stems using the provided formatter."""
    return [
        line for stem in stems for line in formatter(stem, source)
    ]


def _append_filename_detail_section(
    lines: list[str],
    title: str,
    stem_set: set[str],
    source: dict[str, dict[str, list[str]]],
) -> None:
    """Append full filenames for stems in a detail section."""
    lines.append(f"## {title}")
    lines.append("")

    if not stem_set:
        lines.append("*None found.*")
        lines.append("")
        return

    file_names: list[str] = []
    for stem in sorted(stem_set):
        categories = source.get(stem, {})
        for category in ("image", "label", "other"):
            file_names.extend(categories.get(category, []))

    for file_name in sorted(file_names, key=str.lower):
        lines.append(f"- `{file_name}`")
    lines.append("")


def generate_report(
    dir_a: Path,
    dir_b: Path,
    stems_a: dict[str, dict[str, list[str]]],
    stems_b: dict[str, dict[str, list[str]]],
    only_a: set[str],
    only_b: set[str],
    common: set[str],
    workers: int = 4,
    disable_progress: bool = False,
    summary_only: bool = False,
) -> str:
    """Generate a Markdown comparison report."""
    print("[INFO] Generating report...")
    start_time = time.time()

    lines: list[str] = []

    lines.append("# Dataset Stem Comparison Report")
    lines.append("")
    lines.append(f"- **Directory A**: `{dir_a}`")
    lines.append(f"- **Directory B**: `{dir_b}`")
    lines.append(f"- **Generated**: auto-generated")
    lines.append("")

    total_a = len(stems_a)
    total_b = len(stems_b)
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total stems in A | {total_a} |")
    lines.append(f"| Total stems in B | {total_b} |")
    lines.append(f"| Only in A | {len(only_a)} |")
    lines.append(f"| Only in B | {len(only_b)} |")
    lines.append(f"| Common to both | {len(common)} |")
    lines.append("")

    if summary_only:
        _append_filename_detail_section(
            lines, "Files Only in A", only_a, stems_a
        )
        _append_filename_detail_section(
            lines, "Files Only in B", only_b, stems_b
        )
        elapsed = time.time() - start_time
        print(f"[INFO] Summary report generated ({elapsed:.2f}s)")
        return "\n".join(lines)

    def format_section(
        title: str,
        stem_set: set[str],
        source: dict,
        formatter,
    ):
        lines.append(f"## {title}")
        lines.append("")
        if not stem_set:
            lines.append("*None found.*")
            lines.append("")
            return

        stem_list = sorted(stem_set)
        total = len(stem_list)
        print(f"[INFO] Formatting {title}: {total} stems")

        if total <= 500:
            for stem in tqdm(
                stem_list,
                desc=f"Formatting {title}",
                unit="stem",
                disable=disable_progress,
                file=sys.stdout,
                miniters=1,
            ):
                lines.extend(formatter(stem, source))
        else:
            batch_size = max(1, total // workers)
            batches = [
                stem_list[i : i + batch_size]
                for i in range(0, total, batch_size)
            ]
            print(
                f"[INFO] Using {workers} workers, "
                f"{len(batches)} batches"
            )

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(_format_batch, batch, source, formatter): i
                    for i, batch in enumerate(batches)
                }

                batch_results: list[list[str]] = []
                for future in tqdm(
                    as_completed(futures),
                    total=len(futures),
                    desc=f"Formatting {title}",
                    unit="batch",
                    disable=disable_progress,
                    file=sys.stdout,
                    miniters=1,
                ):
                    batch_results.append(future.result())

            for batch_lines in batch_results:
                lines.extend(batch_lines)

        lines.append("")

    # Only in A
    format_section(
        "Stems Only in A",
        only_a,
        stems_a,
        lambda stem, src: _format_stem_entry(stem, src),
    )

    # Only in B
    format_section(
        "Stems Only in B",
        only_b,
        stems_b,
        lambda stem, src: _format_stem_entry(stem, src),
    )

    # Common
    format_section(
        "Common Stems",
        common,
        stems_a,
        lambda stem, src: _format_common_entry(stem, stems_a, stems_b),
    )

    elapsed = time.time() - start_time
    print(f"[INFO] Report generated ({elapsed:.2f}s)")
    return "\n".join(lines)


def main() -> None:
    """Run the comparison workflow."""
    args = parse_args()
    validate_directories(args.dir_a, args.dir_b)

    # Collect stems from both directories
    stems_a = collect_stems(
        args.dir_a, workers=args.workers, disable_progress=args.no_progress
    )
    stems_b = collect_stems(
        args.dir_b, workers=args.workers, disable_progress=args.no_progress
    )

    set_a = set(stems_a.keys())
    set_b = set(stems_b.keys())

    only_a = set_a - set_b
    only_b = set_b - set_a
    common = set_a & set_b

    print(
        f"[INFO] Comparison: A={len(set_a)} stems, B={len(set_b)} stems, "
        f"OnlyA={len(only_a)}, OnlyB={len(only_b)}, Common={len(common)}"
    )

    # Generate report
    report = generate_report(
        args.dir_a,
        args.dir_b,
        stems_a,
        stems_b,
        only_a,
        only_b,
        common,
        workers=args.workers,
        disable_progress=args.no_progress,
        summary_only=args.summary_only,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"\n[INFO] Report saved to: {args.output}")
    print(f"  Only in A: {len(only_a)}")
    print(f"  Only in B: {len(only_b)}")
    print(f"  Common: {len(common)}")


if __name__ == "__main__":
    main()


"""
功能说明：
    这个脚本用来对比两个目录中的文件名（去掉扩展名后的 stem），
    找出只在目录A中存在、只在目录B中存在、以及两边都存在的文件名。

    适用于标注项目的数据集检查场景，例如：
    - 对比图片文件夹和标签文件夹，找出没有对应标签的图片
    - 对比两个标注批次，找出差异文件
    - 检查数据完整性

支持的文件类型：
    - 图片：.jpg, .jpeg, .png, .bmp, .gif, .webp, .tiff, .tif
    - 标签：.txt, .json, .xml
    - 其他：会归类为 other

输出报告：
    生成 Markdown 格式的报告，包含：
    - 统计摘要（总数、只在A、只在B、共有）
    - 只在A中的文件列表（按图片/标签/其他分类）
    - 只在B中的文件列表
    - 共有的文件列表（分别展示A和B中的对应文件）

性能优化：
    - 文件数 <= 500：单线程处理，避免线程开销
    - 文件数 > 500：自动启用多线程池加速
    - 支持 --workers 参数自定义线程数
    - 使用 tqdm 进度条显示处理进度（可禁用）

服务器环境注意事项：
    - 如果在服务器/SSH/CI 环境下进度条不显示，使用 --no-progress 参数
    - 脚本会输出 [INFO] 级别的日志到 stdout，便于重定向到日志文件
    - 每个阶段都会打印耗时统计

依赖安装：
    pip install tqdm

运行命令样例：

  # 基础对比：两个数据集目录
  python scripts/compare_dataset_stems.py \
      --dir-a ./dataset_a \
      --dir-b ./dataset_b \
      --output report.md

  # 对比图片和标签文件夹（检查是否有图片缺少标签）
  python scripts/compare_dataset_stems.py \
      --dir-a ./images \
      --dir-b ./labels \
      --output ./missing_labels.md

  # 指定线程数（处理大目录时有用，7万文件建议 16-32）
  python scripts/compare_dataset_stems.py \
      --dir-a ./batch1 \
      --dir-b ./batch2 \
      --output diff.md \
      --workers 32

  # 服务器环境禁用进度条（输出重定向到日志文件）
  python scripts/compare_dataset_stems.py \
      --dir-a /data/images \
      --dir-b /data/labels \
      --output report.md \
      --no-progress > run.log 2>&1

  # Windows 路径示例
  python scripts/compare_dataset_stems.py \
      --dir-a D:\\images \
      --dir-b D:\\labels \
      --output D:\\report.md
"""
