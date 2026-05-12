# 筛选结果导航实现计划

## 目标

新增“筛选结果导航”功能，用于在已有对象筛选条件基础上，跳过不包含筛选结果的图片，并复用原有 `A` / `D` 上一张、下一张操作。

该功能只处理筛选结果的展示和导航，不重新定义筛选来源和命中规则。筛选条件仍由现有 `FilterState` 和筛选保持系统负责。

核心目标：

1. 不改变原始文件列表结构。
2. 不插入分组 header。
3. 不重排文件列表。
4. 不修改 `image_list` 和 `fn_to_index` 的既有语义。
5. 不破坏普通文件点击、复制路径、上一张/下一张、unchecked 导航等原始操作。
6. 筛选导航开启后，`A` / `D` 跳转到上一个/下一个仍命中的图片。
7. 离开当前图片时，检查当前图片是否仍命中筛选；如果不再命中，则自动从待处理集合移除并更新剩余数量。

## 已确认设计决策

### 展示方式

第一版只使用状态栏提示，不修改左侧文件列表结构。

不做：

```text
Matched / Other 分组
文件列表重排
插入 header
替换 image_list
高亮文件项
```

### 操作方式

继续复用原有快捷键：

```text
A -> open_prev_image()
D -> open_next_image()
```

不新增独立 `QShortcut("A")` / `QShortcut("D")`。

### 导航模式

手动开启/关闭。

普通模式：

```text
A / D 按原始文件顺序切换。
```

筛选结果导航模式：

```text
A / D 在剩余待处理的命中文件之间切换。
```

### 结果集合

启用导航时生成一次快照。

```text
_filter_navigation_files = 启用时命中的文件列表
```

用户修改标签后，不自动全量重扫所有 JSON。

### 当前图结算

只要准备离开当前图，就检查当前图是否仍命中筛选。

离开入口包括：

```text
按 D
按 A
鼠标点击左侧文件列表切换文件
```

如果当前图不再命中：

```text
从 _filter_navigation_files 移除当前文件
更新剩余数量
```

### 判断数据源

采用混合方案：

```text
启用/刷新导航时：用 JSON 扫描全部文件。
离开当前图前结算时：优先用 canvas.shapes 判断当前图。
当前图没有内存 shapes 时：fallback 到 JSON。
```

理由：

1. 批量扫描时，只有当前图在内存，其它文件只能读 JSON。
2. 当前图刚改完标签但还没保存时，JSON 可能滞后，`canvas.shapes` 才是最新状态。

### 边界行为

不循环。

```text
到最后一个筛选结果，按 D：不跳转，提示已到最后一个筛选结果。
到第一个筛选结果，按 A：不跳转，提示已到第一个筛选结果。
待处理集合为空：自动关闭筛选结果导航，提示已完成。
```

当前文件不在待处理集合中：

```text
按 D：跳到原始文件顺序中当前位置之后的下一个命中文件。
按 A：跳到原始文件顺序中当前位置之前的上一个命中文件。
```

## 代码落点

### 新增文件

```text
anylabeling/views/labeling/filter_navigation_engine.py
```

职责：纯逻辑判断，不访问 Qt UI，不调用 `LabelingWidget`。

### 修改文件

```text
anylabeling/views/labeling/label_widget.py
```

新增导航状态、入口方法、A/D 分支和离开当前图结算逻辑。

### 测试文件

```text
tests/test_filter_navigation_engine.py
```

只测纯逻辑，避免导入完整应用包导致 PyQt / onnxruntime 环境问题。

## FilterNavigationEngine 代码细则

### 类定义

```python
class FilterNavigationEngine:
    """Compute and update files for filter result navigation."""
```

### 对外接口

```python
def collect_matched_files(self, image_files, filter_state, output_dir=None):
    """Return image files whose JSON contains at least one matching shape."""
```

```python
def file_matches_filter(self, image_file, filter_state, output_dir=None):
    """Return whether one image's JSON contains a matching shape."""
```

```python
def shapes_match_filter(self, shapes, filter_state):
    """Return whether current in-memory shapes contain a matching shape."""
```

### 私有辅助方法

```python
def _label_file_for_image(self, image_file, output_dir=None):
    label_file = osp.splitext(image_file)[0] + ".json"
    if output_dir:
        label_file = osp.join(output_dir, osp.basename(label_file))
    return label_file
```

```python
def _shape_matches_filter(self, shape, filter_state):
    ...
```

### shape 输入兼容规则

`_shape_matches_filter()` 应同时支持：

1. JSON 中的 `dict` shape。
2. 内存中的 `Shape` 对象。

