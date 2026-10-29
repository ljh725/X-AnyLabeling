"""Render measured real-dataset output-directory timings as Markdown."""

import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
data = json.loads((HERE / "output_change_results.json").read_text(encoding="utf-8"))
assert len(data["runs"]) == 3
assert all(data["read_only_verification"].values())
for path, digest in data["source_sha256"].items():
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest

def stage(name):
    return statistics.median(run["stage_seconds_inclusive"].get(name, 0) for run in data["runs"])

lines = [
    "# 真实 PRW 数据：更改输出目录后，首图标注显示耗时",
    "",
    "日期：2026-10-29（Asia/Shanghai）。用户确认 7～10 分钟的等待发生在旧版本。本次验证当前工作区 4.2.1 源码，不将旧版耗时视为当前版本的已复现故障。",
    "",
    "## 结果",
    "",
    f"确认输出目录到首张图片含标注的绘制完成，三次中位数为 **{data['summary']['first_annotated_paint_seconds_median']:.3f} 秒**。已经加载好的图像和标注，单独触发 20 次画布重绘，中位数为 **{data['loaded_frame_repaint']['median_seconds']*1000:.2f} 毫秒**。",
    "",
    "本数据的当前版本等待主要来自全目录读取与文件列表建立，单张图片上画框/画关键点不是主要瓶颈。本次没有复现旧版本所述的 7～10 分钟，也没有测试旧版本，因此不能据此认定旧版的具体根因。",
    "",
    "## 数据与测试方法",
    "",
    f"- 图片目录：`{data['images']}`。",
    f"- 标注目录：`{data['labels']}`。",
    f"- 图片与标注各 {data['file_count']:,} 个；全部 JSON 共 {data['json_total_bytes']/1024**2:.2f} MiB。",
    f"- 首图：`{data['first_image']}`，1920×1080。首图有 **3 个矩形框和 51 个关键点，共 54 个对象**。原文件版本字段为 4.0.0-beta.4，未含持久对象 ID；当前加载时只在内存中规范化对象 ID，没有回写 JSON。",
    "- 直接启动当前工作区的真实 MainWindow、完整信号连接、应用资源图标、原有数据加载与 Canvas 绘制代码。测试私有窗口 1600×1000，画布约 1301×917，默认显示框、关键点、类别文字及掩码等。",
    "- 先在真实软件窗口打开图片目录，再替换文件选择对话框的返回值，等价于用户选好输出目录并确认。随后完整执行 change_output_dir_dialog，直到 Canvas.paintEvent 处理完含 54 个对象的首帧。人的选目录用时不计入。",
    "- Python 3.11.9；PyQt6/Qt 6.12.0；Qt offscreen。计入软件绘制计算，不计物理显示器扫描输出、桌面合成器或 GPU 驱动呈现延迟。使用独立配置和 QSettings，主题 light。未操作用户现有窗口。",
    "- 为保证原数据只读，关闭自动保存、继承上一张标注和 EXIF 扫描/处理。未做任何标注编辑。Python 审计钩子另外拒绝向两个原始数据目录写文件、删文件或改名。",
    "- 未清空操作系统缓存；正式测试前已有部分文件读取，首轮也不能当作严格冷缓存结果。不能把本次数字视为所有机器、所有配置的性能保证。",
    "- 对相关真实方法作计时包装，存在少量统计开销。各阶段为包含子调用的累计时间，不能全部相加。",
    "",
    "## 三次完整操作",
    "",
    "| 次数 | 更改目录函数返回 | 首张图片标注绘制完成 | UI 定时器最长间隔 |",
    "|---|---:|---:|---:|",
]
for run in data["runs"]:
    lines.append(f"| {run['iteration']} | {run['output_change_return_seconds']:.3f} s | {run['first_annotated_paint_seconds']:.3f} s | {run['largest_ui_heartbeat_gap_seconds']:.3f} s |")
