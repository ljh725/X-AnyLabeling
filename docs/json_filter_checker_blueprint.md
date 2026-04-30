# JSON 筛选与规则检查功能 — 实施蓝图

> 版本: 1.0 / 2026-04-30
> 状态: 设计阶段

---

## 1. 业务目标

在 X-AnyLabeling 标注软件中增加一个"JSON 筛选与规则检查"功能，实现：

1. 把当前目录下所有 JSON 标注文件参数化，像 MySQL/Excel 一样查看
2. 支持两层数据视图：文件层、shape 层
3. 支持多字段筛选，第一版条件关系用 AND
4. 支持数据规则检查和问题发现
5. 筛选结果可直接投射到主界面文件列表
6. 用户基于筛选结果继续修改标注，修改后自动刷新结果

---

## 2. 功能入口

- 放在 `Tool` 菜单，名称：`JSON Filter & Checker`
- 打开方式：独立对话框/工具窗口
- 快捷键：后续版本增加

---

## 3. 数据模型

### 3.1 扫描范围

当前打开目录下所有 JSON 标注文件（每张图片对应的 `.json`）。

### 3.2 表设计

内部按关系模型组织，展示按扁平表。

#### 3.2.1 文件表 `files`

一行一个 JSON 文件。

| 字段 | 类型 | 说明 |
|------|------|------|
| `file_id` | int | 自增主键 |
| `file_name` | str | 文件名（不含路径） |
| `file_path` | str | 完整路径 |
| `version` | str/none | 格式版本号 |
| `shape_count` | int | shape 总数 |
| `group_count` | int | distinct group_id 数量 |
| `label_set` | str | 包含的所有标签（逗号分隔） |
| `shape_type_set` | str | 包含的 shape_type（逗号分隔） |
| `flags_json` | str/none | 文件级 flags |
| `has_issue` | bool | 是否有规则问题 |
| `issue_count` | int | 规则问题数量 |

#### 3.2.2 Shape 表 `shapes`

一行一个 shape。

| 字段 | 类型 | 说明 |
|------|------|------|
| `shape_id` | int | 自增主键 |
| `file_id` | int | 所属文件 |
| `file_name` | str | 文件名（冗余便于扁平表查询） |
| `file_path` | str | 完整路径（冗余便于定位） |
| `shape_index` | int | 在原文件 shapes 列表中的索引 |
| `label` | str | 标签名 |
| `group_id` | int/none | 分组 ID |
| `description` | str/none | 描述 |
| `shape_type` | str | 形状类型（point/rectangle/polygon 等） |
| `points_count` | int | point 数量 |
| `points_json` | str | 原始 points（JSON 字符串，供查看） |
| `points_xmin` | float/none | 派生：points x 最小值 |
| `points_xmax` | float/none | 派生：points x 最大值 |
| `points_ymin` | float/none | 派生：points y 最小值 |
| `points_ymax` | float/none | 派生：points y 最大值 |
| `flags_json` | str | flags（JSON 字符串） |
| `flags_is_empty` | bool | 派生：flags 是否为空 |
| `mask_is_null` | bool | 派生：mask 是否为 null |

#### 3.2.3 问题表 `issues`

一行一条规则问题。

| 字段 | 类型 | 说明 |
|------|------|------|
| `issue_id` | int | 自增主键 |
| `file_id` | int | 所属文件 |
| `file_name` | str | 文件名 |
| `file_path` | str | 完整路径 |
| `rule_code` | str | 规则标识 |
| `rule_name` | str | 规则名称（中文） |
| `severity` | str | 严重级别：error / warning / info |
| `group_id` | int/none | 涉及的分组（可空） |
| `shape_index` | int/none | 涉及的 shape 索引（可空） |
| `shape_type` | str/none | 涉及的 shape 类型（可空） |
| `label` | str/none | 涉及的标签（可空） |
| `message` | str | 问题描述 |
| `fixed` | bool | 是否已修复（运行时实时更新） |