建议实现一个取值 helper：

```python
@staticmethod
def _shape_value(shape, key, default=None):
    if isinstance(shape, dict):
        return shape.get(key, default)
    return getattr(shape, key, default)
```

### 匹配规则

复用当前筛选语义：

```text
label 集合内部 OR
label / gid / shape_type 条件之间 AND
文件中任意 shape 命中，则文件命中
```

伪代码：

```python
def _shape_matches_filter(self, shape, filter_state):
    label = self._shape_value(shape, "label", "")
    gid = self._shape_value(shape, "group_id", None)
    shape_type = self._shape_value(shape, "shape_type", "")

    if filter_state.labels and label not in filter_state.labels:
        return False
    if filter_state.gid != "-1":
        if gid is None or str(gid) != str(filter_state.gid):
            return False
    if filter_state.shape_type and shape_type != filter_state.shape_type:
        return False
    return True
```

### JSON 错误处理

以下情况都返回不命中：

```text
JSON 文件不存在
JSON 解析失败
JSON 无 shapes 字段
shapes 不是 list
```

不要抛异常给 UI 层。

## LabelingWidget 状态细则

### import

在 `label_widget.py` 中新增：

```python
from .filter_navigation_engine import FilterNavigationEngine
```

### 初始化字段

在 `LabelingWidget.__init__` 中新增：

```python
self._filter_navigation_engine = FilterNavigationEngine()
self._filter_navigation_active = False
self._filter_navigation_files = []
self._filter_navigation_initial_count = 0
self._filter_navigation_state = None
```

### 字段含义

| 字段 | 类型 | 含义 |
|------|------|------|
| `_filter_navigation_engine` | `FilterNavigationEngine` | 纯逻辑引擎 |
| `_filter_navigation_active` | `bool` | 是否启用筛选结果导航 |
| `_filter_navigation_files` | `list[str]` | 当前剩余待处理命中文件 |
| `_filter_navigation_initial_count` | `int` | 启用时初始命中文件数量 |
| `_filter_navigation_state` | `FilterState | None` | 启用时筛选状态快照 |

## LabelingWidget 方法细则

### 启用/刷新导航

新增：

```python
def enable_filter_navigation(self):
    ...
```

流程：

```text
1. 如果当前没有 active filter，status 提示并 return。
2. state = self._copy_filter_state()
3. files = list(self.image_list)
4. matched = engine.collect_matched_files(files, state, self.output_dir)
5. 保存状态：
   _filter_navigation_active = True
   _filter_navigation_files = matched
   _filter_navigation_initial_count = len(matched)
   _filter_navigation_state = state
6. 如果 matched 为空：
   可保持 active=False，提示没有匹配文件。
7. 否则 status 提示剩余数量。
```

建议代码：

```python
def enable_filter_navigation(self):
    if not self._filter_state.has_active_filter():
        self.status(self.tr("No active filter for result navigation"), 3000)
        return

    state = self._copy_filter_state()
    matched = self._filter_navigation_engine.collect_matched_files(
        list(self.image_list), state, self.output_dir
    )
    self._filter_navigation_files = matched
    self._filter_navigation_initial_count = len(matched)
    self._filter_navigation_state = state
    self._filter_navigation_active = bool(matched)

    if not matched:
        self.status(self.tr("No files match the current filter"), 3000)
        return
    self._show_filter_navigation_status(
        self.tr("Filter result navigation enabled")
    )
```

### 关闭导航

新增：

```python
def clear_filter_navigation(self):
    self._filter_navigation_active = False
    self._filter_navigation_files = []
    self._filter_navigation_initial_count = 0
    self._filter_navigation_state = None
    self.status(self.tr("Filter result navigation cleared"), 2000)
```

### 状态栏显示

新增：

```python
def _show_filter_navigation_status(self, prefix=None):
    ...
```

建议格式：

```text
Filter result navigation enabled: remaining 99 / initial 100
Current file completed: remaining 98 / initial 100
```

代码：

```python
def _show_filter_navigation_status(self, prefix=None):
    message = self.tr("Remaining {remaining} / initial {initial}").format(
        remaining=len(self._filter_navigation_files),
        initial=self._filter_navigation_initial_count,
    )
    if prefix:
        message = f"{prefix}: {message}"
    self.status(message, 3000)
```

### 离开当前图前结算

新增：

```python
def _settle_current_filter_navigation_file(self):
    ...
```

流程：

