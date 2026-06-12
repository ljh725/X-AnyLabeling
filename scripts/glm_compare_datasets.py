# import os

# # ==========================================
# # 📌 配置区 (请在这里修改你的路径)
# # ==========================================

# # 本地第一部分的文件夹路径 (支持多个文件夹，用逗号隔开，写在方括号里)
# PATHS_LOCAL_FOLDERS = [
#     r"D:\A0_part1_kps_3_class_dataset\Hard\iamges",
#     r"D:\A0_part1_kps_3_class_dataset\images\images",
#     r"D:\A0_part1_kps_3_class_dataset\Sample\images",
#     r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\A1_personHead1-4\images_18442",
#     r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\PETS09-S2L1\PETS09_image_794",
#     r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\PRW\PRW_image_11792",
#     r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\TUD-Campus\TUD-Campus_iamge_248"
# ]

# # 服务器第一部分 (存放点2) 的文件夹路径 (现在也支持多个文件夹)
# PATHS_SERVER_FOLDERS = [
#     # r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\A1_personHead1-4\images_18442",
#     # r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\PETS09-S2L1\PETS09_image_794",
#     # r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\PRW\PRW_image_11792",
#     # r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\TUD-Campus\TUD-Campus_iamge_248"

#     r"D:\A4_date_set\A0_三类标注_PersonFaceHead_69407_总数据\images"

# ]
# # 注意：请将 sub_folder_1, sub_folder_2 替换为你服务器上实际拆分的子文件夹名称！
# # 如果图片直接就在 images 目录下散落着，没有子文件夹，请把路径写为 r"\\192.168.3.248\opt\chengdu\PersonFaceHead_cocoPartBETHs_2.0_38122\images"

# # 结果保存的文件夹路径
# OUTPUT_DIR = r"D:\A000_report_txt"

# # 结果文件名定义
# FILE_ONLY_IN_LOCAL = "本地独有_服务器没有_03.txt"
# FILE_ONLY_IN_SERVER = "服务器独有_本地没有_03.txt"
# FILE_IN_BOTH = "两边共有_03.txt"
# FILE_LOCAL_INTERNAL_DUPS = "本地内部重复记录_03.txt"
# FILE_SERVER_INTERNAL_DUPS = "服务器内部重复记录_03.txt" # 新增：服务器查重记录

# # ==========================================
# # 🚀 逻辑执行区 (一般无需修改)
# # ==========================================

# def get_stem_names_from_dirs(folder_paths):
#     """
#     从多个文件夹中提取文件名（去后缀）。
#     返回：去重后的文件名集合，以及未去重时的重复记录
#     """
#     all_names = set()
#     seen_stems = {}  # 用于记录文件名出现的来源文件夹，查重用
#     duplicate_records = [] # 记录重复详情
    
#     for folder_path in folder_paths:
#         if not os.path.exists(folder_path):
#             print(f"⚠️ 警告: 路径不存在，已跳过 {folder_path}")
#             continue
            
#         folder_name = os.path.basename(folder_path)
#         for f in os.listdir(folder_path):
#             full_path = os.path.join(folder_path, f)
#             if os.path.isfile(full_path):
#                 if f.startswith('.'): # 忽略隐藏文件
#                     continue
#                 stem = os.path.splitext(f)[0]
#                 all_names.add(stem)
                
#                 # 查重逻辑：如果这个文件名之前见过
#                 if stem in seen_stems:
#                     duplicate_records.append(f"重复文件名: {stem} | 当前位于: {folder_name} | 之前位于: {seen_stems[stem]}")
#                 else:
#                     seen_stems[stem] = folder_name

#     return all_names, duplicate_records

# def save_list_to_txt(data_list, filepath):
#     """将列表按行写入 txt 文件"""
#     with open(filepath, 'w', encoding='utf-8') as f:
#         for item in sorted(data_list):
#             f.write(f"{item}\n")

# def main():
#     # 1. 读取并合并本地数据
#     print("⏳ 正在读取本地第一部分 (3个文件夹)...")
#     set_local, local_dups = get_stem_names_from_dirs(PATHS_LOCAL_FOLDERS)
#     print(f"✅ 本地去重后的唯一文件名数: {len(set_local)}")
#     if local_dups:
#         print(f"🚨 警告: 本地文件夹之间存在 {len(local_dups)} 处同名文件重叠！")

