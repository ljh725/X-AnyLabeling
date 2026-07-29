# Inspector L1/L2 质检复核队列使用说明

本文档说明当前版本 Inspector 中“普通数据检查”和“L1/L2 质检复核队列”的使用方法。

## 1. 普通数据检查

打开数据集后，进入 `数据检查 (Inspector)` 面板。

可使用以下功能：

| 功能 | 用法 |
|---|---|
| `数据检查` Tab | 点击 `扫描`，运行现有 8 条基础 Inspector 检查规则 |
| `扫描当前` | 对当前文件做增量检查 |
| `导入` | 导入外部检查结果，支持 TSV / CSV / JSON |
| 问题跳转 | 单击或双击问题，跳转到对应文件和 shape |
| `数据表格` Tab | 查看或编辑当前文件中的 label、group_id、description 等字段 |
| `规则配置` Tab | 配置基础 Inspector 检查规则 |
| `导出` Tab | 按问题规则导出相关 JSON 和图片 |

普通数据检查主要用于日常标注结构检查，不等同于 L1/L2 目标框质量复核。

## 2. L1/L2 质检复核队列

L1/L2 质检复核推荐采用：

```text
CLI 全量扫描
  -> Inspector 导入 report.json
  -> 标注员复核和修改
  -> 自动写 review_feedback.tsv
  -> 生成 threshold_suggestion.json
```

### 2.1 第一步：CLI 全量扫描

在项目环境中执行：

```bash
conda activate x-anylabeling-cu12
```

然后运行：

```bash
python scripts/run_l1l2_qc.py ^
  --input D:\your_json_dir ^
  --output D:\qc_output
```

其中：

| 参数 | 说明 |
|---|---|
| `--input` | 标注 JSON 所在目录 |
| `--output` | 质检输出目录 |

运行后，输出目录中会生成：

```text
review.tsv
report.json
```

优先使用 `report.json` 进入 Inspector 复核，因为它包含完整证据、指标和阈值信息。

### 2.2 第二步：导入 Inspector

在 Inspector 面板中：

1. 切换到 `质检复核` Tab。
2. 点击 `导入`。
3. 选择 CLI 生成的 `report.json`。
4. 等待问题队列加载完成。

导入后，队列会显示 L1/L2 issue。点击 issue 会跳转到对应文件和 shape。

如果只导入 `review.tsv`，可以查看和复核问题，但不能生成阈值建议。生成阈值建议必须导入 `report.json`。

### 2.3 第三步：人工复核

标注员查看图像和标注后，对每个 issue 选择复核动作：

| 按钮 | 含义 | 写入 decision |
|---|---|---|
| `已修复` | 已经修改标注问题 | `fixed` |
| `确认错误` | 确认该 issue 是真实错误，但暂未修改 | `confirmed_error` |
| `误报` | 规则判断不适用，该 issue 是误报 | `false_positive` |
| `可接受` | 样本特殊但可以接受 | `acceptable` |
| `需讨论` | 复核员无法判断，需要二次仲裁 | `needs_discussion` |
| `清除` | 清空当前复核结论，回到待复核 | 空 |

点击 `已修复` 前，可以在旁边下拉框选择修复类型：

```text
框 / 标签 / 组ID / 点
```

对应写入：

| 下拉选项 | final_action |
|---|---|
| 框 | `fixed_box` |
| 标签 | `fixed_label` |
| 组ID | `fixed_group_id` |
| 点 | `fixed_points` |

复核动作会自动写入同目录的：

```text
review_feedback.tsv
```

标注员不需要手工编辑 `review_feedback.tsv`。

### 2.4 第四步：修改后复扫当前文件

如果标注员修改了当前文件中的框、点、标签或 group_id，可以点击：

```text
复扫当前
```

复扫只针对当前 issue / 当前文件，不会清空已有复核反馈。

如果某个 issue 在复扫后不再出现，队列会保留原始反馈证据，并将该 issue 标记为复扫后已消失。

### 2.5 第五步：生成阈值建议

完成一轮复核后，点击：

```text
生成建议
```

系统会基于：

```text
report.json + review_feedback.tsv
```

生成：

```text
threshold_suggestion.json
```

注意：

- `threshold_suggestion.json` 只是阈值调整建议。
- `approval.status` 固定为 `pending`。
- 系统不会自动修改 YAML 阈值配置。
- 阈值变更必须经过人工确认。

## 3. 推荐操作流程

完整推荐流程：

```text
1. 使用 CLI 对数据集做全量 L1/L2 扫描
2. 在 Inspector 的“质检复核”Tab 导入 report.json
3. 标注员逐条查看 issue
4. 修改标注或标记误报、可接受、需讨论
5. 系统自动维护 review_feedback.tsv
6. 修改后使用“复扫当前”检查问题是否消失
7. 一轮复核完成后生成 threshold_suggestion.json
8. 人工审核阈值建议，再决定是否更新阈值 YAML
```

## 4. 注意事项

- 大规模首次扫描建议使用 CLI，不建议直接依赖 UI 做全量扫描。
- Inspector 中的 `复扫当前` 适合当前文件或当前 issue 的增量复查。
- `review_feedback.tsv` 由系统自动维护，人工只在 UI 中操作。
- 只导入 `review.tsv` 时不能生成阈值建议。
- 导入 `report.json` 后才能生成 `threshold_suggestion.json`。
- 质检 issue 是“待复核任务”，不是自动判错结论。