```text
1. 如果导航未开启，return。
2. 如果没有当前 filename，return。
3. 如果当前 filename 不在 _filter_navigation_files，return。
4. 优先用 self.canvas.shapes 判断当前图是否仍命中。
5. 如果不命中，从 _filter_navigation_files 移除当前 filename。
6. 如果移除后为空，自动关闭导航并提示完成。
7. 如果未空，提示剩余数量。
```

建议代码：

```python
def _settle_current_filter_navigation_file(self):
    if not self._filter_navigation_active:
        return
    if not self.filename or self._filter_navigation_state is None:
        return

    filename = str(self.filename)
    if filename not in self._filter_navigation_files:
        return

    shapes = getattr(self.canvas, "shapes", None)
    if shapes is not None:
        still_matches = self._filter_navigation_engine.shapes_match_filter(
            shapes, self._filter_navigation_state
        )
    else:
        still_matches = self._filter_navigation_engine.file_matches_filter(
            filename, self._filter_navigation_state, self.output_dir
        )

    if still_matches:
        return

    self._filter_navigation_files.remove(filename)
    if not self._filter_navigation_files:
        self.clear_filter_navigation()
        self.status(self.tr("Filter result navigation completed"), 3000)
        return

    self._show_filter_navigation_status(
        self.tr("Current file completed")
    )
```

### 获取当前原始文件位置

新增：

```python
def _current_image_index(self):
    files = self.image_list
    if not self.filename or str(self.filename) not in files:
        return -1
    return files.index(str(self.filename))
```

### 查找下一个命中文件

新增：

```python
def _next_filter_navigation_file(self):
    ...
```

规则：

```text
从当前文件在 image_list 的位置之后开始查找。
只返回仍在 _filter_navigation_files 中的文件。
不循环。
```

代码：

```python
def _next_filter_navigation_file(self):
    files = self.image_list
    current_index = self._current_image_index()
    start = current_index + 1 if current_index >= 0 else 0
    remaining = set(self._filter_navigation_files)
    for filename in files[start:]:
        if filename in remaining:
            return filename
    return None
```

### 查找上一个命中文件

新增：

```python
def _prev_filter_navigation_file(self):
    ...
```

代码：

```python
def _prev_filter_navigation_file(self):
    files = self.image_list
    current_index = self._current_image_index()
    if current_index < 0:
        return None
    remaining = set(self._filter_navigation_files)
    for filename in reversed(files[:current_index]):
        if filename in remaining:
            return filename
    return None
```

### 筛选结果下一张

新增：

```python
def _open_next_filter_navigation_image(self, load=True):
    ...
```

代码：

```python
def _open_next_filter_navigation_image(self, load=True):
    self._settle_current_filter_navigation_file()
    if not self._filter_navigation_active:
        return True

    filename = self._next_filter_navigation_file()
    if filename is None:
        self.status(self.tr("Already at the last filter result"), 2000)
        return True

    self.filename = filename
    if load:
        self.load_file(filename)
    return True
```

### 筛选结果上一张

新增：

```python
def _open_prev_filter_navigation_image(self):
    ...
```

代码：

```python
def _open_prev_filter_navigation_image(self):
    self._settle_current_filter_navigation_file()
    if not self._filter_navigation_active:
        return True

    filename = self._prev_filter_navigation_file()
    if filename is None:
        self.status(self.tr("Already at the first filter result"), 2000)
        return True

    self.load_file(filename)
    return True
```

## 修改现有导航方法

### open_next_image

当前原逻辑保持不动，只在开头增加筛选导航分支：

```python
def open_next_image(self, _value=False, load=True):
    if self._filter_navigation_active:
        if self._open_next_filter_navigation_image(load=load):
            return

    # existing logic unchanged
```

注意：`may_continue()` 应在 `_open_next_filter_navigation_image()` 内部或外部只调用一次，避免重复弹保存提示。推荐保留现有 `open_next_image()` 开头的 `may_continue()`，并在筛选导航分支放在其后：

```python
def open_next_image(self, _value=False, load=True):
    if not self.may_continue():
        return
    if self._filter_navigation_active:
        if self._open_next_filter_navigation_image(load=load):
            return
    ...
```

### open_prev_image

同理：

```python
def open_prev_image(self, _value=False):
    if not self.may_continue():
        return
    if self._filter_navigation_active:
        if self._open_prev_filter_navigation_image():
            return
    ...
```

## 修改 file_selection_changed

目标：鼠标点击文件离开当前图时，也结算当前图。

当前逻辑：

```python
if not self.may_continue():
    return
...
self.load_file(filename)
```

建议改为：

```python
if not self.may_continue():
    return
if self._filter_navigation_active:
    self._settle_current_filter_navigation_file()
...
self.load_file(filename)
```

