# 数据检查面板（Inspector Panel）—— 分阶段实现方案

> **文档版本**: 1.0  
> **创建日期**: 2025-07-18  
> **项目**: X-AnyLabeling v4.0.0-beta.4  
> **状态**: Phase 1 已完成代码骨架，集成进行中

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [整体架构设计](#2-整体架构设计)
3. [Phase 1：只读问题列表 + 点击跳转](#3-phase-1只读问题列表--点击跳转-已完成代码骨架)
4. [Phase 2：可编辑表格 + 双向同步](#4-phase-2可编辑表格--双向同步-计划中)
5. [Phase 3：条件拆分/导出 + 规则配置 UI](#5-phase-3条件拆分导出--规则配置-ui-计划中)
6. [文件清单](#6-文件清单)
7. [集成点说明](#7-集成点说明)

---

## 1. 背景与动机

### 1.1 现有工作流痛点

在 X-AnyLabeling 标注工具中，用户在标注完成后需要执行数据质量检查。当前流程为：

```
标注 → 导出 JSON → 外部 Python 脚本检查 → 手动定位问题文件 → 
在工具中逐张打开修复 → 导出 → 再次检查
```

**典型脚本示例**：`D:\Deepseek\football_field_kps\修复版_标签过滤label_filer_no_invis_dele.py`
- 使用 `ThreadPoolExecutor` 批量处理
- 过滤 `label in ['dele', 'invis']` 且 `shape_type == 'point'` 的 shape
- 复制非 JSON 文件以保持数据集完整性

**核心问题**：
- 需要在工具外部反复执行脚本，效率低下
- 发现问题后无法直接跳转到对应 shape 进行修复
- 无法在编辑标注的同时实时验证数据质量

### 1.2 设计目标

| 维度 | 要求 |
|------|------|
| **性能** | 支持 500~1000 文件/批次（~30K shape 记录），纯内存操作 |
| **可扩展性** | 插件化规则引擎，新增规则无需修改核心代码 |
| **用户体验** | 点击问题 → 自动跳转到对应文件和 shape，支持一键扫描 |
| **无外部依赖** | 纯 Python + PyQt6，无需数据库 |

---

## 2. 整体架构设计

### 2.1 核心概念

```
┌─────────────────────────────────────────────────────┐
│                  InspectorPanel                      │
│  (QDockWidget — 顶层容器，协调扫描→验证→显示流程)      │
│                                                      │
│  ┌────────────────┐  ┌──────────────────┐           │
│  │   FlatIndex    │  │ ValidationEngine │           │
│  │ (内存索引)      │  │   (规则引擎)       │           │
│  │                │  │                  │           │
│  │ • _records     │  │ • LabelInAllowlist│          │
│  │ • _by_file     │  │ • GroupIdUniqueness│         │
│  │ • _by_label    │  │ • KeypointIntegrity│         │
│  │ • _by_group    │  │ • RequiredField    │          │
│  │                │  │ • AttributeConsistency│       │
│  └────────┬───────┘  └────────┬─────────┘           │
│           │                    │                     │
│           └────────┬───────────┘                     │
│                    ▼                                 │
│          ┌──────────────────┐                        │
│          │  IssueListWidget │                        │
│          │  (QTreeWidget)   │                        │
│          │                  │                        │
│          │  点击 → issue_   │                        │
│          │  navigate_requested                       │
│          │  (file_path, idx)│                        │
│          └──────────────────┘                        │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│              LabelingWidget (label_widget.py)        │
│                                                      │
│  _on_inspector_navigate(file_path, shape_index)      │
│    → 切换到目标文件                                   │
│    → 选中目标 shape                                   │
│    → 居中显示                                         │
└─────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
JSON 文件列表
    │
    ▼
[FlatIndex.scan_files()]
    │  逐文件解析 JSON，构建 FlattenedRecord 列表
    │  建立 _by_file, _by_label, _by_group 索引
    ▼
[ValidationEngine.run()]
    │  遍历所有规则，对每个 record 执行 check()
    │  收集 Issue 对象
    ▼
[ValidationReport]
    │  聚合所有 Issue，按规则分组
    ▼
[IssueListWidget.populate()]
    │  渲染为 QTreeWidget（分组树形视图）
    │  颜色编码：error=红色, warning=琥珀色, info=蓝色
    ▼
用户点击某条 Issue
    │  issue_clicked.emit(file_path, shape_index)
    ▼
[LabelingWidget._on_inspector_navigate()]
    → 切换文件 + 选中 shape + 居中
```

### 2.3 性能评估

| 指标 | 估算 |
|------|------|
| 单个 JSON 文件 shapes 平均数量 | ~30 |
| 500 文件总记录数 | ~15,000 |
| 1000 文件总记录数 | ~30,000 |
| 单条 FlattenedRecord 内存占用 | ~750 bytes |
| 30K records 内存总占用 | ~22 MB |
| 扫描 1000 文件耗时（估算） | < 5 秒 |

结论：**完全不需要数据库**，纯 Python 内存字典足够。

---

## 3. Phase 1：只读问题列表 + 点击跳转（已完成代码骨架）

### 3.1 目标

- 用户点击"扫描"按钮 → 扫描当前文件列表中所有 JSON 文件
- 展示按规则分组的、颜色编码的问题列表
- 点击/双击问题项 → 跳转到对应文件和 shape

### 3.2 已创建的文件

#### 3.2.1 `flat_index.py` — 内存索引

**路径**: `anylabeling/views/labeling/widgets/inspector/flat_index.py`

**`FlattenedRecord` 数据类**（12 个字段）:

```python
@dataclass
class FlattenedRecord:
    file_path: str          # JSON 文件绝对路径
    image_path: str         # JSON 中的 imagePath 字段
    shape_index: int        # shapes[] 数组中的索引
    label: str              # 标签名
    shape_type: str         # rectangle/polygon/point/linestrip/circle/rotation
    group_id: Optional[int] # 分组 ID
    flags: Dict[str, Any]   # flags 字典
    attributes: Dict[str, Any] # attributes 字典
    description: str        # 描述文字
    points_count: int       # 坐标点数量
    difficulty: bool        # 是否为难例
```

**`FlatIndex` 类**——核心方法:

| 方法 | 说明 |
|------|------|
| `scan_files(json_paths, progress_callback)` | 批量扫描 JSON 文件，建立索引 |
| `refresh_file(file_path)` | 单文件增量刷新（保存后更新用） |
| `query(label, shape_type, group_id, file_path)` | 多条件查询 |
| `get_unique_labels()` | 获取所有不同标签名 |
| `get_unique_group_ids()` | 获取所有不同 group_id |
| `iter_all()` / `iter_file(file_path)` | 遍历记录 |
| `clear()` | 清空索引 |

内部索引结构:
- `_records: List[FlattenedRecord]` — 全量记录
- `_by_file: Dict[str, List[FlattenedRecord]]` — 按文件分组
- `_by_label: Dict[str, List[FlattenedRecord]]` — 按标签分组
- `_by_group: Dict[int, List[FlattenedRecord]]` — 按 group_id 分组

#### 3.2.2 `validation_engine.py` — 规则引擎

**路径**: `anylabeling/views/labeling/widgets/inspector/validation_engine.py`

**数据类**:

```python
@dataclass
class Issue:
    rule_name: str      # 规则名，如 "label_in_allowlist"
    severity: str       # "error" | "warning" | "info"
    message: str        # 人类可读描述
    file_path: str      # JSON 文件路径
    shape_index: int    # shape 索引（-1 表示文件级问题）
    label: str
    group_id: Optional[int]
    extra: Dict[str, Any]

@dataclass
class ValidationReport:
    total_files: int
    total_records: int
    issues: List[Issue]
    # 计算属性: error_count, warning_count, issue_count
    # 方法: issues_by_rule() → Dict[str, List[Issue]]
```

**`ValidationRule` 抽象基类**:

```python
class ValidationRule(ABC):
    name: str = ""
    severity: str = "error"
    description: str = ""

    @abstractmethod
    def check(self, record, all_records, index) -> Optional[Issue]: ...

    def check_all(self, index) -> List[Issue]: ...  # 默认遍历每条记录
```

**5 个内置规则**:

| # | 规则类 | 严重级别 | 检查内容 |
|---|--------|----------|----------|
| 1 | `LabelInAllowlist` | **error** | 标签名是否在预定义列表中；空标签也报错 |
| 2 | `GroupIdUniqueness` | **error** | 同一 group_id 内 person/head/face 矩形框是否唯一 |
| 3 | `GroupIdKeypointIntegrity` | **warning** | 有关键点(point)的 group 必须有 person 矩形框（检测孤立头） |
| 4 | `RequiredFieldNotEmpty` | **error** | label 和 points 字段非空 |
| 5 | `AttributeConsistency` | **warning** | 关键点 difficult 标志、orphan_head flag 一致性 |

**注意**：规则 1 (`LabelInAllowlist`) 仅在构造时传入了 `allowed_labels` 集合时才会被添加。

**`ValidationEngine` 类**:

```python
class ValidationEngine:
    def __init__(self, rules=None): ...
    def add_rule(rule): ...
    def remove_rule(rule_name): ...
    def run(index: FlatIndex) -> ValidationReport: ...  # 执行所有规则
```

#### 3.2.3 `issue_list_widget.py` — 问题列表 UI

**路径**: `anylabeling/views/labeling/widgets/inspector/issue_list_widget.py`

**UI 布局**:
```
┌──────────────────────────────────┐
│  数据检查                [扫描]  │  ← 标题栏 + 扫描按钮
│  扫描 10 文件 | ✗ 3 错误 | ⚠ 5 警告│  ← 摘要栏
├──────────────────────────────────┤
│ ▼ ✗ label_in_allowlist (2 项)   │  ← 规则分组头（红色加粗）
│   ├ [空标签] shape #5 标签为空    │  ← 问题子项
│   └ [未注册标签] shape #12 ...   │
│ ▼ ✗ group_id_uniqueness (1 项)  │
│   └ [重复类型] group_id=3 ...    │
│ ▼ ⚠ keypoint_integrity (3 项)   │  ← 琥珀色
│   └ [孤立关键点] ...              │
│ ...                             │
└──────────────────────────────────┘
```

**信号**:

| 信号 | 参数 | 说明 |
|------|------|------|
| `issue_clicked` | `(file_path: str, shape_index: int)` | 单击问题行 |
| `issue_double_clicked` | `(file_path: str, shape_index: int)` | 双击问题行 |
| `rescan_requested` | `()` | 点击"扫描"按钮 |

**颜色编码**:

| 严重级别 | 颜色 | 色码 | 图标 |
|----------|------|------|------|
| error | 红色 | `#DC3545` | ✗ |
| warning | 琥珀色 | `#FFC107` | ⚠ |
| info | 蓝色 | `#0D6EFD` | ℹ |

#### 3.2.4 `inspector_panel.py` — 顶层容器

**路径**: `anylabeling/views/labeling/widgets/inspector/inspector_panel.py`

**`InspectorPanel(QDockWidget)`**——协调扫描→验证→显示流程:

```python
class InspectorPanel(QtWidgets.QDockWidget):
    issue_navigate_requested = QtCore.pyqtSignal(str, int)  # 导航信号
    scan_started = QtCore.pyqtSignal()
    scan_finished = QtCore.pyqtSignal(object)  # ValidationReport

    def __init__(self, allowed_labels=None, extra_rules=None, parent=None):
        # 内部持有: FlatIndex, ValidationEngine, IssueListWidget
        ...

    # 公开 API
    def set_file_list(file_paths: List[str]): ...    # 设置待扫描文件列表
    def set_allowed_labels(labels: Set[str]): ...     # 更新标签白名单
    def run_scan(json_paths=None): ...                 # 执行扫描三阶段
    def refresh_file(file_path: str): ...              # 单文件增量刷新
```

**内部流程（`run_scan`）**:
1. **Phase 1 — 索引**: `flat_index.scan_files(paths)` → 解析所有 JSON
2. **Phase 2 — 验证**: `engine.run(flat_index)` → 运行所有规则
3. **Phase 3 — 显示**: `issue_list.populate(report)` → 更新 UI

#### 3.2.5 `__init__.py` — 包导出

**Inspector 子包** (`inspector/__init__.py`):
```python
from .flat_index import FlatIndex, FlattenedRecord
from .validation_engine import ValidationEngine, Issue, ValidationRule
from .issue_list_widget import IssueListWidget
from .inspector_panel import InspectorPanel
```

**Widgets 包** (`widgets/__init__.py` 第 38 行):
```python
from .inspector import InspectorPanel
```

### 3.3 label_widget.py 集成点（已完成）

#### 3.3.1 导入

```python
# 第 100-102 行
from .widgets import (
    ...
    KeypointFillMode,
    KeypointToolWindow,
    InspectorPanel,  # ← 新增
)
```

#### 3.3.2 实例化 + 信号连接

```python
# 第 200-205 行
self.inspector_panel = InspectorPanel(
    allowed_labels=self._config.get("labels", []),
)
self.inspector_panel.issue_navigate_requested.connect(
    self._on_inspector_navigate
)
```

#### 3.3.3 右侧栏布局

```python
# 第 2601-2610 行
self.inspector_panel.setVisible(False)  # 默认隐藏
insp_panel = QFrame()
insp_panel.setObjectName("sidebarPanel")
insp_panel.setStyleSheet(get_panel_style())
insp_panel_layout = QVBoxLayout(insp_panel)
insp_panel_layout.setContentsMargins(0, 0, 0, 0)
insp_panel_layout.setSpacing(0)
insp_panel_layout.addWidget(self.inspector_panel)
right_sidebar_layout.addWidget(insp_panel)
```

> **注意**: 由于 `LabelingWidget` 继承 `LabelDialog`（而非 `QMainWindow`），QDockWidget 作为普通 widget 嵌入 QFrame 显示在右侧栏。dock 的 closable/floatable/movable 特性在此布局中不可用。

#### 3.3.4 导航处理

```python
# 第 4259-4285 行
def _on_inspector_navigate(self, file_path: str, shape_index: int):
    """导航到目标文件和 shape"""
    normalized = str(file_path)

    # 如果目标文件不是当前文件，切换到它
    if str(self.filename) != normalized:
        if normalized in self.fn_to_index:
            idx = self.fn_to_index[normalized]
            item = self.file_list_widget.item(idx)
            if item:
                self.file_list_widget.setCurrentItem(item)
        elif osp.isfile(normalized):
            self.load_file(normalized)

    # 选中目标 shape 并居中
    if shape_index >= 0 and shape_index < len(self.canvas.shapes):
        shape = self.canvas.shapes[shape_index]
        self.canvas.select_shape(shape)         # ⚠ 待验证 API
        self.canvas.zoom_to_selection()         # ⚠ 待验证 API
        self.canvas.highlighted_shape = shape   # ⚠ 应为 h_hape
        self.canvas.update()
```

> **⚠ 已知问题**: `_on_inspector_navigate` 中使用的方法名可能与实际 Canvas API 不匹配：
> - `select_shape()` → Canvas 中不存在此方法，应使用 `selection_changed.emit([shape])`
> - `zoom_to_selection()` → Canvas 中尚未确认存在
> - `highlighted_shape` → Canvas 实际属性名为 `h_hape`

#### 3.3.5 文件列表同步

```python
# 第 4287-4309 行
def _update_inspector_file_list(self):
    """将当前文件列表（image_list）中的 JSON 文件路径同步给 inspector"""
    ...
    # 收集 JSON 路径：
    # 1. 直接的 .json 文件
    # 2. 图片文件对应的同目录 .json 文件
    self.inspector_panel.set_file_list(json_paths)

def toggle_inspector_panel(self):
    """切换 Inspector 面板的可见性"""
    ...
```

#### 3.3.6 菜单集成

```python
# 第 1773-1781 行 — Action 定义
toggle_inspector = action(
    self.tr("Data Inspector"),
    self.toggle_inspector_panel,
    None,
    "eye",
    self.tr("Show/hide the data inspector panel"),
    checkable=True,
    enabled=True,
)

# 第 1922 行 — 添加到 actions 结构体
toggle_inspector=toggle_inspector,

# 第 2225 行 — 添加到 View 菜单
utils.add_actions(
    self.menus.view,
    (
        show_navigator,
        toggle_inspector,  # ← 新增
        fill_drawing,
        ...
    ),
)
```

#### 3.3.7 文件搜索触发同步

```python
# 第 4223-4231 行
def file_search_changed(self):
    search_text = self.file_search.text()
    self.import_image_folder(
        self.last_open_dir,
        pattern=search_text,
        load=False,
    )
    # 同步文件列表到 inspector 面板
    self._update_inspector_file_list()
```

### 3.4 Phase 1 待完成项

| # | 项目 | 说明 |
|---|------|------|
| 1 | **修复 `_on_inspector_navigate` Canvas API 调用** | `select_shape()` → `selection_changed.emit([shape])`<br>`highlighted_shape` → `h_hape`<br>`zoom_to_selection()` 需确认正确方法名 |
| 2 | **验证文件切换后的 shape 选中时序** | 切换到新文件后，`self.canvas.shapes` 可能尚未更新，需要等 `load_file` 完成后再选中 shape |
| 3 | **测试扫描流程** | 用实际数据（如 `historical_code_3.3.8/` 目录）端到端测试 |
| 4 | **菜单 checkable 状态同步** | `toggle_inspector` action 的 checked 状态应与面板可见性保持同步 |

---

## 4. Phase 2：可编辑表格 + 双向同步（计划中）

### 4.1 目标

在 Phase 1 基础上新增：
- 将问题列表扩展为可编辑的表格视图（QTableView + QAbstractTableModel）
- 支持在表格中直接编辑 label、group_id、flags/attributes
- 编辑结果双向同步：表格修改 → Shape 更新 → Canvas 重绘；Canvas 编辑 → 信号 → 表格刷新

### 4.2 设计要点

```
┌─────────────────────────────────────┐
│ InspectorPanel                      │
│  ┌─ Tab: 问题列表 ─────────────────┐│
│  │ IssueListWidget (Phase 1)       ││
│  └─────────────────────────────────┘│
│  ┌─ Tab: 数据表格 ─────────────────┐│
│  │ EditableTableWidget (Phase 2)   ││
│  │                                 ││
│  │  label | gid | type | flags ... ││
│  │  ──────┼─────┼──────┼──────────││
│  │  person│  0  │ rect │ {}       ││
│  │  nose  │  0  │ point│ {}       ││
│  │  ...   │ ... │ ...  │ ...      ││
│  └─────────────────────────────────┘│
└─────────────────────────────────────┘
```

**双向同步策略**:

| 方向 | 触发条件 | 同步路径 |
|------|----------|----------|
| 表格 → Canvas | 用户编辑单元格 | TableModel.setData() → 修改 Shape 对象 → Canvas.update() |
| 表格 → JSON | 用户保存 | Shape → LabelFile.save() → JSON 文件 |
| Canvas → 表格 | shape_moved / selection_changed | 信号 → FlatIndex.refresh_file() → TableModel 刷新 |
| JSON → 表格 | load_file | LabelFile → FlatIndex.refresh_file() → TableModel 刷新 |

**关键技术点**:
- 使用 `QAbstractTableModel` + 自定义 delegate 实现可编辑列
- flags/attributes 列使用 JSON 编辑器（或简单的 key-value 编辑器）
- 利用现有 `set_dirty` 机制确保未保存修改不被丢弃

---

## 5. Phase 3：条件拆分/导出 + 规则配置 UI（计划中）

### 5.1 目标

在 Phase 2 基础上新增：
- 按条件拆分文件：根据问题类型、标签、group_id 等条件，将文件**复制**到不同子目录
- 规则配置 UI：用户可勾选/取消规则、添加自定义规则、调整规则参数
- 可自定义的拆分规则（如"将包含孤立关键点的文件复制到 orphan_heads/"）

### 5.2 设计要点

**拆分操作**:
- 操作类型：**复制**（非移动），保持原始数据不变
- 目录结构：`output_dir/{rule_name}/...` 按规则建子目录
- 非 JSON 资源文件（图片）同步复制

**规则配置**:
```
┌────────────────────────────────────┐
│ 规则配置                           │
│                                    │
│  ☑ 标签名检查 (LabelInAllowlist)   │
│    标签列表: [编辑...]             │
│  ☑ Group ID 唯一性                 │
│    唯一类型: person, head, face    │
│  ☑ 关键点完整性                    │
│  ☑ 必填字段非空                    │
│  ☑ 属性一致性                      │
│  ─────────────────────             │
│  [+ 添加自定义规则]                │
└────────────────────────────────────┘
```

**可扩展性**: 自定义规则可通过实现 `ValidationRule` 抽象基类并注册到 `ValidationEngine` 来实现。

---

## 6. 文件清单

### 6.1 新增文件（Inspector 子包）

```
anylabeling/views/labeling/widgets/inspector/
├── __init__.py              # 包导出
├── flat_index.py            # FlattenedRecord + FlatIndex（内存索引）
├── validation_engine.py     # ValidationRule + 5 个内置规则 + ValidationEngine
├── issue_list_widget.py     # IssueListWidget（QTreeWidget 问题列表）
└── inspector_panel.py       # InspectorPanel（QDockWidget 顶层容器）
```

### 6.2 修改文件

| 文件 | 修改内容 |
|------|----------|
| `anylabeling/views/labeling/widgets/__init__.py` | + `from .inspector import InspectorPanel` |
| `anylabeling/views/labeling/label_widget.py` | + 导入、实例化、右侧栏嵌入、导航方法、菜单 action、文件列表同步 |

### 6.3 参考文件（无需修改，仅作数据源参考）

| 文件 | 说明 |
|------|------|
| `historical_code_3.3.8/000000000389.json` | 测试数据：8 个 group，其中 3 个有 person 框 + 关键点，5 个是孤立头 |
| `D:\Deepseek\football_field_kps\修复版_标签过滤label_filer_no_invis_dele.py` | 用户现有外部过滤脚本 |

---

## 7. 集成点说明

### 7.1 信号流图

```
IssueListWidget.issue_clicked(file_path, shape_index)
    ↓
InspectorPanel (透传)
    ↓ issue_navigate_requested.emit(file_path, shape_index)
LabelingWidget._on_inspector_navigate(file_path, shape_index)
    ↓
    ├─ file_list_widget.setCurrentItem(item)
    │   → 触发 file_selection_changed()
    │   → load_file(filename)
    │
    └─ canvas.select_shape(shape)   ← 待修复
       canvas.zoom_to_selection()   ← 待修复
```

### 7.2 文件列表同步链

```
file_search_changed()
    → import_image_folder(...)
    → _update_inspector_file_list()
        → inspector_panel.set_file_list(json_paths)
            → 存储 _file_list
            → 清除旧结果
```

### 7.3 扫描触发

```
用户点击"扫描"按钮
    → IssueListWidget.rescan_requested.emit()
    → InspectorPanel.run_scan()
        → flat_index.scan_files(paths)
        → engine.run(flat_index)
        → issue_list.populate(report)
```

---

> **下一步**: 修复 Phase 1 中 `_on_inspector_navigate` 的 Canvas API 调用问题，使其能正确选中并居中目标 shape。
