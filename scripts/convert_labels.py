import os
import glob

LABELS_DIR = "labels"
OUTPUT_DIR = "labels_d"

os.makedirs(OUTPUT_DIR, exist_ok=True)

for filepath in glob.glob(os.path.join(LABELS_DIR, "*.txt")):
    filename = os.path.basename(filepath)
    outpath = os.path.join(OUTPUT_DIR, filename)

    with open(filepath, "r") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        parts = line.strip().split()
        if not parts:
            continue
        # First 5 values: class, x, y, w, h
        new_parts = parts[:5]
        # Remaining values: keypoints in groups of 3 (x, y, visible)
        kp = parts[5:]
        for i in range(0, len(kp), 3):
            x = kp[i]
            y = kp[i+1]
            v = float(kp[i+2])
            new_v = "2" if v > 0.5 else "0"
            new_parts.extend([x, y, new_v])
        new_lines.append(" ".join(new_parts))

    with open(outpath, "w") as f:
        f.write("\n".join(new_lines) + "\n")

print("Done.")


"""
功能说明：
    这个脚本用来批量转换 YOLO 格式的标注文件。
    它读取 labels 文件夹里的所有 .txt 文件，把关键点（keypoint）
    的可见性值按 0.5 的阈值改成 0（不可见）或 2（可见），
    然后把转换后的结果保存到 labels_d 文件夹里。

运行命令样例：

  # 在项目根目录下直接运行
  python scripts/convert_labels.py
"""