注意：不要改变原始 `current_index` / `image_list` 逻辑，因为本方案不改文件列表结构。

## 菜单入口

建议第一版加在文件列表右键菜单 `pop_file_list_menu()`：

```text
Enable/Refresh Filter Result Navigation
Clear Filter Result Navigation
```

插入位置：复制路径、重置视图动作之后。

代码细则：

```python
menu.addSeparator()
enable_filter_navigation_action = menu.addAction(
    self.tr("Enable/Refresh Filter Result Navigation")
)
enable_filter_navigation_action.setEnabled(
    self._filter_state.has_active_filter()
)
clear_filter_navigation_action = menu.addAction(
    self.tr("Clear Filter Result Navigation")
)
clear_filter_navigation_action.setEnabled(self._filter_navigation_active)
```

响应：

```python
elif action == enable_filter_navigation_action:
    self.enable_filter_navigation()
elif action == clear_filter_navigation_action:
    self.clear_filter_navigation()
```

## 测试计划

### 新增测试文件

```text
tests/test_filter_navigation_engine.py
```

### 测试导入方式

避免导入完整 `anylabeling` 包，使用 `importlib.util.spec_from_file_location()` 按路径加载：

```python
MODULE_PATH = Path(__file__).resolve().parents[1] / "anylabeling/views/labeling/filter_navigation_engine.py"
```

原因：完整包导入可能触发 PyQt / onnxruntime 初始化，导致环境相关失败。

### 纯逻辑测试用例

1. 单 label 命中文件。
2. 多 label 使用 OR。
3. `label + gid + shape_type` 使用 AND。
4. 一个文件多个 shape，任一 shape 命中则文件命中。
5. `shapes_match_filter()` 支持内存对象。
6. `shapes_match_filter()` 支持 dict。
7. JSON 不存在返回不匹配。
8. JSON 损坏返回不匹配。
9. `output_dir` 下 JSON 正确匹配。

### 手动验证清单

1. 启用导航后，左侧文件列表顺序不变。
2. 启用导航后，文件列表不出现 header。
3. `D` 跳到下一个命中文件。
4. `A` 跳到上一个命中文件。
5. 当前文件不命中时，`D` 跳到后方下一个命中文件。
6. 当前文件不命中时，`A` 跳到前方上一个命中文件。
7. 修改当前文件标签后，按 `D`，当前文件从剩余集合移除。
8. 剩余数量更新。
9. 到最后一个结果，按 `D` 不循环。
10. 到第一个结果，按 `A` 不循环。
11. 鼠标点击其它文件时，也结算当前文件。
12. 清除导航后，`A/D` 恢复普通行为。

## 风险控制

### 不要改的东西

本次实现禁止修改：

```text
image_list 属性语义
fn_to_index 语义
file_list_widget item 结构
文件列表顺序
文件列表 item 文本
open_next_unchecked_image / open_prev_unchecked_image 逻辑
```

### 为什么不会复现前次递归问题

前次问题来自：

```text
向 file_list_widget 插入 header
导致 UI row != image_list index
点击文件时错位 load_file
load_file 触发 setCurrentRow
递归进入 file_selection_changed
```

本方案不插入 header、不改文件列表结构，因此不破坏这个隐含关系。

### 结算必须在 load_file 前

`load_file()` 会调用：

```text
reset_state()
canvas.reset_state()
```

这会清空当前图的内存 shapes。

因此 `_settle_current_filter_navigation_file()` 必须在 `load_file()` 前调用。

## 实施顺序

1. 新增 `filter_navigation_engine.py`。
2. 新增 `tests/test_filter_navigation_engine.py` 并跑通纯逻辑测试。
3. 在 `LabelingWidget.__init__` 初始化导航状态。
4. 新增 `enable_filter_navigation()` / `clear_filter_navigation()`。
5. 新增 `_settle_current_filter_navigation_file()`。
6. 新增 `_next_filter_navigation_file()` / `_prev_filter_navigation_file()`。
7. 改造 `open_next_image()` / `open_prev_image()`。
8. 改造 `file_selection_changed()`。
9. 给 `pop_file_list_menu()` 增加入口。
10. 运行语法检查、lint、单元测试。

## 验收标准

1. 不启用导航时，软件行为与原始版本一致。
2. 启用导航后，`A/D` 跳过不命中的图片。
3. 修改标签后离开当前图，当前图能从待处理集合移除。
4. 剩余数量正确显示。
5. 清除导航后，`A/D` 恢复原始行为。
6. 文件列表没有结构变化。
7. 不再出现 `file_selection_changed()` 递归崩溃。