lines += [
    "",
    "首帧时间有时略早于函数返回，因为真实方法中的同步 repaint 会在方法返回前触发绘制。UI 心跳每 10 ms 设置一次，实际间隔约等于整段 4.8～5.0 秒，确认当前实现仍会短暂阻塞主线程。",
    "",
    "## 分阶段耗时（3 次中位数）",
    "",
    "| 阶段 | 耗时 | 说明 |",
    "|---|---:|---|",
    f"| 扫描图片路径和自然排序 | {stage('scan_and_sort')*1000:.2f} ms | 一次目录扫描 |",
    f"| 逐个读取 JSON 审核状态 | {stage('status_read'):.3f} s | 共 11,792 次 |",
    f"| 创建文件列表条目，含审核读取 | {stage('create_file_item'):.3f} s | 11,792 条；包含上一行耗时 |",
    f"| 完整导入目录 | {stage('folder_import'):.3f} s | 包含扫描、状态读取和列表建立 |",
    f"| 加载当前图片完整流程 | {stage('load_current_file')*1000:.2f} ms | 一次，包含下列部分步骤 |",
    f"| 首图 JSON 解析、对象构建 | {stage('label_file_parse')*1000:.2f} ms | 54 个对象；第一轮略慢，原始值在 JSON 结果中 |",
    f"| 图片解码为 QImage | {stage('decode_image')*1000:.2f} ms | 1920×1080 JPG |",
    f"| 标注列表及画布对象载入 | {stage('widget_load_shapes')*1000:.2f} ms | 含对象列表、撤销快照、筛选同步 |",
    f"| 本次操作触发的全部画布绘制 | {stage('canvas_paint')*1000:.2f} ms | 每次操作 2 个 paintEvent，合计 |",
    "",
    "## 单独测绘图",
    "",
    f"在首图及 54 个对象已经加载好的情况下调用真实 canvas.repaint() 20 次：中位数 **{data['loaded_frame_repaint']['median_seconds']*1000:.2f} ms**，最小 {data['loaded_frame_repaint']['min_seconds']*1000:.2f} ms，最大 {data['loaded_frame_repaint']['max_seconds']*1000:.2f} ms。实际执行 20 次 Canvas.paintEvent，共调用 Shape.paint 1080 次（54×20）。",
    "",
    "这个数字代表本次首图场景的完整画布重绘计算，不是读取一万个 JSON 的时间，也不是鼠标手动画新框的时延。没有把物理屏幕帧率或用户实际可感知延迟等同于上述 CPU/Qt 耗时。",
    "",
    "## 判断与后续处理",
    "",
    "1. 当前 4.2.1 在这套真实数据下，确认输出目录到首图标注显示约 5 秒，主要仍卡在全目录读取；此前提出的后台扫描、分批显示和索引缓存仍是优先方向。",
    "2. 首图仅 3 个框和 51 个关键点，绘制仅毫秒级，没有依据优先重写绘图引擎。更多对象、更大图像或特殊显示设置的表现需另测，不能从一张图外推。",
    "3. 旧版的 7～10 分钟没有在当前版本复现。要确认旧版原因，需要对应旧版的准确代码或启动程序进行相同数据测试；本次未作未经验证的旧版归因。",
    "4. 本次没有实施性能修复，只留下独立测试工具和测量结果，没有改动应用源码。",
    "",
    "## 原数据保护与产物",
    "",
    "- 测试前后，全部 JSON 的数量、文件大小和修改时间一致；首图 JSON SHA256 一致。",
    "- 全部图片的数量、文件大小、修改时间一致；运行时有针对原始目录的写入/删除/改名保护。",
    "- 四个被测生产源文件的 SHA256 前后一致。",
    "- 原始数据：output_change_results.json；运行日志：output_change.log；脚本：benchmark_output_change.py 和 probe.py。",
    "",
    "复测：在当前工作区运行以下命令，依赖仅安装到此测试目录，不改全局 Python。测试会创建私有 profile，不回写原始数据。",
    "",
    "```powershell",
    "uv --cache-dir benchmarks/canvas_drawing_20261029/.uv-cache pip install --python D:/Python311/python.exe --target benchmarks/canvas_drawing_20261029/.deps PyQt6==6.12.0 PyQt6-WebEngine==6.11.0 darkdetect==0.8.0",
    "D:/Python311/python.exe benchmarks/canvas_drawing_20261029/benchmark_output_change.py",
    "D:/Python311/python.exe benchmarks/canvas_drawing_20261029/make_report.py",
    "```",
    "",
    "复测需要 D:/Python311 中现有的应用依赖。此机器的既有依赖已成功启动真实主窗口。完整环境版本详见结果 JSON。测试结束后可删除测试目录的 .deps、.uv-cache、profile、__pycache__；保留脚本、结果和报告即可。",
    "",
]
(HERE / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
print(HERE / "REPORT.md")