---

## 4. 筛选系统

### 4.1 条件表达式

第一版统一支持：目标表 + 条件列表 + 多条件 AND。

每条条件：

```yaml
{
  "field": "shape_type",
  "operator": "equals",
  "value": "point"
}
```

### 4.2 操作符

#### 文本字段

| 操作符 | 说明 |
|--------|------|
| `equals` | 等于 |
| `not_equals` | 不等于 |
| `contains` | 包含 |
| `starts_with` | 以...开头 |
| `ends_with` | 以...结尾 |
| `is_empty` | 为空 |
| `is_not_empty` | 不为空 |

#### 数值字段

| 操作符 | 说明 |
|--------|------|
| `equals` | 等于 |
| `not_equals` | 不等于 |
| `greater_than` | 大于 |
| `greater_equal` | 大于等于 |
| `less_than` | 小于 |
| `less_equal` | 小于等于 |

#### 布尔字段

| 操作符 | 说明 |
|--------|------|
| `is_true` | 为真 |
| `is_false` | 为假 |

### 4.3 可直接筛选的字段

- 文件表：`file_name`、`shape_count`、`group_count`、`version`
- Shape 表：`label`、`group_id`、`description`、`shape_type`、`points_count`
- Shape 派生字段：`mask_is_null`、`flags_is_empty`
- 问题表：`rule_code`、`severity`、`group_id`、`label`、`message`

### 4.4 复杂字段的处理

对于 `points`、`flags` 等 JSON 嵌套字段，第一版通过派生字段覆盖常见需求：

- `points_*_min/max`（坐标范围）
- `flags_is_empty`
- `mask_is_null`

后续版本可增加：`json_text contains "xxx"`。

---

## 5. 规则检查系统

### 5.1 架构

规则检查器采用插件式设计：

- 一个抽象基类 `BaseRule`
- 每个规则继承基类，实现 `check()` 方法
- 规则注册表：`RuleRegistry`
- 执行入口：`RuleEngine.run_all()`

### 5.2 内置规则（第一版）

| 规则码 | 名称 | 说明 |
|--------|------|------|
| `label_illegal` | 标签不合法 | label 不在允许标签集合中 |
| `label_shape_mismatch` | 标签与 shape 类型不匹配 | 某标签应是 point 却是 rectangle 等 |
| `group_label_duplicate` | 组内标签重复 | 同一 group_id 下某标签出现多次 |
| `group_missing_label` | 组内标签缺失 | 某 group_id 缺少必须标签 |
| `file_missing_required_label` | 文件缺少必须标签 | 文件中不包含必须标签 |
| `description_invalid` | 描述值异常 | description 不符合预期规则 |

### 5.3 规则配置

规则通过可配置的 YAML 参数控制，不做成写死在代码里的检查：

```yaml
rules:
  label_illegal:
    enabled: true
    allowed_labels: ["person", "nose", "l_eye", "r_eye", ...]
  group_label_duplicate:
    enabled: true
    check_labels: ["person"]
  group_missing_label:
    enabled: true
    required_labels_by_group: ["person"]
  label_shape_mismatch:
    enabled: true
    mapping:
      person: "rectangle"
      nose: "point"
      # ...
```

---

## 6. UI 方案

### 6.1 窗口布局

