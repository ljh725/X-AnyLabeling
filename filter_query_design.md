# X-AnyLabeling 筛选查询条件动态变化设计方案

> 目标：在 JSON 文件系统之上构建灵活的查询层，支持查询条件的动态增删、组合、嵌套与实时刷新。

---

## 1. 核心设计哲学

**JSON 仍是唯一事实来源**，数据库/内存索引仅作为**临时查询视图**。查询条件的变化不应触发索引重建，而应通过「抽象语法树（AST）」+「动态 SQL 生成器」实现零延迟的条件重组。

---

## 2. 查询条件的结构化表示（AST）

### 2.1 数据模型

采用树形结构支持任意嵌套的 `AND` / `OR` / `NOT`：

```python
from dataclasses import dataclass, field
from typing import List, Union, Any

@dataclass
class Condition:
    """叶子节点：单条条件"""
    field: str       # 字段名："width", "label", "color"...
    op: str          # 操作符："==", "<", ">", "<=", ">=", "!=", "contains", "starts_with", "in"
    value: Any       # 对比值
    negate: bool = False  # 是否取反（NOT）

@dataclass
class ConditionGroup:
    """分支节点：条件组合"""
    logic: str = "AND"  # "AND" | "OR"
    conditions: List[Union[Condition, 'ConditionGroup']] = field(default_factory=list)
    negate: bool = False
```

### 2.2 复杂查询示例

**需求**：查询 `(label == "cat" AND width < 96) OR (shape_type == "point" AND difficult == 0)`

```python
query = ConditionGroup(
    logic="OR",
    conditions=[
        ConditionGroup(
            logic="AND",
            conditions=[
                Condition("label", "==", "cat"),
                Condition("width", "<", 96),
            ]
        ),
        ConditionGroup(
            logic="AND",
            conditions=[
                Condition("shape_type", "==", "point"),
                Condition("difficult", "==", 0),
            ]
        ),
    ]
)
```

---

## 3. 动态 SQL 生成器

遍历 AST 生成参数化 SQL，**完全防止注入攻击**。

### 3.1 核心实现

```python
import sqlite3
from typing import Union, Any, List, Dict

class QueryBuilder:
    # 表字段白名单：原生字段 + 预计算派生字段
    NATIVE_FIELDS = {
        "json_path", "image_path", "shape_idx", "label", "shape_type",
        "difficult", "group_id", "width", "height", "area",
        "center_x", "center_y", "direction", "score",
    }
    
    # 操作符映射表
    OP_SQL = {
        "==": "=", "!=": "!=", "<": "<", "<=": "<=",
        ">": ">", ">=": ">=",
        "contains": "LIKE",
        "starts_with": "LIKE",
        "in": "IN",
    }

    @classmethod
    def build(cls, node: Union[Condition, ConditionGroup]) -> tuple[str, list]:
        """返回 (where_sql, params)"""
        if isinstance(node, Condition):
            return cls._build_condition(node)
        return cls._build_group(node)

    @classmethod
    def _build_condition(cls, c: Condition) -> tuple[str, list]:
        field_sql, params = cls._resolve_field(c.field, c.value)
        
        if c.op in ("contains", "starts_with"):
            params[0] = f"%{params[0]}" if c.op == "contains" else f"{params[0]}%"
            field_sql = f"{field_sql} LIKE ?"
        elif c.op == "in":
            placeholders = ",".join("?" for _ in c.value)
            field_sql = f"{field_sql} IN ({placeholders})"
            params = list(c.value)
        else:
            field_sql = f"{field_sql} {cls.OP_SQL[c.op]} ?"
        
        if c.negate:
            field_sql = f"NOT ({field_sql})"
        return field_sql, params

    @classmethod
    def _resolve_field(cls, field: str, value: Any) -> tuple[str, list]:
        if field in cls.NATIVE_FIELDS:
            return f'"{field}"', [value]
        
        # attributes 穿透：自动使用 json_extract
        # 例：attributes.color → json_extract(attributes_json, '$.color')
        return f"json_extract(attributes_json, '$.{field}')", [value]

    @classmethod
    def _build_group(cls, g: ConditionGroup) -> tuple[str, list]:
        parts = []
        all_params = []
        
        for child in g.conditions:
            sql, params = cls.build(child)
            parts.append(sql)
            all_params.extend(params)
        
        if not parts:
            return "1=1", []
        
        joiner = f" {g.logic} "
        combined = f"({joiner.join(parts)})"
        
        if g.negate:
            combined = f"NOT {combined}"
        return combined, all_params
```

### 3.2 执行查询

