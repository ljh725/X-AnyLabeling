#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
跨格式目录提取器 (Cross-Format Directory Extractor)

功能：从目标文件夹获取文件名（去后缀），在源文件夹中查找同名文件/文件夹，
     自动识别类型并复制到指定输出目录，同时生成缺失和跳过日志。

场景：目标端 .jpg 图片 → 源端 .json 文件或同名文件夹，按文件名主干匹配。
"""

import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import time

# ==================== 请修改以下配置 ====================

# 目标文件夹：从这里获取文件名列表（如 .jpg 文件）
target_dir = r'D:\A0_part1_kps_3_class_dataset\images\images'

# 源文件夹：在这里查找同名文件/文件夹（如 .json 文件或同名文件夹）
source_dir = r'D:\A0_part1_kps_3_class_dataset\sort_jsons_35100'

# 输出文件夹：找到的文件/文件夹复制到这里
output_dir = r'D:\A0_part1_kps_3_class_dataset\images\sort_json_19063'

# 日志输出目录
log_output_dir = r'D:\A0_part1_kps_3_class_dataset\images'

# 并发线程数
MAX_WORKERS = 12

# 输出日志文件名
NOT_FOUND_LOG_NAME = 'not_found_items.txt'
SKIPPED_LOG_NAME = 'skipped_existing_items.txt'

# 进度统计间隔（每处理多少个任务输出一次进度）
PROGRESS_INTERVAL = 1000

# ======================================================

os.makedirs(output_dir, exist_ok=True)
os.makedirs(log_output_dir, exist_ok=True)

start_time = time.time()

# ---------- 1. 扫描目标文件夹，提取去后缀的文件名（stem） ----------
print(f'[1/4] 正在扫描目标文件夹: {target_dir}')
target_stems = set()
with os.scandir(target_dir) as it:
    for entry in it:
        if entry.is_file():
            # 文件 → 去掉扩展名，如 001.jpg → 001
            stem = os.path.splitext(entry.name)[0]
            target_stems.add(stem)
        elif entry.is_dir():
            # 文件夹 → 直接用文件夹名作为 stem
            target_stems.add(entry.name)

print(f'      获取到目标名称(stem): {len(target_stems)} 个')

# ---------- 2. 扫描源文件夹，建立 stem → 源端信息 的映射 ----------
# source_map: { stem: ('file', 完整文件名) 或 ('dir', 文件夹名) }
# 注意：同一 stem 可能同时存在 .json 文件和同名文件夹，优先取文件夹
print(f'[2/4] 正在扫描源文件夹: {source_dir}')
source_map = {}  # stem -> ('file', name) 或
with os.scandir(source_dir) as it:
    for entry in it:
        if entry.is_file():
            stem = os.path.splitext(entry.name)[0]
            # 文件夹优先于文件，如果已有文件夹记录则不覆盖
            if stem not in source_map or source_map[stem][0] != 'dir':
                source_map[stem] = ('file', entry.name)
        elif entry.is_dir():
            source_map[entry.name] = ('dir', entry.name)

print(f'      获取到源端条目: {len(source_map)} 个 (文件+文件夹)')

# ---------- 3. 扫描输出文件夹，获取已存在条目的 stem ----------
print(f'[3/4] 正在扫描输出文件夹: {output_dir}')
output_stems = set()
if os.path.exists(output_dir):
    with os.scandir(output_dir) as it:
        for entry in it:
            if entry.is_file():
                output_stems.add(os.path.splitext(entry.name)[0])
            elif entry.is_dir():
                output_stems.add(entry.name)

print(f'      获取到已输出条目: {len(output_stems)} 个')

# ---------- 4. 内存极速比对（零网络IO） ----------
# to_copy: [(stem, kind, source_name), ...]
to_copy = []
skipped_names = []   # stem 列表
not_found_names = [] # stem 列表

for stem in target_stems:
    if stem not in source_map:
        not_found_names.append(stem)
    elif stem in output_stems:
        skipped_names.append(stem)
    else:
        kind, src_name = source_map[stem]
        to_copy.append((stem, kind, src_name))

print(f'\n[4/4] 比对完成：')
print(f'  需要复制:   {len(to_copy)} 个')
print(f'  源端缺失:   {len(not_found_names)} 个')
print(f'  已存在跳过: {len(skipped_names)} 个')

# 统计源端类型分布
file_count = sum(1 for _, k, _ in to_copy if k == 'file')
dir_count = sum(1 for _, k, _ in to_copy if k == 'dir')
print(f'  其中文件:   {file_count} 个, 文件夹: {dir_count} 个')

# ---------- 5. 多线程复制 ----------
stats = {
    'copied': 0,
    'failed': 0,
    'lock': Lock(),
}


def copy_task(item):
    """根据类型选择复制方式：文件用 copy2，文件夹用 copytree"""
    stem, kind, src_name = item
    src_path = os.path.join(source_dir, src_name)
    dst_path = os.path.join(output_dir, src_name)

    try:
        if kind == 'dir':
            shutil.copytree(src_path, dst_path)
        else:
            shutil.copy2(src_path, dst_path)
        with stats['lock']:
            stats['copied'] += 1
        return ('copied', stem, kind)
    except Exception as e:
        with stats['lock']:
            stats['failed'] += 1
        return ('failed', stem, kind, str(e))


total = len(to_copy)
if total == 0:
    print('\n无需复制，程序结束。')
else:
    print(f'\n开始复制，线程数: {MAX_WORKERS}，每 {PROGRESS_INTERVAL} 个输出一次进度')
    processed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(copy_task, item): item for item in to_copy
        }

        for future in as_completed(future_to_item):
            processed += 1
            
            # 捕获异常，防止某条任务崩溃导致整体退出
            try:
                future.result()
            except Exception as exc:
                # 极端情况下 copy_task 内部未捕获的异常
                with stats['lock']:
                    stats['failed'] += 1

            # 每 PROGRESS_INTERVAL 个或全部完成时，打印一次进度条统计
            if processed % PROGRESS_INTERVAL == 0 or processed == total:
                elapsed = time.time() - start_time
                # 计算处理速度
                speed = processed / elapsed if elapsed > 0 else 0
                
                # 进度百分比
                percent = processed / total * 100
                
                print(f'[进度] {processed}/{total} ({percent:.1f}%) | '
                      f'成功: {stats["copied"]} | 失败: {stats["failed"]} | '
                      f'速度: {speed:.1f} 项/秒 | 耗时: {elapsed:.1f}s')

# ---------- 导出日志 ----------
if not_found_names:
    not_found_file = os.path.join(log_output_dir, NOT_FOUND_LOG_NAME)
    with open(not_found_file, 'w', encoding='utf-8') as f:
        for name in sorted(not_found_names):
            f.write(name + '\n')
    print(f'\n未找到的清单已导出到: {not_found_file}')

if skipped_names:
    skipped_file = os.path.join(log_output_dir, SKIPPED_LOG_NAME)
    with open(skipped_file, 'w', encoding='utf-8') as f:
        for name in sorted(skipped_names):
            f.write(name + '\n')
    print(f'跳过重名的清单已导出到: {skipped_file}')

# ---------- 总结 ----------
cost_time = time.time() - start_time
print(f'\n总结 (总耗时: {cost_time:.2f} 秒):')
print(f'  成功复制:     {stats["copied"]} 个')
print(f'  已跳过重名:   {len(skipped_names)} 个')
print(f'  未找到:       {len(not_found_names)} 个')
print(f'  失败:         {stats["failed"]} 个')

if not_found_names:
    print(f'\n未找到的名称 (前 20 个):')
    for name in sorted(not_found_names)[:20]:
        print(f'  - {name}')
    if len(not_found_names) > 20:
        print(f'  ... 还有 {len(not_found_names) - 20} 个')


# #!/usr/bin/env python3
# # -*- coding: utf-8 -*-
# """
# 跨格式目录提取器 (Cross-Format Directory Extractor)