```
┌─────────────────────────────────────────────────┐
│  JSON Filter & Checker                          │
├───────────────────┬─────────────────────────────┤
│ 数据范围          │  Tab: 文件 | Shape | 问题   │
│ 源目录: xxx      │                             │
│ [重新扫描] [自动] │  ┌───────────────────────┐  │
│                   │  │ row1 | file1 | ...    │  │
│ 筛选条件          │  ├───────────────────────┤  │
│ ┌──────┬────┬───┐ │  │ row2 | file2 | ...    │  │
│ │label │ =  │car│ │  ├───────────────────────┤  │
│ │group │ =  │3  │ │  │ ...                   │  │
│ └──────┴────┴───┘ │  └───────────────────────┘  │
│ [+ 增加条件]      │                             │
│                   │  匹配: X 行                 │
│ 规则检查          │                             │
│ ☑ 标签不合法      │                             │
│ ☑ 组内标签重复    │                             │
│ ☐ 标签类型不匹配  │                             │
│ [运行规则检查]    │                             │
├───────────────────┴─────────────────────────────┤
│ [投射到文件列表] [清除投射] [导出 CSV]          │
│ [上一个问题] [下一个问题]                       │
└─────────────────────────────────────────────────┘
```

### 6.2 组件说明

- **数据范围区**：显示当前源目录，提供重新扫描按钮
- **筛选条件区**：条件行列表，每行支持：字段选择、操作符选择、值输入
- **规则检查区**：勾选要运行的规则，显示规则运行结果
- **结果表格区**：三个 Tab 分别展示文件、shape、问题结果
- **操作按钮区**：投射到文件列表、清除投射、导出 CSV、上下问题导航

---

## 7. 文件列表投射

### 7.1 投射模式

| 模式 | 说明 |
|------|------|
| 过滤模式 | 文件列表只显示命中的文件 |
| 高亮模式 | 文件列表保留全部，命中项高亮/置顶（后续版本） |

第一版默认用**过滤模式**。

### 7.2 实现要点

1. 投射前保存原始文件列表
2. 将文件列表替换为命中文件
3. 自动切换到第一个命中文件
4. 清除投射时恢复原始文件列表
5. 需要在 label_widget 中增加两个方法：

```python
# 投射筛选结果到文件列表
def apply_file_list_projection(self, hit_paths: set):
    # 保存原始列表
    # 过滤 file_list_widget
    # 重建 fn_to_index

# 清除投射，恢复原始列表
def clear_file_list_projection(self):
    pass
```

---

## 8. 修改后实时刷新

### 8.1 触发时机

当筛选窗口处于激活状态时，每次 `save_labels()` 成功后：

1. 重新解析当前保存的 JSON
2. 增量刷新 `files`、`shapes`、`issues` 中与该文件相关的行
3. 重新应用当前筛选条件
4. 刷新筛选结果表格
5. 刷新文件列表投射

### 8.2 实现方式

筛选窗口监听 `label_widget` 的保存完成信号：

```python
# 在 label_widget 中
file_saved = QtCore.pyqtSignal(str)  # 参数：保存的文件路径

# 在 save_labels() 成功后
self.file_saved.emit(filename)

# 在筛选窗口中
self._label_widget.file_saved.connect(self._on_file_saved)
```

---

## 9. 模块拆分

### 9.1 文件清单

```
anylabeling/views/labeling/
├── widgets/
│   ├── json_filter_checker/
│   │   ├── __init__.py              # 导出
│   │   ├── data_scanner.py          # 扫描 JSON、建表
│   │   ├── data_models.py           # 表定义（files/shapes/issues）
│   │   ├── filter_engine.py         # 条件筛选引擎
│   │   ├── rule_engine.py           # 规则检查引擎
│   │   ├── rules/                   # 规则实现
│   │   │   ├── __init__.py
│   │   │   ├── base_rule.py         # BaseRule 抽象类
│   │   │   ├── label_rules.py       # 标签类规则
│   │   │   └── group_rules.py       # 组级规则
│   │   └── checker_dialog.py        # 主对话框 UI
│   └── __init__.py                  # 增加导出
```

### 9.2 类职责

| 类/模块 | 职责 |
|----------|------|
| `DataScanner` | 扫描目录 JSON → 生成 files/shapes 数据 |
| `DataModels` | 定义 FileRow, ShapeRow, IssueRow 数据类 |
| `FilterEngine` | 接受条件列表 + 数据集 → 返回过滤后行列表 |
| `BaseRule` | 规则抽象基类，定义 check(shapes, config) 接口 |
| `RuleEngine` | 注册规则、按配置运行规则、生成 issues |
| `CheckerDialog` | 主窗口 UI：三表 Tab、条件编辑、规则勾选、操作按钮 |