#     # 2. 读取并合并服务器数据
#     print("\n⏳ 正在读取服务器第一部分 (2个文件夹)...")
#     set_server, server_dups = get_stem_names_from_dirs(PATHS_SERVER_FOLDERS)
#     print(f"✅ 服务器去重后的唯一文件名数: {len(set_server)}")
#     if server_dups:
#         print(f"🚨 警告: 服务器文件夹之间存在 {len(server_dups)} 处同名文件重叠！")

#     # 3. 核心对比
#     only_in_local = set_local - set_server
#     only_in_server = set_server - set_local
#     in_both = set_local & set_server

#     print("\n" + "="*40)
#     print("📊 本地 VS 服务器 对比结果统计:")
#     print(f"本地独有 (差集): {len(only_in_local)} 个")
#     print(f"服务器独有 (差集): {len(only_in_server)} 个")
#     print(f"两边共有 (交集): {len(in_both)} 个")
#     print("="*40 + "\n")

#     # 4. 保存结果
#     if not os.path.exists(OUTPUT_DIR):
#         os.makedirs(OUTPUT_DIR)
#         print(f"📁 已自动创建输出目录: {OUTPUT_DIR}")

#     print("⏳ 正在保存对比结果到 TXT 文件...")
#     save_list_to_txt(only_in_local, os.path.join(OUTPUT_DIR, FILE_ONLY_IN_LOCAL))
#     save_list_to_txt(only_in_server, os.path.join(OUTPUT_DIR, FILE_ONLY_IN_SERVER))
#     save_list_to_txt(in_both, os.path.join(OUTPUT_DIR, FILE_IN_BOTH))
    
#     if local_dups:
#         save_list_to_txt(local_dups, os.path.join(OUTPUT_DIR, FILE_LOCAL_INTERNAL_DUPS))
#         print(f"⚠️ 本地内部重复详情已保存至: {FILE_LOCAL_INTERNAL_DUPS}")
    
#     if server_dups:
#         save_list_to_txt(server_dups, os.path.join(OUTPUT_DIR, FILE_SERVER_INTERNAL_DUPS))
#         print(f"⚠️ 服务器内部重复详情已保存至: {FILE_SERVER_INTERNAL_DUPS}")

#     print(f"\n✅ 全部保存完毕！请前往以下路径查看: {OUTPUT_DIR}")

# if __name__ == "__main__":
#     main()



import os

# ==========================================
# 📌 配置区 (请在这里修改你的路径)
# ==========================================

# 本地第一部分的文件夹路径 (支持多个文件夹，用逗号隔开，写在方括号里)
PATHS_LOCAL_FOLDERS = [
        r"\\192.168.3.248\opt\chengdu\cls3pose_cly\cls3pose_v1\train\images",
        r"\\192.168.3.248\opt\chengdu\cls3pose_cly\cls3pose_v1\test\images"

]

# 服务器第一部分 (存放点2) 的文件夹路径 (现在也支持多个文件夹)
PATHS_SERVER_FOLDERS = [
    # r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\A1_personHead1-4\images_18442",
    # r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\PETS09-S2L1\PETS09_image_794",
    # r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\PRW\PRW_image_11792",
    # r"D:\A0_part2_kps_3_class_dataset\Phase_2_1217_personheadface_points_33076\TUD-Campus\TUD-Campus_iamge_248"

    r"D:\A0_part1_kps_3_class_dataset\hard-111\images",
    r"D:\A0_part1_kps_3_class_dataset\HK-Hard\images",
    r"D:\A0_part1_kps_3_class_dataset\HK-Sample\images",
    r"D:\A0_part1_kps_3_class_dataset\images\images"

]

# 结果保存的文件夹路径
OUTPUT_DIR = r"D:\A000_report_txt"

# 结果文件名定义
FILE_ONLY_IN_LOCAL = "本地独有_服务器没有_0609.txt"
FILE_ONLY_IN_SERVER = "服务器独有_本地没有_0609.txt"
FILE_IN_BOTH = "两边共有_0609.txt" # 建议也带上_03保持一致
FILE_LOCAL_INTERNAL_DUPS = "本地内部重复记录_1913.txt"
FILE_SERVER_INTERNAL_DUPS = "服务器内部重复记录_69407.txt"

# ==========================================
# 🚀 逻辑执行区 (一般无需修改)
# ==========================================

