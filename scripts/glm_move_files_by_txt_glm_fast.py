import os
import shutil
import datetime

# ======================== 路径配置 ========================
source_dir = r"\\192.168.3.248\data1\ljh\cls3_pose\class3_1st_Edition_and_keypints_2nd_Edtion_BAK\part2_images_jsons_33076\add\jsons"
target_dir = r"\\192.168.3.248\data1\ljh\cls3_pose\class3_1st_Edition_and_keypints_2nd_Edtion_BAK\part2_images_jsons_33076\add\去除共有数据集38张"
txt_file   = r"D:\A000_report_txt\两边共有_0609.txt"
# =========================================================

# 1. 自动创建目标文件夹（如果不存在）
if not os.path.exists(target_dir):
    os.makedirs(target_dir)
    print(f"[信息] 目标文件夹已自动创建: {target_dir}")

# 2. 从txt文件中提取主文件名（忽略后缀），存入 set 加速查找
names_to_move = set()
with open(txt_file, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split('\t')
        if len(parts) >= 2:
            full_name = os.path.basename(parts[1])      # 如 s10235.jpg
            stem_name = os.path.splitext(full_name)[0]  # 如 s10235（去掉后缀）
            names_to_move.add(stem_name)

print(f"[信息] 从txt中读取到 {len(names_to_move)} 个待移动文件名")

# 3. 扫描数据源目录，遇到目标文件直接处理，避免全量建映射
success_list = []
copy_fail_list = []

remaining = set(names_to_move)  # 复制一份用于追踪尚未找到的文件

for fname in os.listdir(source_dir):
    if not remaining:
        break  # 所有目标已找到，提前退出扫描

    full_path = os.path.join(source_dir, fname)
    if not os.path.isfile(full_path):
        continue

    stem = os.path.splitext(fname)[0]
    if stem not in remaining:
        continue

    # 找到目标，立即执行复制+校验+删除
    remaining.remove(stem)
    dst_path = os.path.join(target_dir, fname)

    try:
        # 第一步：复制文件到目标路径
        shutil.copy2(full_path, dst_path)

        # 第二步：校验复制是否成功（对比文件大小）
        if os.path.exists(dst_path) and os.path.getsize(dst_path) == os.path.getsize(full_path):
            # 第三步：删除源文件
            os.remove(full_path)
            success_list.append(fname)
        else:
            copy_fail_list.append(fname)
            # 如果复制后大小不一致，删除目标端可能损坏的副本
            if os.path.exists(dst_path):
                os.remove(dst_path)
    except Exception as e:
        copy_fail_list.append(f"{fname} (错误: {e})")

# 4. 扫描结束后，remaining 中剩余的就是未找到的文件
not_found_list = list(remaining)

# 5. 在目标路径生成log文件
log_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = f"move_log_{log_time}.txt"
log_path = os.path.join(target_dir, log_filename)

with open(log_path, 'w', encoding='utf-8') as log:
    log.write("=" * 60 + "\n")
    log.write("  文件移动日志\n")
    log.write("=" * 60 + "\n")
    log.write(f"  执行时间:       {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    log.write(f"  数据源路径:     {source_dir}\n")
    log.write(f"  目标路径:       {target_dir}\n")
    log.write(f"  文件名清单:     {txt_file}\n")
    log.write("=" * 60 + "\n\n")

    log.write(f"【成功移动】共 {len(success_list)} 个文件\n")
    log.write("-" * 40 + "\n")
    for item in success_list:
        log.write(f"  {item}\n")
    log.write("\n")

    log.write(f"【未找到】共 {len(not_found_list)} 个文件（数据源中不存在，已跳过）\n")
    log.write("-" * 40 + "\n")
    for item in not_found_list:
        log.write(f"  {item}\n")
    log.write("\n")

    log.write(f"【复制失败】共 {len(copy_fail_list)} 个文件\n")
    log.write("-" * 40 + "\n")
    for item in copy_fail_list:
        log.write(f"  {item}\n")
    log.write("\n")

    log.write("=" * 60 + "\n")
    log.write("  汇总统计\n")
    log.write("=" * 60 + "\n")
    log.write(f"  待移动总数: {len(names_to_move)}\n")
    log.write(f"  成功移动:   {len(success_list)}\n")
    log.write(f"  未找到:     {len(not_found_list)}\n")
    log.write(f"  复制失败:   {len(copy_fail_list)}\n")

# 6. 控制台输出结果
print("\n" + "=" * 50)
print("  移动操作完成！")
print("=" * 50)
print(f"  待移动总数: {len(names_to_move)}")
print(f"  成功移动:   {len(success_list)}")
print(f"  未找到:     {len(not_found_list)}")
print(f"  复制失败:   {len(copy_fail_list)}")
print(f"\n  日志文件已保存至: {log_path}")
print("=" * 50)
