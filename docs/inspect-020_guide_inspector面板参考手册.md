# Inspector Panel — Reference Manual

> **最后更新**: 2026-04-30  
> **关联**：`AGENTS.md` → Inspector module 章节  
> **对应设计文档**：`docs/inspect-010_des_数据检查面板设计.md`（设计阶段，已过期）

---

## 1. 文件清单

```
anylabeling/views/labeling/widgets/inspector/
├── __init__.py                  # 包导出
├── flat_index.py                # FlattenedRecord + FlatIndex（内存索引）
├── validation_engine.py         # 8 条规则 + ValidationEngine
├── issue_list_widget.py         # 问题树形列表 (QTreeWidget)
├── editable_table_widget.py     # 可编辑 QTableView + EditableTableModel
├── rule_config_widget.py        # 规则配置 UI + 共享标签集
├── export_manager.py            # 文件导出 / 拆分 (ExportManager)
└── inspector_panel.py           # 顶层 4-tab QDockWidget 容器
```

| 文件 | 职责 | 阶段 |
|------|------|------|
| `flat_index.py` | 解析 JSON → `FlattenedRecord` 列表；`_by_file` / `_by_label` / `_by_group` 索引；`query()` 多条件查询；`refresh_file()` 单文件增量更新 | Phase 1 |
| `validation_engine.py` | `ValidationRule` 抽象基类 + 8 条内置规则 + `ValidationEngine`(`run()`, `add_rule()`, `remove_rule()`) + `Issue` / `ValidationReport` 数据结构 | Phase 1 |
| `issue_list_widget.py` | `QTreeWidget` — 扫描结果按规则分组、颜色编码（红/黄/蓝）、单击/双击跳转 shape | Phase 1 |
| `editable_table_widget.py` | `QTableView` + `EditableTableModel` — 当前文件 shape 表格，可编辑 label/group_id/description，双击跳转 | Phase 2 |
| `rule_config_widget.py` | 共享标签集编辑器 + 8 条规则 checkbox + 参数编辑器；`build_rules()` 方法构建 `ValidationRule` 列表 | Phase 3 |
| `export_manager.py` | `ExportManager.export()` — 按规则名分目录复制 JSON + 图片（复制，非移动） | Phase 3 |
| `inspector_panel.py` | `QDockWidget` — 4-tab 容器，协调扫描→验证→显示、规则配置变更、导出操作；对外信号 `issue_navigate_requested` / `shape_edit_requested` / `scan_started` / `scan_finished` | 集成 |

---

## 2. 组件依赖图

```
InspectorPanel (QDockWidget)
├── QTabWidget
│   ├── [0] IssueListWidget         ← ValidationReport
│   ├── [1] EditableTableWidget     ← FlattenedRecord[]
│   ├── [2] RuleConfigWidget        ← 共享标签集 + 8 规则行
│   └── [3] 导出面板                ← ValidationReport
├── FlatIndex
│   └── scan_files(json_paths)
│       → _by_file / _by_label / _by_group
├── ValidationEngine
│   └── run(flat_index) → ValidationReport
│       └── 调用每条规则的 check_all()
├── ExportManager
│   └── export(report, output_dir) → ExportResult
│
│ 信号（→ label_widget）
├── issue_navigate_requested(file_path, shape_index)
├── shape_edit_requested(file_path, shape_index, field, value)
├── scan_started()
└── scan_finished(report)

LabelingWidget (label_widget.py)
├── 创建 InspectorPanel()
├── 连接 issue_navigate_requested → _on_inspector_navigate()
├── 连接 shape_edit_requested    → _on_inspector_shape_edit()
├── _update_inspector_file_list() → set_file_list(json_paths)
├── _refresh_inspector_table()   → refresh_table_from_shapes()
└── 初始标签集 → set_allowed_labels(labels)
```

**横向数据流**：