```python
def execute_query(conn: sqlite3.Connection, root: ConditionGroup) -> List[Dict]:
    where_sql, params = QueryBuilder.build(root)
    sql = f"SELECT * FROM shapes WHERE {where_sql}"
    cursor = conn.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
```

### 3.3 安全性说明

- **字段白名单**：`NATIVE_FIELDS` 阻止非法字段名注入。
- **参数化查询**：所有用户输入通过 `?` 占位符传入，SQL 语句本身不可注入。
- **操作符白名单**：`OP_SQL` 仅允许预定义的比较操作。

---

## 4. 条件变化的三种刷新策略

条件变化时，不应每次都重建索引，而应根据变更粒度选择策略：

| 变更类型 | 触发时机 | 动作 | 成本 |
|---|---|---|---|
| **条件值变化** | 用户修改输入框内容 | 防抖后重新执行 `execute_query` | 极低（仅 SQL 执行） |
| **条件结构变化** | 添加/删除条件行、切换 AND/OR | 重新生成 AST，执行查询 | 低（AST 重建 + SQL 执行） |
| **数据源变化** | 保存标注、新增/删除图片 | 增量刷新索引，然后重新查询 | 中（单文件重新解析） |

### 4.1 防抖查询控制器

```python
from PyQt6.QtCore import QTimer

class FilterController:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.root_condition = ConditionGroup()  # 当前条件树
        self._debounce_timer = QTimer()
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._do_query)
    
    def on_condition_changed(self):
        """UI 任何条件变化都调用这里"""
        self._debounce_timer.stop()
        self._debounce_timer.start(300)  # 300ms 防抖
    
    def _do_query(self):
        results = execute_query(self.conn, self.root_condition)
        self.apply_to_ui(results)
    
    def apply_to_ui(self, results: List[dict]):
        """投射查询结果到 UI"""
        matched_images = {r["image_path"] for r in results}
        # 更新文件列表可见性、画布高亮等...
```

---

## 5. Qt UI 双向绑定设计

### 5.1 界面布局

```
┌────────────────────────────────────────────┐
│ [高级筛选]                              [X] │
├────────────────────────────────────────────┤
│ 逻辑: [AND ▼] [+ 条件] [+ 条件组]          │
│ ┌────────────────────────────────────────┐ │
│ │ [字段▼] [操作符▼] [值      ] [−]      │ │  ← ConditionRow
│ │ label    ==        "cat"               │ │
│ ├────────────────────────────────────────┤ │
│ │ [字段▼] [操作符▼] [值      ] [−]      │ │
│ │ width    <         96                  │ │
│ └────────────────────────────────────────┘ │
│ ┌────────────────────────────────────────┐ │
│ │ 逻辑: [OR ▼]                           │ │  ← ConditionGroup（嵌套）
│ │  shape_type  ==   "point"          [−] │ │
│ │  difficult   ==   0                    │ │
│ └────────────────────────────────────────┘ │
│ [应用] [重置] [保存为预设]                 │
└────────────────────────────────────────────┘
```

### 5.2 ConditionRow（单行条件组件）

```python
from PyQt6 import QtWidgets, QtCore

class ConditionRow(QtWidgets.QWidget):
    """单行条件 UI"""
    changed = QtCore.pyqtSignal()
    removed = QtCore.pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        
        self.field_combo = QtWidgets.QComboBox()
        self.field_combo.addItems([
            "label", "shape_type", "width", "height", "area",
            "center_x", "center_y", "difficult", "group_id", "score"
        ])
        self.field_combo.setEditable(True)  # 支持自定义 attributes 字段
        
        self.op_combo = QtWidgets.QComboBox()
        self.op_combo.addItems(["==", "!=", "<", "<=", ">", ">=", "contains", "in"])
        
        self.value_edit = QtWidgets.QLineEdit()
        self.value_edit.setPlaceholderText("输入值...")
        
        self.del_btn = QtWidgets.QPushButton("−")
        self.del_btn.setFixedWidth(30)
        
        layout.addWidget(self.field_combo)
        layout.addWidget(self.op_combo)
        layout.addWidget(self.value_edit)
        layout.addWidget(self.del_btn)
        
        # 任何变化都发射信号
        self.field_combo.currentTextChanged.connect(self.changed.emit)
        self.op_combo.currentTextChanged.connect(self.changed.emit)
        self.value_edit.textChanged.connect(self.changed.emit)
        self.del_btn.clicked.connect(lambda: self.removed.emit(self))
    
    def to_condition(self) -> Condition:
        val = self.value_edit.text()
        try:
            val = float(val)
        except ValueError:
            pass
        
        return Condition(
            field=self.field_combo.currentText(),
            op=self.op_combo.currentText(),
            value=val
        )
```