---

## 10. 分阶段实施

### 阶段 1 — 基础筛选（核心版）

**目标**：JSON → 表 → 筛选 → 结果投射

1. 实现 `DataScanner`，扫描当前目录所有 JSON
2. 实现 `DataModels`，定义 FileRow、ShapeRow
3. 实现 `FilterEngine`，支持多条件 AND
4. 实现 `CheckerDialog`：
   - 文件 Tab
   - Shape Tab
   - 条件编辑
   - 投射到文件列表按钮
5. 接入 `label_widget`：
   - `Tool` 菜单增加入口
   - 增加 `apply_file_list_projection` / `clear_file_list_projection`

**预计改动文件量**：6-7 个新增 + 2 个修改

### 阶段 2 — 规则检查

**目标**：数据检查 → 问题表 → 问题修复

1. 实现 `BaseRule` 和规则系统架构
2. 实现内置规则：
   - `label_illegal`
   - `group_label_duplicate`
   - `group_missing_label`
3. 实现 `RuleEngine`
4. `CheckerDialog` 增加：
   - 规则勾选区
   - 问题 Tab
5. 支持问题结果投射到文件列表

### 阶段 3 — 工作流联动

**目标**：点击结果 → 跳转图片 → 修改 → 自动刷新

1. 点击结果表格行 → 打开对应文件
2. 点击 shape 相关问题行 → 跳转到对应 shape
3. `label_widget` 增加 `file_saved` 信号
4. `CheckerDialog` 监听保存事件，自动增量刷新
5. 提供"上一个问题 / 下一个问题"快速导航
6. 已修复问题自动从问题表移除

---

## 11. 关键设计决策

| 决策 | 方案 | 理由 |
|------|------|------|
| 底层结构 | 关系表（files/shapes/issues） | 扫描一次、多视图复用 |
| 展示结构 | 扁平表（QTableWidget） | 用户最熟悉，实现快 |
| 结果窗口 | 独立 QDialog | 与标注主界面解耦 |
| 文件列表投射 | 过滤模式（只显示命中项） | 最适合"直接修问题文件"场景 |
| 实时刷新 | 监听 save_labels 完成 | 零额外操作，自动联动 |
| 条件关系 | 第一版仅 AND | 覆盖 90% 实际需求 |
| 规则系统 | 插件式 | 扩展方便，不污染主逻辑 |

---

## 12. 风险与假设

| 风险 | 应对 |
|------|------|
| 大量 JSON（数百个）导致扫描慢 | 第一版做全量扫描，后续可加缓存/增量 |
| points 数组差异大（point vs rectangle） | 派生字段统一处理，原始 JSON 存副本备查 |
| 用户 JSON 字段不完全一致 | 扫描器做容错，缺失字段填默认值 |
| 文件列表投射影响现有翻页逻辑 | 明确保存原始列表，投射期间只改变显示 |

---

## 13. 与现有功能的区别

- **现有 SearchBar**：文件名/文本/正则搜索，不解析 JSON 内容
- **现有 Shape filter**：在加载后的当前文件内按 label/group_id 过滤 shape 可见性
- **现有 Overview**：统计汇总，不提供逐条筛选
- **本功能**：跨文件、结构化、多字段筛选 + 规则检查 + 结果驱动修改

---

## 14. 后续扩展方向

- 支持 OR / NOT 条件组合
- 支持保存/加载筛选方案和规则集
- 结果高亮模式（保留全部文件、高亮命中项）
- 可视化条件编辑器
- 支持 `points_json contains` 文本搜索
- 支持自定义脚本规则
- 生成规则检查报告（HTML/PDF）