# 功能：从目标文件夹获取文件名（去后缀），在源文件夹中查找同名文件/文件夹，
#      自动识别类型并复制到指定输出目录，同时生成缺失和跳过日志。

# 场景：目标端 .jpg 图片 → 源端 .json 文件或同名文件夹，按文件名主干匹配。
# """

# import os
# import shutil
# from concurrent.futures import ThreadPoolExecutor, as_completed
# from threading import Lock
# import time

# # ==================== 请修改以下配置 ====================

# # 目标文件夹：从这里获取文件/文件夹名列表
# target_dir = r'D:\A0_part1_kps_3_class_dataset\hard-111\images'

# # 源文件夹：在这里查找同名文件夹（3.5万数量级）
# source_dir = r'D:\A0_part1_kps_3_class_dataset\sort_jsons_35100'

# # 输出文件夹：找到的同名文件夹复制到这里
# output_dir = r'D:\A0_part1_kps_3_class_dataset\hard-111\sort_json_111'

# # 日志输出目录
# log_output_dir = r'D:\A0_part1_kps_3_class_dataset\hard-111'

# # 并发线程数（默认 8，可按磁盘和网络情况调整）
# MAX_WORKERS = 8

# # 输出日志文件名
# NOT_FOUND_LOG_NAME = 'not_found_folder.txt'
# SKIPPED_LOG_NAME = 'skipped_existing_folder.txt'