### 5.3 FilterPanel（筛选面板容器）

```python
class FilterPanel(QtWidgets.QWidget):
    """完整筛选面板"""
    query_changed = QtCore.pyqtSignal(object)  # 发射 ConditionGroup
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("高级筛选")
        self._rows: List[ConditionRow] = []
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # 顶部控制栏
        top = QtWidgets.QHBoxLayout()
        self.logic_combo = QtWidgets.QComboBox()
        self.logic_combo.addItems(["AND", "OR"])
        self.add_btn = QtWidgets.QPushButton("+ 条件")
        self.group_btn = QtWidgets.QPushButton("+ 条件组")
        top.addWidget(QtWidgets.QLabel("逻辑:"))
        top.addWidget(self.logic_combo)
        top.addStretch()
        top.addWidget(self.add_btn)
        top.addWidget(self.group_btn)
        layout.addLayout(top)
        
        # 条件容器
        self.rows_container = QtWidgets.QVBoxLayout()
        layout.addLayout(self.rows_container)
        layout.addStretch()
        
        # 底部按钮
        bottom = QtWidgets.QHBoxLayout()
        self.apply_btn = QtWidgets.QPushButton("应用")
        self.reset_btn = QtWidgets.QPushButton("重置")
        bottom.addStretch()
        bottom.addWidget(self.reset_btn)
        bottom.addWidget(self.apply_btn)
        layout.addLayout(bottom)
        
        self.add_btn.clicked.connect(self._add_row)
        self.reset_btn.clicked.connect(self._reset)
        self.apply_btn.clicked.connect(self._emit_query)
        
        self._add_row()
    
    def _add_row(self):
        row = ConditionRow()
        row.changed.connect(self._on_any_change)
        row.removed.connect(self._remove_row)
        self._rows.append(row)
        self.rows_container.addWidget(row)
    
    def _remove_row(self, row: ConditionRow):
        if row in self._rows:
            self._rows.remove(row)
            row.deleteLater()
            self._on_any_change()
    
    def _on_any_change(self):
        self._emit_query()
    
    def _reset(self):
        for row in list(self._rows):
            self._remove_row(row)
        self._add_row()
    
    def _emit_query(self):
        if not self._rows:
            return
        
        group = ConditionGroup(
            logic=self.logic_combo.currentText(),
            conditions=[r.to_condition() for r in self._rows if r.isVisible()]
        )
        self.query_changed.emit(group)
```

---

## 6. 自定义派生字段注册机制

### 6.1 注册表设计

派生字段的计算逻辑集中在注册表中，查询引擎自动识别：

```python
# filter_indexer.py

DERIVED_EXTRACTORS = {
    "width": lambda shape: (
        abs(pts[2][0] - pts[0][0]) 
        if len(pts := shape.get("points", [])) == 4 else 0.0
    ),
    "height": lambda shape: (
        abs(pts[2][1] - pts[0][1]) 
        if len(pts := shape.get("points", [])) == 4 else 0.0
    ),
    "area": lambda shape: (
        abs(pts[2][0] - pts[0][0]) * abs(pts[2][1] - pts[0][1])
        if len(pts := shape.get("points", [])) == 4 else 0.0
    ),
    "diagonal": lambda shape: (
        (abs(pts[2][0]-pts[0][0])**2 + abs(pts[2][1]-pts[0][1])**2) ** 0.5
        if len(pts := shape.get("points", [])) == 4 else 0.0
    ),
    "center_x": lambda shape: (
        (pts[0][0] + pts[2][0]) / 2 
        if len(pts := shape.get("points", [])) >= 3 else 0.0
    ),
    "center_y": lambda shape: (
        (pts[0][1] + pts[2][1]) / 2 
        if len(pts := shape.get("points", [])) >= 3 else 0.0
    ),
}

def extract_shape_fields(shape: dict) -> dict:
    """提取所有字段（原生 + 派生）"""
    result = {
        "label": shape.get("label", ""),
        "shape_type": shape.get("shape_type", ""),
        "difficult": int(shape.get("difficult", False)),
        "group_id": shape.get("group_id"),
        "direction": shape.get("direction", 0),
        "score": shape.get("score"),
    }
    for name, fn in DERIVED_EXTRACTORS.items():
        result[name] = fn(shape)
    return result
```

### 6.2 扩展方式

新增派生字段只需三步：

1. 在 `DERIVED_EXTRACTORS` 添加 lambda。
2. 将字段名加入 `QueryBuilder.NATIVE_FIELDS`。
3. 建表语句中增加该列（或运行时 `ALTER TABLE`）。

