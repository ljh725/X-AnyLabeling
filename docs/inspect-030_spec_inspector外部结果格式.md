# Inspector 外部检测结果导入格式

本文档说明外部脚本如何生成结果文件，以便在 Inspector 的
「数据检查」页通过「导入」按钮统一查看、双击跳转和按规则导出问题。

## 支持的文件类型

Inspector 当前支持导入以下扩展名：

- `.txt`
- `.tsv`
- `.csv`
- `.json`

`.txt` / `.tsv` / `.csv` 都按「带表头的表格文件」解析。`.json`
按 JSON 结构解析。

## 字段定义

每条问题记录建议包含以下字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `file_path` | 是 | 原始标注 JSON 路径。可写完整路径，也可只写文件名。 |
| `shape_index` | 是 | `shapes[]` 中的问题 shape 下标。文件级问题写 `-1`。 |
| `rule_name` | 否 | 规则名。用于 Inspector 分组和导出目录名。默认 `external_result`。 |
| `severity` | 否 | 严重级别：`error` / `warning` / `info`。其他值按 `warning` 处理。 |
| `message` | 否 | 问题描述。为空时显示 `[外部检测] rule_name`。 |
| `label` | 否 | 问题关联的 label，用于详情列显示。 |
| `group_id` | 否 | 问题关联的 group_id，用于详情列显示。 |

`file_path` 也兼容以下字段名：

- `json_path`
- `path`
- `file`
- `filename`

## 路径匹配规则

`file_path` 可以使用三种写法：

1. 完整 JSON 路径：

```text
D:\dataset\labels\000001.json
```

2. 当前 Inspector 文件列表中存在的 JSON 文件名：

```text
000001.json
```

3. 图片文件名或不带扩展名的文件名：

```text
000001.jpg
000001
```

导入器会按 basename 匹配当前 Inspector 已加载的 JSON 文件列表。

## TXT / TSV 格式

`.txt` 和 `.tsv` 推荐使用 Tab 分隔，第一行必须是表头。

```text
file_path	shape_index	rule_name	severity	message	label	group_id
000001.json	3	missing_keypoint	error	关键点缺失	nose	12
000002.json	-1	file_level_warning	warning	该文件人数与预期不一致		
```

说明：

- `shape_index=3` 表示跳转到该 JSON 的第 4 个 shape。
- `shape_index=-1` 表示文件级问题，双击只跳转到文件，不选中特定 shape。
- 空字段可以留空，但分隔符位置要保留。

## CSV 格式

`.csv` 使用英文逗号分隔，第一行必须是表头。

```csv
file_path,shape_index,rule_name,severity,message,label,group_id
000001.json,3,missing_keypoint,error,关键点缺失,nose,12
000002.json,-1,file_level_warning,warning,该文件人数与预期不一致,,
```

如果 `message` 中包含英文逗号，需要用双引号包起来：

```csv
file_path,shape_index,rule_name,severity,message,label,group_id
000003.json,5,invalid_pose,error,"关键点顺序异常, 请检查",l_eye,7
```

## JSON 格式

JSON 支持两种结构。

结构 1：对象中包含 `issues` 列表。

```json
{
  "issues": [
    {
      "file_path": "000001.json",
      "shape_index": 3,
      "rule_name": "missing_keypoint",
      "severity": "error",
      "message": "关键点缺失",
      "label": "nose",
      "group_id": 12
    },
    {
      "file_path": "000002.json",
      "shape_index": -1,
      "rule_name": "file_level_warning",
      "severity": "warning",
      "message": "该文件人数与预期不一致"
    }
  ]
}
```

结构 2：顶层直接是列表。

```json
[
  {
    "file_path": "000001.json",
    "shape_index": 3,
    "rule_name": "missing_keypoint",
    "severity": "error",
    "message": "关键点缺失",
    "label": "nose",
    "group_id": 12
  }
]
```

## 推荐脚本输出方式

外部检测脚本最推荐输出 `.tsv`，因为它简单、可读，并且不容易和中文
描述里的逗号冲突。

Python 示例：

```python
import csv

rows = [
    {
        "file_path": "000001.json",
        "shape_index": 3,
        "rule_name": "missing_keypoint",
        "severity": "error",
        "message": "关键点缺失",
        "label": "nose",
        "group_id": 12,
    }
]

with open("pose_check_result.tsv", "w", encoding="utf-8", newline="") as f:
    fieldnames = [
        "file_path",
        "shape_index",
        "rule_name",
        "severity",
        "message",
        "label",
        "group_id",
    ]
    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
    writer.writeheader()
    writer.writerows(rows)
```

## 导入后的行为

- 导入外部结果会替换当前 Inspector 检查结果。
- 问题列表按 `rule_name` 分组。
- 双击问题时，根据 `file_path + shape_index` 跳转。
- `shape_index=-1` 的文件级问题只跳转文件，不选中特定 shape。
- 导出功能会按 `rule_name` 创建目录，并复制命中的 JSON 和图片。
- 无法匹配到当前文件列表的行会被跳过，跳过原因会显示在摘要提示中。