```
JSON文件列表
  → scan_files() → FlatIndex
    → engine.run() → ValidationReport
      → issue_list.populate() → 问题树显示
      → export_manager.export() → 按规则拆分文件

Canvas.shapes
  → refresh_table_from_shapes() → 表格显示
  → 表格编辑 → shape_edit_requested → Shape修改 → canvas.update()
```

---

## 3. 规则逻辑速查（8 条规则）

| # | 规则名称 / 类 | 检查层级 | 逻辑摘要 | 严重级别 | 参数 | 默认启用 |
|---|-------------|----------|----------|----------|------|----------|
| R1 | `label_in_allowlist`<br>`LabelInAllowlist` | per-shape | label 必须在共享标签集内（空标签报错） | error | 共享标签集 | ✓ |
| R2 | `group_label_uniqueness`<br>`GroupLabelUniqueness` | per-file group | 同一 group_id 内共享标签集中每个标签最多出现 1 次 | error | 共享标签集 | ✓ |
| R3 | `person_rect_requires_group_id`<br>`PersonRectRequiresGroupId` | per-shape | `label=person` + `shape_type=rectangle` → group_id 必须为 int（None / 缺字段报错） | error | 无 | ✓ |
| R4 | `label_shape_type_binding`<br>`LabelShapeTypeBinding` | per-shape | rectangle_labels → 必须 rectangle；point_labels → 必须 point；未绑定标签报 error | error | rectangle_labels, point_labels | ✓ |
| R5 | `group_id_keypoint_integrity`<br>`GroupIdKeypointIntegrity` | per-file group | 有关键点(point)的 group 必须有 person 矩形框 | warning | 无（COCO 17 点硬编码） | ✓ |
| R6 | `required_field_not_empty`<br>`RequiredFieldNotEmpty` | per-shape | label 非空 + points 非空 | error | 无 | ✓ |
| R7 | `group_id_uniqueness`<br>`GroupIdUniqueness` | per-file group | 同一 group_id 内 UNIQUE_TYPES 标签矩形框唯一（默认空，用户自配） | error | unique_types | ✓ |
| R8 | `attribute_consistency`<br>`AttributeConsistency` | per-shape | 关键点 difficult 标志 / orphan_head flag 一致性 | warning | 无 | ✗ |

**规则级别说明**：
- `per-shape`：实现 `check(record, all_records, index)` → 每个 shape 独立检查
- `per-file group`：实现 `check_all(index)`，遍历 `index._by_file` 内的 group 聚合

---

## 4. 新增规则的操作步骤

> 以新增一条名为 `my_rule` 的 per-shape 规则为例。

### Step 1 — `validation_engine.py` 添加规则类

```python
class MyRule(ValidationRule):
    """检查 xxx 条件。"""
    name = "my_rule"
    severity = "error"
    description = "规则描述（显示在 UI 中）"

    def __init__(self, param1: Set[str]):
        self.param1 = param1

    def check(self, record, all_records, index):
        if record.label in self.param1 and record.points_count < 3:
            return Issue(
                rule_name=self.name,
                severity=self.severity,
                message=f"shape #{record.shape_index} 点数不足",
                file_path=record.file_path,
                shape_index=record.shape_index,
                label=record.label,
            )
        return None
```

### Step 2 — `rule_config_widget.py` 注册到 `_RULE_REGISTRY`

```python
{
    "name": "my_rule",
    "display": "我的规则",
    "description": "检查 xxx 条件",
    "severity": "error",
    "default_on": True,
    "params": {
        "param1": ("参数1", "default,values", "csv"),
    },
},
```

### Step 3 — `rule_config_widget.py` 在 `_instantiate_rule` 添加分支

```python
if rule_name == "my_rule":
    val = self._read_param(rule_name, "param1", "default,values")
    return MyRule(val)
```

### Step 4 — 更新导入

- `rule_config_widget.py`：`from .validation_engine import ..., MyRule`
- `inspector_panel.py`：无需改（引擎通过 `rule_config.build_rules()` 构建）
- `__init__.py`：无需改（规则类不对外暴露）