# # ======================================================

# os.makedirs(output_dir, exist_ok=True)
# os.makedirs(log_output_dir, exist_ok=True)

# start_time = time.time()

# # ======================================================

# os.makedirs(output_dir, exist_ok=True)
# os.makedirs(log_output_dir, exist_ok=True)

# start_time = time.time()

# # ---------- 1. 扫描目标文件夹，提取去后缀的文件名（stem） ----------
# print(f'[1/4] 正在扫描目标文件夹: {target_dir}')
# target_stems = set()
# with os.scandir(target_dir) as it:
#     for entry in it:
#         if entry.is_file():
#             # 文件 → 去掉扩展名，如 001.jpg → 001
#             stem = os.path.splitext(entry.name)[0]
#             target_stems.add(stem)
#         elif entry.is_dir():
#             # 文件夹 → 直接用文件夹名作为 stem
#             target_stems.add(entry.name)

# print(f'      获取到目标名称(stem): {len(target_stems)} 个')

# # ---------- 2. 扫描源文件夹，建立 stem → 源端信息 的映射 ----------
# # source_map: { stem: ('file', 完整文件名) 或 ('dir', 文件夹名) }
# # 注意：同一 stem 可能同时存在 .json 文件和同名文件夹，优先取文件夹
# print(f'[2/4] 正在扫描源文件夹: {source_dir}')
# source_map = {}  # stem -> ('file', name) 或 ('dir', name)
# with os.scandir(source_dir) as it:
#     for entry in it:
#         if entry.is_file():
#             stem = os.path.splitext(entry.name)[0]
#             # 文件夹优先于文件，如果已有文件夹记录则不覆盖
#             if stem not in source_map or source_map[stem][0] != 'dir':
#                 source_map[stem] = ('file', entry.name)
#         elif entry.is_dir():
#             source_map[entry.name] = ('dir', entry.name)

# print(f'      获取到源端条目: {len(source_map)} 个 (文件+文件夹)')

# # ---------- 3. 扫描输出文件夹，获取已存在条目的 stem ----------
# print(f'[3/4] 正在扫描输出文件夹: {output_dir}')
# output_stems = set()
# if os.path.exists(output_dir):
#     with os.scandir(output_dir) as it:
#         for entry in it:
#             if entry.is_file():
#                 output_stems.add(os.path.splitext(entry.name)[0])
#             elif entry.is_dir():
#                 output_stems.add(entry.name)

# print(f'      获取到已输出条目: {len(output_stems)} 个')

# # ---------- 4. 内存极速比对（零网络IO） ----------
# # to_copy: [(stem, kind, source_name), ...]
# to_copy = []
# skipped_names = []   # stem 列表
# not_found_names = [] # stem 列表

