# Rename `_pred.json` 标注文件设计文档

## 目标

提供一个独立脚本，将 JSON 标注目录中所有以 `_pred.json` 结尾的文件，按同名图片的 stem 去掉 `_pred` 后缀后复制到输出目录。没有对应图片的 JSON 文件直接跳过。

## 输入

- `images_dir`: 图片目录，例如 `D:\A0_part1_kps_3_class_dataset\HK-Hard\images`
- `json_dir`: JSON 标注目录，例如 `D:\A0_part1_kps_3_class_dataset\HK-Hard\sort_json_preds_1458`
- `output_dir`: 输出目录
- `--suffix`: JSON 文件名中需要去掉的后缀，默认为 `_pred`
- `--dry-run`: 仅预览，不实际复制
- `--report`: 可选 CSV 报告输出路径

## 输出

- 仅输出重命名后的 JSON 文件到 `output_dir`
- 控制台统计信息
- 可选 CSV 报告

## 重命名规则

| 图片文件 | 原始 JSON 文件 | 输出 JSON 文件 |
|----------|----------------|----------------|
| `0001.jpg` | `0001_pred.json` | `0001.json` |
| `0002.png` | `0002_pred.json` | `0002.json` |
| 无对应图片 | `0003_pred.json` | 跳过 |

## 处理流程

1. 校验 `images_dir`、`json_dir` 为目录，创建 `output_dir`
2. 收集 `images_dir` 中所有图片文件的 stem（忽略扩展名）
3. 遍历 `json_dir` 中的 `.json` 文件，筛选出以 `{suffix}.json` 结尾的文件
4. 对每个候选 JSON 文件：
   - 去掉 `{suffix}` 得到候选 stem
   - 检查候选 stem 是否在图片 stem 集合中
   - 若存在，构造目标文件名 `{stem}.json`
   - 若目标文件已存在，跳过并记录冲突
   - 否则复制 JSON 到输出目录
5. 输出统计信息和报告

## 边界处理

- 目标文件已存在：跳过，记录到报告
- 多个源 JSON 映射到同一个目标名：只处理第一个，后续记录为冲突
- 无对应图片的 JSON：跳过，不计入成功
- 图片目录为空：报错退出

## 命令行示例

```bash
python scripts/rename_pred_jsons.py \
    --images-dir "D:\A0_part1_kps_3_class_dataset\HK-Hard\images" \
    --json-dir "D:\A0_part1_kps_3_class_dataset\HK-Hard\sort_json_preds_1458" \
    --output-dir "D:\A0_part1_kps_3_class_dataset\HK-Hard\renamed_jsons"
```

预览模式：

```bash
python scripts/rename_pred_jsons.py \
    --images-dir "D:\A0_part1_kps_3_class_dataset\HK-Hard\images" \
    --json-dir "D:\A0_part1_kps_3_class_dataset\HK-Hard\sort_json_preds_1458" \
    --output-dir "D:\A0_part1_kps_3_class_dataset\HK-Hard\renamed_jsons" \
    --dry-run
```

## 文件位置

- 实现脚本：`scripts/rename_pred_jsons.py`
