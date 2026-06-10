import argparse
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

import orjson as json


def extract_labels(json_path: str) -> set[str]:
    """从单个 JSON 文件中提取所有非空 label."""
    try:
        with open(json_path, "rb") as f:
            data = json.loads(f.read())
        return {shape["label"] for shape in data["shapes"] if shape.get("label")}
    except Exception:
        return set()


def get_json_files(root_dir: str) -> list[str]:
    """递归获取所有 JSON 文件路径."""
    files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for name in filenames:
            if name.endswith(".json"):
                files.append(os.path.join(dirpath, name))
    return files


def main():
    parser = argparse.ArgumentParser(
        description="递归遍历 JSON 文件，汇总唯一标签名（高性能版，每 5000 文件显示进度）。"
    )
    parser.add_argument("input_dir", help="输入目录（递归子目录）")
    parser.add_argument("output_file", help="输出 txt 文件路径")
    args = parser.parse_args()

    json_files = get_json_files(args.input_dir)
    total = len(json_files)
    if not total:
        print("未找到 JSON 文件。")
        return

    print(f"找到 {total} 个 JSON 文件，开始处理...")
    start_time = time.time()

    unique_labels: set[str] = set()
    batch_size = 5000
    processed = 0

    # 使用进程池并行处理
    cpu_count = multiprocessing.cpu_count()
    with ProcessPoolExecutor(max_workers=cpu_count) as executor:
        futures = {executor.submit(extract_labels, path): path for path in json_files}
        
        for future in as_completed(futures):
            try:
                labels = future.result()
                unique_labels.update(labels)
            except Exception:
                pass
            
            processed += 1

            if processed % batch_size == 0:
                elapsed = time.time() - start_time
                speed = processed / elapsed if elapsed > 0 else 0
                remaining = (total - processed) / speed if speed > 0 else 0
                print(
                    f"  进度: {processed}/{total} ({processed/total*100:.1f}%) | "
                    f"已用 {elapsed:.1f}s | 剩余 {remaining:.1f}s | "
                    f"速度 {speed:.0f} 文件/秒"
                )

    elapsed = time.time() - start_time
    print(
        f"\n处理完成！共处理 {processed} 个文件，"
        f"提取 {len(unique_labels)} 个唯一标签，总耗时 {elapsed:.1f} 秒"
    )

    # 保存结果
    with open(args.output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(unique_labels)))
        if unique_labels:
            f.write("\n")

    print(f"结果已保存至 {args.output_file}")


if __name__ == "__main__":
    main()
