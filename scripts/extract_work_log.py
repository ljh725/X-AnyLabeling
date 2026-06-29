"""从原始工作记录 CSV 提取"日期|时长|内容"三列汇总。

数据源每条记录占多行，关键信息分布在固定列：
- 内容: 第 1 列 (index 0)
- 日期: 第 10 列附近 (index 9)，格式 YYYY.MM.DD
- 时长: 第 17 列附近 (index 16)，数字

规则:
- 只保留含日期的行 (一条记录)
- 空内容 -> （续前一天）
- 空时长 -> -
- 日期标准化为 YYYY-MM-DD
"""

import csv
import re
import sys
from pathlib import Path

SRC = Path(r"D:\桌面备份\2026年1-6月工作记录.csv")
DST = Path(r"D:\桌面备份\2026年1-6月工作总结.csv")

DATE_RE = re.compile(r"(20\d{2})\.(\d{1,2})\.(\d{1,2})")


def parse_cell(val):
    """单元格去空白、去内部换行，None -> ''"""
    if val is None:
        return ""
    return str(val).strip().strip('"').strip().replace("\r", " ").replace("\n", " ")


def is_noise(content):
    """跳过无意义的噪声行"""
    return content in ("开始位", "结束位", "时长", "图片数量位置", "场景位置")


def main():
    rows_out = []
    # GBK 编码读取 (Windows 中文 Excel 默认导出编码)
    with open(SRC, "r", encoding="gbk", errors="replace", newline="") as f:
        reader = csv.reader(f)
        for raw in reader:
            if not raw:
                continue
            # 找日期单元格
            date_cell = None
            date_idx = -1
            for i, cell in enumerate(raw):
                if DATE_RE.search(parse_cell(cell)):
                    date_cell = parse_cell(cell)
                    date_idx = i
                    break
            if date_cell is None:
                continue
            # 标准化日期
            m = DATE_RE.search(date_cell)
            date_std = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

            # 内容: 第 1 列
            content = parse_cell(raw[0]) if len(raw) > 0 else ""
            if not content or is_noise(content):
                content = "（续前一天）"
            else:
                # 合并多余空格
                content = re.sub(r"\s+", " ", content)

            # 时长: 日期列之后可能有数值, 扫描剩余非空数字单元格
            duration = "-"
            for cell in raw[date_idx + 1 :]:
                v = parse_cell(cell)
                if not v or is_noise(v):
                    continue
                # 纯数字 (含小数) 视为时长
                try:
                    num = float(v)
                    duration = f"{num:g}"
                    break
                except ValueError:
                    continue

            rows_out.append((date_std, duration, content))

    # 按日期升序
    rows_out.sort(key=lambda r: r[0])

    # 写出 (UTF-8-BOM, Excel 友好)
    with open(DST, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["日期", "时长", "工作内容"])
        for r in rows_out:
            w.writerow(r)

    # 控制台预览
    print(f"共提取 {len(rows_out)} 条记录 -> {DST}")
    print("-" * 60)
    print(f"{'日期':<12}{'时长':<6}{'工作内容'}")
    print("-" * 60)
    for d, t, c in rows_out:
        print(f"{d:<12}{t:<6}{c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
