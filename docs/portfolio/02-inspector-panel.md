# 02 · Inspector 数据检查面板
#### Inspector Data-Quality Panel

> 一个 5-Tab 的 QDockWidget 工作台，把外部质检脚本的能力搬进标注工具——点击问题点直接跳转 Canvas 上的 shape，形成标注-质检闭环。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

原工作流是一个**断裂的闭环**：

```
标注 → 导出 JSON → 外部 Python 脚本检查 → 手动定位问题文件
                                              ↓
再检查 ← 再导出 ← 逐张打开修复 ← 手动找文件 ←─┘
```

痛点在于：
1. 质检在**外部脚本**，发现的问题无法直接跳转回标注位修复
2. 每次修改后要重新导出、重新跑脚本、重新找文件
3. 规则散落在脚本里，团队成员难以共享和调整

---

## 架构设计

### 5-Tab 工作台

```
┌──────────────────────────────────────────────────────────┐
│ InspectorPanel (QDockWidget)                             │
│ ┌────────┬──────────┬──────────┬──────────┬──────────┐   │
│ │数据检查│ 质检复核 │ 数据表格 │ 规则配置 │  导出    │   │
│ │ Tab#0  │ Tab#1    │ Tab#2    │ Tab#3    │ Tab#4    │   │
│ └────────┴──────────┴──────────┴──────────┴──────────┘   │
│                                                          │
│  IssueList    Quality    Editable     RuleConfig   Export│
│  Widget       Review     Table        Widget       Manager│
│              Widget      Widget                          │
└──────────────────────────────────────────────────────────┘
        │ issue_navigate_requested(file, shape_index)
        ▼
   Canvas 跳转到对应 shape
```

| Tab | 组件 | 职责 |
|-----|------|------|
| 0 数据检查 | `IssueListWidget` | 8 条基础规则验证结果，按规则分组、红/黄/蓝颜色编码 |
| 1 质检复核 | `QualityReviewWidget` | L1/L2 质检复核队列（后插入，置于数据检查之后） |
| 2 数据表格 | `EditableTableWidget` | 当前文件 shape 表格，可编辑 label/group_id/description |
| 3 规则配置 | `RuleConfigWidget` | 8 条规则开关 + 共享标签集编辑 + 参数 UI |
| 4 导出 | 内建 | 按规则名分目录复制 JSON+图片 |

### 信号契约（向上层解耦）

`InspectorPanel` 对外只暴露 4 个 `pyqtSignal`：

```python
# anylabeling/views/labeling/widgets/inspector/inspector_panel.py:156
issue_navigate_requested = QtCore.pyqtSignal(str, int)   # (file_path, shape_index)
shape_edit_requested = QtCore.pyqtSignal(str, int, str, object)  # 表格编辑回调
scan_started = QtCore.pyqtSignal()
scan_finished = QtCore.pyqtSignal(object)
```

**关键工程亮点**：质检复核 Tab 复用既有 `issue_navigate_requested` 通路，docstring 明确写道——

> "reuses the existing issue_navigate_requested path so the panel re-emits it. The parent label_widget needs no changes."

**父级 LabelingWidget 零改动**即可接入新的 L1/L2 复核功能——这是信号契约稳定复用的价值。

---

## 技术亮点

### 1. 插件化规则引擎

新增一条规则只需继承 `ValidationRule` 并实现 `check()`（per-shape）或重写 `check_all()`（per-group/per-file）：

```python
# anylabeling/views/labeling/widgets/inspector/validation_engine.py:77
class ValidationRule(ABC):
    """Abstract base for a validation rule."""
    name: str = ""
    severity: str = "error"
    description: str = ""

    @abstractmethod
    def check(
        self,
        record: FlattenedRecord,
        all_records: List[FlattenedRecord],
        index: FlatIndex,
    ) -> Optional[Issue]:
        """Check a single record. Return an Issue if a problem is found."""
        ...

    def check_all(self, index: FlatIndex) -> List[Issue]:
        """Default: iterate every record. Override for batch checks."""
        ...
```

双层级设计：`check()` 用于单个 shape 的独立检查（如标签白名单），`check_all()` 用于跨 shape/跨文件的批量检查（如 group_id 唯一性）。

### 2. 8 条内置验证规则