### 如果是 per-group 规则

额外重写 `check_all(self, index: FlatIndex) -> List[Issue]`，并在 `check(self, record, all_records, index)` 中返回 `None`（表示不使用逐条检查）。

---

## 5. 已知限制与待办

| # | 限制 | 影响 | 优先级 |
|---|------|------|--------|
| 1 | `GroupLabelUniqueness` 仅检查**单文件内** group 唯一性，不跨文件 | 需在外部脚本中做跨文件 group 检查 | low |
| 2 | 规则不支持导入/导出为 JSON/YAML | 用户需手动在 UI 中配置 | low |
| 3 | `AttributeConsistency` 目前无用（默认关闭） | 无影响 | — |
| 4 | 表格编辑时，`label_list` 侧边栏不会自动更新（需下次 selection_changed 事件触发） | 侧边栏可能显示旧标签名 | low |
| 5 | 导出功能无进度条（大量文件时界面可能卡顿） | 用户体验 | low |
| 6 | `RuleConfigWidget._read_param` 通过 `findChildren` 定位 QLineEdit，依赖子控件顺序 | 如有人改动 UI 顺序会出错 | low |
| 7 | 扫描不支持进度回调（大目录无反馈） | 用户等待时无视觉反馈 | medium |

---

## 6. 信号流汇总

### 扫描→显示
```
用户点击"扫描" → rescan_requested
  → InspectorPanel.run_scan()
    → FlatIndex.scan_files(paths)
    → ValidationEngine.run(flat_index) → ValidationReport
    → IssueListWidget.populate(report)
    → 更新导出按钮状态
```

### 点击问题→跳转
```
IssueListWidget.issue_clicked(file_path, shape_index)
  → InspectorPanel.issue_navigate_requested.emit()
    → LabelingWidget._on_inspector_navigate(file_path, shape_index)
      → _json_path_to_image(json_path) → 图片路径
      → 如已是当前文件 → 直接选中 shape + 居中
      → 如需切换文件 → setCurrentItem() → load_file() → 选中 shape + 居中
```

### 表格编辑→Shape 同步
```
EditableTableModel.setData(index, value)
  → edit_callback(file_path, shape_index, field, value)
    → InspectorPanel.shape_edit_requested.emit()
      → LabelingWidget._on_inspector_shape_edit()
        → 修改 Shape.label / group_id / description
        → set_dirty() + canvas.update()
        → 150ms 防抖 → _refresh_inspector_table()
```

### 文件列表同步
```
file_search_changed() / import_image_folder()
  → _update_inspector_file_list()
    → 收集 image_list 对应的 JSON 路径（同目录 + output_dir）
    → InspectorPanel.set_file_list(json_paths)
```

---

## 7. 集成点

| 调用方 | 调用 | 触发时机 |
|--------|------|----------|
| `label_widget.py:200` | `InspectorPanel()` | 构造 |
| `label_widget.py:210` | `set_allowed_labels(labels)` | 初始化标签配置 |
| `label_widget.py:4382` | `set_file_list(json_paths)` | 文件列表变化时 |
| `label_widget.py:4371` | `refresh_table_from_shapes(...)` | `load_file` 结束 / canvas 变更（防抖 150ms） |
| `label_widget.py:4333` | `_on_inspector_shape_edit(...)` | 表格编辑 → Shape 修改 |
| `label_widget.py:4365` | `_schedule_inspector_table_refresh()` | `new_shape` / `shape_moved` / `selection_changed` |
| `label_widget.py:4280` | `_on_inspector_navigate(file_path, shape_index)` | 扫描结果 / 表格行点击 |
| `label_widget.py:4320` | `_json_path_to_image(json_path)` | 导航时 JSON → 图片路径转换 |
| `mainwindow.py` (间接) | `toggle_inspector_panel()` | View 菜单切换面板 |
