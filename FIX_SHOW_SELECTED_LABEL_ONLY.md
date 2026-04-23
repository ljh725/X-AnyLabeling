# Show Selected Label Only 功能修复说明

## 修复版本
X-AnyLabeling 4.0.0-beta.4

## 问题描述
在 4.0.0 版本中，"Show Selected Label Only" 功能在选中关键点对象时不显示标签名。

## 根因分析
通过对比 3.3.0 版本代码发现，4.0.0 版本在 PyQt5→PyQt6 升级重构时，**遗漏了** `show_selected_label_only` 模式的配套逻辑：

1. **mouseReleaseEvent** 中缺少 `show_selected_label_only` 检查，导致点击已选中形状时错误地取消选中
2. **select_shape_point** 中缺少 `show_selected_label_only` 检查，导致重复点击时取消选中

## 修复内容

### 文件1: `anylabeling/views/labeling/widgets/canvas.py`

#### 修复1: mouseReleaseEvent (第1304-1313行)
**修改前**:
```python
elif ev.button() == QtCore.Qt.MouseButton.LeftButton:
    if self.editing():
        if (
            self.h_hape is not None
            and self.h_shape_is_selected
            and not self.moving_shape
        ):
            self.selection_changed.emit(
                [x for x in self.selected_shapes if x != self.h_hape]
            )
```

**修改后**:
```python
elif ev.button() == QtCore.Qt.MouseButton.LeftButton:
    if self.editing():
        if (
            self.h_hape is not None
            and self.h_shape_is_selected
            and not self.moving_shape
        ):
            # [修复] show_selected_label_only 模式下，禁用"点击取消选中"行为
            # 使标签持续显示直到选中其他对象
            if not getattr(self, 'show_selected_label_only', False):
                self.selection_changed.emit(
                    [x for x in self.selected_shapes if x != self.h_hape]
                )
```

#### 修复2: select_shape_point (第1504-1507行)
**修改前**:
```python
if shape not in self.selected_shapes:
    # ... 添加选中
    self.h_shape_is_selected = False
else:
    self.h_shape_is_selected = True
```

**修改后**:
```python
if shape not in self.selected_shapes:
    # ... 添加选中
    self.h_shape_is_selected = False
else:
    # [修复] show_selected_label_only 模式下，不自动取消选中
    # 使标签持续显示直到选中其他对象
    if getattr(self, 'show_selected_label_only', False):
        self.h_shape_is_selected = False
    else:
        self.h_shape_is_selected = True
```

### 文件2: `anylabeling/views/labeling/label_widget.py`
无修改（无需修改）

## 修复原理

### 3.3.0 版本的行为
在 3.3.0 版本中，`show_selected_label_only` 模式通过 `LabelDisplayManager` 的 `DisplayMode.SELECTED_ONLY` 来管理：
- **mouseReleaseEvent**: 检查 `current_mode != DisplayMode.SELECTED_ONLY`，如果是 SELECTED_ONLY 模式则**不执行**取消选中
- **select_shape_point**: 在 SELECTED_ONLY 模式下保持选中状态

### 4.0.0 版本的问题
4.0.0 版本简化了代码，但遗漏了这些检查：
- 点击已选中的形状时，`mouseReleaseEvent` 会**移除**该形状的选中状态
- 导致 `show_selected_label_only=True` 时，标签立即消失

### 修复方案
采用**最小改动**（方案A）：
1. 在 `mouseReleaseEvent` 中添加 `show_selected_label_only` 属性检查
2. 在 `select_shape_point` 中添加 `show_selected_label_only` 属性检查
3. 当 `show_selected_label_only=True` 时，**禁用**"点击取消选中"行为

## 测试验证

### 测试场景1: 普通编辑模式
1. 打开包含关键点的图像
2. 开启 "Show Selected Label Only" 功能
3. 点击关键点A → 应显示标签
4. 点击关键点B → 应显示标签（A的标签消失）

### 测试场景2: 关键点填充模式
1. 进入关键点填充模式
2. 开启 "Show Selected Label Only" 功能
3. 点击关键点A → 应显示标签
4. 点击关键点B → 应显示标签（A的标签消失）

### 测试场景3: 关闭功能
1. 关闭 "Show Selected Label Only" 功能
2. 所有标签应正常显示
3. 点击选择行为应恢复正常（可取消选中）

## 影响范围
- **仅影响** `show_selected_label_only=True` 时的鼠标点击行为
- **不影响** 其他模式下的选择逻辑
- **不影响** 标签绘制逻辑（仅修改选择状态管理）

## 代码变更统计
- 修改文件数: 1
- 新增代码行数: ~8行
- 删除代码行数: 0行（仅添加条件判断）

## 注意事项
1. 此修复为**最小改动方案**，未恢复 3.3.0 中的 `LabelDisplayManager` 系统
2. 如果未来需要更复杂的标签显示模式，建议考虑恢复 `LabelDisplayManager`
3. 修复后应保持与 3.3.0 版本相同的行为