**无需修改查询引擎核心代码**。

---

## 7. 查询结果投射到 X-AnyLabeling UI

查询结果需要映射到三个 UI 区域：

### 7.1 文件列表过滤

只显示包含命中 shape 的图片，其余隐藏。

```python
def project_to_file_list(results: List[dict], file_list_widget):
    matched = {r["image_path"] for r in results}
    for i in range(file_list_widget.count()):
        item = file_list_widget.item(i)
        item.setHidden(item.data(Qt.ItemDataRole.UserRole) not in matched)
```

### 7.2 画布高亮（单图模式）

打开图片后，命中 shape 正常显示，未命中 shape 半透明置灰。

```python
def project_to_canvas(results: List[dict], canvas):
    matched_indices = {r["shape_idx"] for r in results 
                       if r["image_path"] == canvas.current_image_path}
    for idx, shape in enumerate(canvas.shapes):
        if idx not in matched_indices:
            shape.line_color = QtGui.QColor(200, 200, 200, 80)
            shape.disabled = True
```

### 7.3 标签列表过滤

左侧标签面板仅列出命中条目，支持快速跳转。

---

## 8. 增量索引同步

用户标注过程中 JSON 会变化，索引需要同步刷新：

```python
def refresh_single_file(conn: sqlite3.Connection, json_path: str):
    """单文件增量刷新"""
    conn.execute("DELETE FROM shapes WHERE json_path = ?", (json_path,))
    
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    image_path = data.get("imagePath", "")
    for idx, shape in enumerate(data.get("shapes", [])):
        fields = extract_shape_fields(shape)
        conn.execute("""
            INSERT INTO shapes 
            (json_path, image_path, shape_idx, label, shape_type, difficult,
             group_id, width, height, area, center_x, center_y, direction,
             score, attributes_json, raw_shape_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            json_path, image_path, idx,
            fields["label"], fields["shape_type"], fields["difficult"],
            fields["group_id"], fields["width"], fields["height"],
            fields["area"], fields["center_x"], fields["center_y"],
            fields["direction"], fields["score"],
            json.dumps(shape.get("attributes", {}), ensure_ascii=False),
            json.dumps(shape, ensure_ascii=False)
        ))
    conn.commit()
```

**触发时机**：`LabelFile.save()` 成功后调用 `refresh_single_file()`。

---

## 9. 完整调用链路

```
用户在 FilterPanel 中修改条件
           ↓
ConditionRow.changed → FilterPanel._emit_query()
           ↓
生成 ConditionGroup AST
           ↓
QueryBuilder.build(AST) → (参数化 SQL, values)
           ↓
sqlite3.execute(sql, values) → 命中记录
           ↓
按 image_path 分组
           ↓
投射到：文件列表可见性 / 画布高亮 / 标签列表
```

---

## 10. 新增文件清单

建议新增以下文件，不破坏现有架构：

| 文件 | 职责 |
|---|---|
| `anylabeling/views/labeling/filter_indexer.py` | 建表、JSON 提取、增量同步、派生字段注册表 |
| `anylabeling/views/labeling/filter_query.py` | `Condition` / `ConditionGroup` AST + `QueryBuilder` |
| `anylabeling/views/labeling/filter_panel.py` | Qt 筛选面板 UI（`ConditionRow` + `FilterPanel`） |
| `anylabeling/views/labeling/filter_controller.py` | 防抖控制器 + 查询结果到 UI 的投射逻辑 |

**需修改的现有文件**：
- `label_widget.py`：挂载 `FilterPanel`，绑定 `file_list_widget` 过滤逻辑。
- `canvas.py`：增加 `project_to_canvas` 接口，接收命中索引集合。
- `label_file.py`：`save()` 成功后触发索引增量刷新。

---

## 11. 兼容性注意事项

| 注意事项 | 解决方案 |
|---|---|
| SQLite JSON1 扩展 | Python 3.11+ 内置 sqlite3 已支持 `json_extract`。若需兼容旧版本，回退到 Python 端过滤。 |
| `attributes` 任意键 | 首次打开文件夹时扫描所有 JSON 的 `attributes` 键集合，动态注册到 `QueryBuilder.NATIVE_FIELDS` 或走 `json_extract`。 |
| 大数据集启动慢 | 使用本地 `.xanylabeling_index.db` 持久化索引，启动时检查文件修改时间，仅增量更新。 |
| 多形状类型混排 | `width`/`height` 等非矩形形状返回 0，查询时自动过滤掉。 |