def get_stem_names_from_dirs(folder_paths):
    """
    从多个文件夹中提取文件名（去后缀）及绝对路径。
    返回：
        - all_names: 去重后的文件名集合
        - duplicate_records: 重复详情列表
        - stem_to_path: 文件名到绝对路径的映射字典
    """
    all_names = set()
    seen_stems = {}           # 记录文件名第一次出现时的绝对路径，用于查重比对
    duplicate_records = []    # 记录重复详情
    stem_to_path = {}         # 记录文件名最终的绝对路径映射
    
    for folder_path in folder_paths:
        if not os.path.exists(folder_path):
            print(f"⚠️ 警告: 路径不存在，已跳过 {folder_path}")
            continue
            
        # 统一转为绝对路径，防止相对路径混乱
        abs_folder_path = os.path.abspath(folder_path)
            
        for f in os.listdir(abs_folder_path):
            full_path = os.path.join(abs_folder_path, f)
            if os.path.isfile(full_path):
                if f.startswith('.'): # 忽略隐藏文件
                    continue
                
                stem = os.path.splitext(f)[0]
                all_names.add(stem)
                stem_to_path[stem] = full_path # 更新映射路径（如果有重名，保留最后遍历到的）
                
                # 查重逻辑
                if stem in seen_stems:
                    duplicate_records.append(f"重复文件名: {stem} | 当前路径: {full_path} | 之前路径: {seen_stems[stem]}")
                else:
                    seen_stems[stem] = full_path

    return all_names, duplicate_records, stem_to_path

def save_list_to_txt(data_list, filepath):
    """将列表按行写入 txt 文件"""
    with open(filepath, 'w', encoding='utf-8') as f:
        for item in sorted(data_list):
            f.write(f"{item}\n")

def main():
    # 1. 读取并合并本地数据
    print("⏳ 正在读取本地第一部分 (3个文件夹)...")
    set_local, local_dups, local_path_map = get_stem_names_from_dirs(PATHS_LOCAL_FOLDERS)
    print(f"✅ 本地去重后的唯一文件名数: {len(set_local)}")
    if local_dups:
        print(f"🚨 警告: 本地文件夹之间存在 {len(local_dups)} 处同名文件重叠！")

    # 2. 读取并合并服务器数据
    print("\n⏳ 正在读取服务器第一部分 (2个文件夹)...")
    set_server, server_dups, server_path_map = get_stem_names_from_dirs(PATHS_SERVER_FOLDERS)
    print(f"✅ 服务器去重后的唯一文件名数: {len(set_server)}")
    if server_dups:
        print(f"🚨 警告: 服务器文件夹之间存在 {len(server_dups)} 处同名文件重叠！")

    # 3. 核心对比
    only_in_local = set_local - set_server
    only_in_server = set_server - set_local
    in_both = set_local & set_server

    print("\n" + "="*40)
    print("📊 本地 VS 服务器 对比结果统计:")
    print(f"本地独有 (差集): {len(only_in_local)} 个")
    print(f"服务器独有 (差集): {len(only_in_server)} 个")
    print(f"两边共有 (交集): {len(in_both)} 个")
    print("="*40 + "\n")

    # 4. 格式化输出列表：将文件名与绝对路径拼接
    # 格式： 文件名    绝对路径 (中间是Tab键，方便复制到Excel分列)
    only_in_local_list = sorted([f"{stem}\t{local_path_map.get(stem, '路径丢失')}" for stem in only_in_local])
    only_in_server_list = sorted([f"{stem}\t{server_path_map.get(stem, '路径丢失')}" for stem in only_in_server])
    in_both_list = sorted([f"{stem}\t{local_path_map.get(stem, '路径丢失')}" for stem in in_both]) # 共有的以本地路径为例

    # 5. 保存结果
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"📁 已自动创建输出目录: {OUTPUT_DIR}")

    print("⏳ 正在保存对比结果到 TXT 文件...")
    save_list_to_txt(only_in_local_list, os.path.join(OUTPUT_DIR, FILE_ONLY_IN_LOCAL))
    save_list_to_txt(only_in_server_list, os.path.join(OUTPUT_DIR, FILE_ONLY_IN_SERVER))
    save_list_to_txt(in_both_list, os.path.join(OUTPUT_DIR, FILE_IN_BOTH))
    
    if local_dups:
        save_list_to_txt(local_dups, os.path.join(OUTPUT_DIR, FILE_LOCAL_INTERNAL_DUPS))
        print(f"⚠️ 本地内部重复详情已保存至: {FILE_LOCAL_INTERNAL_DUPS}")
    
    if server_dups:
        save_list_to_txt(server_dups, os.path.join(OUTPUT_DIR, FILE_SERVER_INTERNAL_DUPS))
        print(f"⚠️ 服务器内部重复详情已保存至: {FILE_SERVER_INTERNAL_DUPS}")

    print(f"\n✅ 全部保存完毕！请前往以下路径查看: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