# for stem in target_stems:
#     if stem not in source_map:
#         not_found_names.append(stem)
#     elif stem in output_stems:
#         skipped_names.append(stem)
#     else:
#         kind, src_name = source_map[stem]
#         to_copy.append((stem, kind, src_name))

# print(f'\n[4/4] 比对完成：')
# print(f'  需要复制:   {len(to_copy)} 个')
# print(f'  源端缺失:   {len(not_found_names)} 个')
# print(f'  已存在跳过: {len(skipped_names)} 个')

# # 统计源端类型分布
# file_count = sum(1 for _, k, _ in to_copy if k == 'file')
# dir_count = sum(1 for _, k, _ in to_copy if k == 'dir')
# print(f'  其中文件:   {file_count} 个, 文件夹: {dir_count} 个')

# # ---------- 5. 多线程复制 ----------
# stats = {
#     'copied': 0,
#     'failed': 0,
#     'lock': Lock(),
# }


# def copy_task(item):
#     """根据类型选择复制方式：文件用 copy2，文件夹用 copytree"""
#     stem, kind, src_name = item
#     src_path = os.path.join(source_dir, src_name)
#     dst_path = os.path.join(output_dir, src_name)

#     try:
#         if kind == 'dir':
#             shutil.copytree(src_path, dst_path)
#         else:
#             shutil.copy2(src_path, dst_path)
#         with stats['lock']:
#             stats['copied'] += 1
#         return ('copied', stem, kind)
#     except Exception as e:
#         with stats['lock']:
#             stats['failed'] += 1
#         return ('failed', stem, kind, str(e))


# print(f'\n开始复制，线程数: {MAX_WORKERS}')
# total = len(to_copy)
# processed = 0

# with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
#     future_to_item = {
#         executor.submit(copy_task, item): item for item in to_copy
#     }

#     for future in as_completed(future_to_item):
#         processed += 1
#         try:
#             result = future.result()
#             status, stem = result[0], result[1]
#             kind = result[2] if len(result) > 2 else '?'
#         except Exception as exc:
#             stem = '?'
#             print(f'[FAIL] 复制异常: {exc}')
#             print(f'进度: {processed}/{total}')
#             continue

#         type_tag = '📁' if kind == 'dir' else '📄'
#         if status == 'copied':
#             print(f'[OK]  {type_tag} 已复制: {stem}')
#         elif status == 'failed':
#             err = result[3] if len(result) > 3 else ''
#             print(f'[FAIL]{type_tag} 复制失败: {stem} -> {err}')

#         if processed % 10 == 0 or processed == total:
#             print(f'进度: {processed}/{total}')

# # ---------- 导出日志 ----------
# if not_found_names:
#     not_found_file = os.path.join(log_output_dir, NOT_FOUND_LOG_NAME)
#     with open(not_found_file, 'w', encoding='utf-8') as f:
#         for name in sorted(not_found_names):
#             f.write(name + '\n')
#     print(f'\n未找到的清单已导出到: {not_found_file}')

# if skipped_names:
#     skipped_file = os.path.join(log_output_dir, SKIPPED_LOG_NAME)
#     with open(skipped_file, 'w', encoding='utf-8') as f:
#         for name in sorted(skipped_names):
#             f.write(name + '\n')
#     print(f'跳过重名的清单已导出到: {skipped_file}')

# # ---------- 总结 ----------
# cost_time = time.time() - start_time
# print(f'\n总结 (耗时: {cost_time:.2f} 秒):')
# print(f'  成功复制:     {stats["copied"]} 个')
# print(f'  已跳过重名:   {len(skipped_names)} 个')
# print(f'  未找到:       {len(not_found_names)} 个')
# print(f'  失败:         {stats["failed"]} 个')

# if not_found_names:
#     print(f'\n未找到的名称 (前 20 个):')
#     for name in sorted(not_found_names)[:20]:
#         print(f'  - {name}')
#     if len(not_found_names) > 20:
#         print(f'  ... 还有 {len(not_found_names) - 20} 个')