| # | 规则类 | 检查层级 | 简介 | 严重级 |
|---|--------|---------|------|--------|
| R1 | `LabelInAllowlist` | per-shape | label 必须在共享标签集内 | error |
| R2 | `GroupLabelUniqueness` | per-group | 同一 group_id 内标签不可重复 | error |
| R3 | `PersonRectRequiresGroupId` | per-shape | person 矩形框 group_id 必须为 int | error |
| R4 | `LabelShapeTypeBinding` | per-shape | label 必须匹配预期 shape_type | error |
| R5 | `GroupIdKeypointIntegrity` | per-group | 有关键点的 group 必须有 person | warning |
| R6 | `RequiredFieldNotEmpty` | per-shape | label + points 非空 | error |
| R7 | `GroupIdUniqueness` | per-group | 可配唯一类型（默认空） | error |
| R8 | `AttributeConsistency` | per-shape | difficult/orphan_head 一致性 | warning |

### 3. 三维内存索引

`FlatIndex` 维护三个维度的索引，支撑批量扫描无需数据库：

```python
_by_file:  Dict[file_path, List[FlattenedRecord]]   # 按文件
_by_label: Dict[label, List[FlattenedRecord]]        # 按标签
_by_group: Dict[(file_path, group_id), List[...]]    # 按分组
```

支持 500~1000 文件/批次（~30K 记录）的快速扫描与过滤。

### 4. 数据闭环

```
扫描(scan) → 验证(validate) → 显示(display) → 跳转修复(navigate)
    ↑                                              │
    └───────── 编辑回写(edit) ← 重扫(rescan) ←──────┘
```

标注员在 Inspector 发现问题 → 点击跳转 Canvas → 修复 shape → 单文件重扫验证 → 确认解决。整个过程不出标注工具。

---

## 代码定位

| 文件 | 行数 | 职责 |
|------|------|------|
| [`inspector/inspector_panel.py`](../../anylabeling/views/labeling/widgets/inspector/inspector_panel.py) | 1078 | 顶层 QDockWidget 容器，5-Tab，扫描→验证→显示调度 |
| [`inspector/validation_engine.py`](../../anylabeling/views/labeling/widgets/inspector/validation_engine.py) | 732 | ValidationRule ABC + 8 条规则 + ValidationEngine |
| [`inspector/quality_review_widget.py`](../../anylabeling/views/labeling/widgets/inspector/quality_review_widget.py) | 660 | L1/L2 质检复核队列 widget（Tab#1） |
| [`inspector/rule_config_widget.py`](../../anylabeling/views/labeling/widgets/inspector/rule_config_widget.py) | 530 | 共享标签集 + 规则开关 + 参数 UI |
| [`inspector/issue_list_widget.py`](../../anylabeling/views/labeling/widgets/inspector/issue_list_widget.py) | 272 | QTreeWidget 问题列表（颜色编码+点击跳转） |
| [`inspector/editable_table_widget.py`](../../anylabeling/views/labeling/widgets/inspector/editable_table_widget.py) | 275 | QTableView 当前文件 shape 表格 |
| [`inspector/flat_index.py`](../../anylabeling/views/labeling/widgets/inspector/flat_index.py) | 281 | FlattenedRecord + FlatIndex（三维索引） |
| [`inspector/external_result_importer.py`](../../anylabeling/views/labeling/widgets/inspector/external_result_importer.py) | 256 | 外部质检结果 JSON 导入 |
| [`inspector/export_manager.py`](../../anylabeling/views/labeling/widgets/inspector/export_manager.py) | 191 | 按规则名分目录导出 |
| [`inspector/quality_scan_worker.py`](../../anylabeling/views/labeling/widgets/inspector/quality_scan_worker.py) | 95 | L1/L2 后台扫描 worker（QThread） |

**合计：~3,785 行**（不含 `quality/` 子包）

---

## 测试覆盖

| 测试文件 | 用例数 |
|---------|--------|
| [`tests/test_inspector_validation.py`](../../tests/test_inspector_validation.py) | 18 |
| [`tests/test_inspector_scan.py`](../../tests/test_inspector_scan.py) | 9 |
| [`tests/test_inspector_direct.py`](../../tests/test_inspector_direct.py) | — |
| [`tests/test_inspector_standalone.py`](../../tests/test_inspector_standalone.py) | — |
| [`tests/test_quality_review_widget.py`](../../tests/test_quality_review_widget.py) | 15 |
| [`tests/test_quality_review_queue.py`](../../tests/test_quality_review_queue.py) | 25 |

（质检引擎相关测试见 [模块 01](01-quality-engine.md)）

---

## 设计文档

- [`docs/data-inspector-panel-design.md`](../data-inspector-panel-design.md) — 设计动机与架构
- [`docs/inspector-panel-reference.md`](../inspector-panel-reference.md) — Inspector 速查手册
- [`docs/Inspector_L1_L2质检复核队列使用说明.md`](../Inspector_L1_L2质检复核队列使用说明.md) — 质检复核使用说明

---

## 截图

> `[截图待补]` — 计划补充：Inspector 5-Tab 全景、问题列表点击跳转、规则配置面板、数据表格编辑
