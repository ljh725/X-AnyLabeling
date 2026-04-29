# Keypoint Fill Tool — 调用链文档

> 本文档描述 X-AnyLabeling 中 **Keypoint Fill Tool（关键点补标工具）** 的完整调用链，涵盖从用户触发到数据落盘的全部链路。
>
> 对应版本: `4.0.0-beta.4+`

---

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              用户交互层                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │ 快捷键 K     │  │ Ctrl+K       │  │ Ctrl+Shift+[│  │ Ctrl+Shift+]│    │
│  │ 进入补标模式 │  │ 切换工具窗口 │  │ 上一个人    │  │ 下一个人    │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         ┌──────────────────┴──────────────────┴──────────────────┐          │
│         │  鼠标滚轮（在 person_list 区域）                       │          │
│         │  向上=上一个人 / 向下=下一个人                         │          │
│         └────────────────────────────────────────────────────────┘          │
└─────────┼─────────────────┼─────────────────┼─────────────────┼────────────┘
          │                 │                 │                 │
          ▼                 ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           LabelWidget (控制器)                               │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  enter_keypoint_fill_mode()                                         │    │
│  │  toggle_keypoint_tool_window()                                      │    │
│  │  switch_to_prev_person() / switch_to_next_person()                  │    │
│  │  delete_selected_shape() ──► keypoint_fill_mode.refresh()          │    │
│  │  new_shape() ──► 自动分配 label + group_id + advance()             │    │
│  │  undo_shape_edit() ──► keypoint_fill_mode.refresh()                │    │
│  │  toggle_draw_mode() ──► 退出检测 (非 point 模式则 exit)            │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                        │
│  ┌─────────────────────────────────┼────────────────────────────────────┐  │
│  │         KeypointFillMode        │                                    │  │
│  │  ┌──────────────────────────────▼────────────────────────────────┐  │  │
│  │  │  activate(gid) ──► 计算缺失关键点 ──► _LabelCycle.activate()  │  │  │
│  │  │  get_next_label_and_group_id() ──► (label, gid)               │  │  │
│  │  │  advance() ──► 推进 cycle / 完成则 deactivate()               │  │  │
│  │  │  refresh() ──► 重新计算缺失列表                               │  │  │
│  │  │  deactivate() ──► 清理状态 + 恢复选择模式                     │  │  │
│  │  └───────────────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│  ┌─────────────────────────────────┼────────────────────────────────────┐  │
│  │        KeypointToolWindow       │ (批量模式窗口)                      │  │
│  │  ┌──────────────────────────────▼────────────────────────────────┐  │  │
│  │  │  KeypointDockContent                                            │  │  │
│  │  │    ├─ refresh_all() ◄──── canvas.new_shape (external)         │  │  │
│  │  │    ├─ switch_to_person(gid, activate=True/False)              │  │  │
│  │  │    ├─ _get_person_data() ──► 遍历 label_list                   │  │  │
│  │  │    └─ _update_keypoint_list() ──► 高亮当前待标注点           │  │  │
│  │  └───────────────────────────────────────────────────────────────┘  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Canvas (视图层)                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  mousePressEvent (create_mode == "point")                           │    │
│  │    ├── Shape(shape_type="point")                                    │    │
│  │    ├── add_point(pos)                                               │    │
│  │    └── finalise() ──► emit new_shape ──► LabelWidget.new_shape()   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              数据层                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Shape (shape_type="point", label="nose", group_id=1)               │    │
│  │  JSON: { "label": "nose", "points": [[x, y]],                       │    │
│  │          "group_id": 1, "shape_type": "point" }                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 详细调用链

### 2.1 入口：进入补标模式

**触发条件**
- 用户按下快捷键 `K`（或点击菜单 **Tool → Enter Keypoint Fill Mode**）
- 调用: `LabelWidget.enter_keypoint_fill_mode()`

**单目标模式（已选中 person）**
```
enter_keypoint_fill_mode()
    │  遍历 canvas.selected_shapes，查找 label="person" + group_id 的 rectangle
    ▼
keypoint_fill_mode.activate(person_shape.group_id)
    │  _get_existing_labels(gid) ──► 遍历 canvas.shapes 收集已有关键点
    │  计算 missing_labels = KEYPOINT_ORDER - existing
    ▼
_LabelCycle.activate(",".join(missing_labels))
    │  解析标签串，设置当前索引为 0
    ▼
keypoint_fill_mode.is_active = True
mode_activated.emit(gid, missing_count)
    │
    ▼
toggle_draw_mode(edit=False, create_mode="point")
    │  canvas.set_editing(False)
    │  canvas.create_mode = "point"
```

**批量模式（未选中 person）**
```
enter_keypoint_fill_mode()
    │  未找到选中的 person
    ▼
KeypointToolWindow.__init__(fill_mode, label_widget)
    │  KeypointDockContent.__init__()
    │    ├─ _setup_ui() ──► 构建 person_list / keypoint_list / progress_bar
    │    └─ _connect_signals() ──► 连接 fill_mode 信号 + 滚轮事件过滤器
    ▼
canvas.new_shape.connect(keypoint_tool_window.refresh_all)   [外部连接]
keypoint_tool_window.refresh_all()
    │  content_widget.refresh_all()
    │    └─ _get_person_data() ──► 遍历 label_list 统计所有 person
    ▼
keypoint_tool_window.show() / raise_()
    │
    ▼ (如果有未完成的 person)
content_widget.switch_to_person(min(incomplete_gids), activate=True)
    │  fill_mode.activate(gid) ──► 同单目标模式
    │  label_widget.toggle_draw_mode(edit=False, create_mode="point")
    │  canvas.setFocus()   [焦点归还，无需再点击画布]
```

---

### 2.2 工具窗口交互

#### 2.2.1 单击 person_list 项

```
person_list.itemClicked ──► _on_person_selected(item)
    │
    ├─ 若 fill_mode.is_active: deactivate()
    ├─ _sync_gid_filter(gid)        # 画面跟随切换
    ├─ current_group_id = gid
    ├─ _update_current_person_info()
    └─ canvas.setFocus()            # 焦点归还画布
```

**行为**: 仅切换画面目标（设置 gid filter），**不进入**补全模式。

#### 2.2.2 双击 person_list 项

```
person_list.itemDoubleClicked ──► _on_person_activated(item)
    │
    └─ switch_to_person(gid, activate=True)
        ├─ 若 fill_mode.is_active: deactivate()
        ├─ _sync_gid_filter(gid)
        ├─ current_group_id = gid
        ├─ 同步 person_list 选中状态
        ├─ fill_mode.activate(gid)      # 进入补全模式
        ├─ toggle_draw_mode(edit=False, create_mode="point")
        └─ canvas.setFocus()            # 焦点归还画布
```

**行为**: 切换画面目标 **并进入**补全模式。

#### 2.2.3 鼠标滚轮切换

```
person_list.WheelEvent ──► eventFilter()
    │
    ├─ delta > 0: switch_to_prev_person(activate=auto_activate)
    └─ delta < 0: switch_to_next_person(activate=auto_activate)
        │
        └─ switch_to_person(gid, activate=auto_activate)
            ├─ 若 fill_mode.is_active: deactivate()
            ├─ _sync_gid_filter(gid)
            ├─ current_group_id = gid
            ├─ 同步 person_list 选中状态
            ├─ [若 activate=True] fill_mode.activate(gid) + toggle_draw_mode(point)
            ├─ [若 activate=False] _update_current_person_info()
            └─ canvas.setFocus()
```

**auto_activate 来源**: `self.auto_activate_enabled`（"自动锁定目标"复选框状态）。

| 自动锁定目标 | 滚轮行为 |
|-------------|---------|
| **未勾选** | 切换画面 + 同步列表高亮，**不进入**补全模式 |
| **已勾选** | 切换画面 + 同步列表高亮，**自动进入**补全模式 |

---

### 2.3 核心循环：绘制关键点

**用户在 Canvas 上点击**
```
Canvas.mousePressEvent()
    │  create_mode == "point"
    ▼
self.current = Shape(shape_type="point")
self.current.add_point(pos)
self.finalise()
    │  self.shapes.append(self.current)
    │  self.store_shapes()
    ▼
emit new_shape()
    │
    ▼
LabelWidget.new_shape()
    │  keypoint_fill_mode.is_active == True
    ▼
keypoint_fill_mode.get_next_label_and_group_id()
    │  返回 (_LabelCycle.current_label, _target_group_id)
    ▼
shape.label = label          # 例如 "nose"
shape.group_id = group_id    # 例如 1
self.add_label(shape)        # 添加到 label_list
canvas.shapes_backups.pop()
canvas.store_shapes()
    ▼
keypoint_fill_mode.advance()
    │  _LabelCycle.advance() ──► 索引 +1
    │  如果已经是最后一个关键点:
    │      deactivate() ──► mode_deactivated.emit()
    │      label_widget.set_edit_mode()   (通过 KeypointDockContent._on_fill_mode_deactivated)
    │  否则:
    │      current_label_changed.emit(new_label, idx, total)
```

---

### 2.4 状态同步与刷新

**Undo 后刷新**
```
LabelWidget.undo_shape_edit()
    │  恢复 shapes
    ▼
keypoint_fill_mode.refresh()
    │  重新计算当前 gid 的 missing_labels
    │  如果全部完成 ──► deactivate()
    │  否则 ──► _LabelCycle.activate(new_missing_string)
```

**删除 Shape 后刷新**
```
LabelWidget.delete_selected_shape()
    │  canvas.delete_selected() ──► 从 shapes 移除
    │  remove_labels() ──► 从 label_list 移除
    ▼
keypoint_fill_mode.refresh()   [v4.0.0-beta.4+ 新增]
    │  同上
```

---

### 2.5 退出补标模式

**自动退出**
- 当 `_LabelCycle` 推进到最后一个缺失关键点并完成标注时，`advance()` 内部调用 `deactivate()`
- 或者用户切换绘图模式（`toggle_draw_mode(edit=True)` 或 `create_mode != "point"`）

**手动退出**
- 快捷键触发其他工具 / 用户按 Esc / 切换模式
- `LabelWidget.exit_keypoint_fill_mode()`
  - `keypoint_fill_mode.deactivate()`
  - 清除 `gid_filter_combobox` 筛选
  - `self.set_edit_mode()`

---

### 2.6 批量模式导航（快捷键）

```
快捷键 Ctrl+Shift+[  /  Ctrl+Shift+]
    │
    ▼
LabelWidget.switch_to_prev_person() / switch_to_next_person()
    │
    ▼
KeypointDockContent.switch_to_prev_person() / switch_to_next_person()
    │  获取 person_data 的有序 gid 列表
    │  计算循环索引
    ▼
KeypointDockContent.switch_to_person(gid, activate=True)
    │  如果 fill_mode.is_active: deactivate()
    │  _sync_gid_filter(gid) ──► 设置 gid_filter_combobox
    │  同步 person_list 选中状态
    ▼
fill_mode.activate(gid)
toggle_draw_mode(edit=False, create_mode="point")
canvas.setFocus()
```

---

## 3. 信号连接汇总

| 信号发射方 | 信号 | 接收方 / Slot | 连接位置 |
|-----------|------|--------------|---------|
| `Canvas` | `new_shape` | `KeypointToolWindow.refresh_all` | `LabelWidget.enter_keypoint_fill_mode()` / `toggle_keypoint_tool_window()` |
| `KeypointFillMode` | `mode_activated` | `KeypointDockContent._on_fill_mode_activated` | `KeypointDockContent._connect_signals()` |
| `KeypointFillMode` | `mode_deactivated` | `KeypointDockContent._on_fill_mode_deactivated` | `KeypointDockContent._connect_signals()` |
| `KeypointFillMode` | `current_label_changed` | `KeypointDockContent._on_label_changed` | `KeypointDockContent._connect_signals()` |
| `_LabelCycle` | `label_changed` | `KeypointFillMode.current_label_changed` | `KeypointFillMode.__init__()` |
| `person_list` | `itemClicked` | `KeypointDockContent._on_person_selected` | `KeypointDockContent._connect_signals()` |
| `person_list` | `itemDoubleClicked` | `KeypointDockContent._on_person_activated` | `KeypointDockContent._connect_signals()` |
| `person_list` | `WheelEvent` (拦截) | `KeypointDockContent.eventFilter()` | `KeypointDockContent._connect_signals()` |

> **注意**: `canvas.new_shape` 到 `KeypointDockContent.refresh_all` 的连接由 **LabelWidget** 在创建 `KeypointToolWindow` 实例时统一完成，不在 `KeypointDockContent` 内部连接，以避免重复。

---

## 4. 配置项

```yaml
# anylabeling/configs/xanylabeling_config.yaml

auto_activate_keypoint_fill: false   # 切换图片时是否自动激活（单对象场景）
                                     # 也控制滚轮切换时是否自动进入补全模式

shortcuts:
  enter_keypoint_fill_mode: K
  toggle_keypoint_tool_window: Ctrl+K
  switch_to_prev_person: Ctrl+Shift+[
  switch_to_next_person: Ctrl+Shift+]
```

---

## 5. 关键类职责

| 类 | 文件 | 职责 |
|---|---|------|
| `KeypointFillMode` | `widgets/keypoint_fill_mode.py` | 管理 group_id 绑定、缺失关键点计算、标签循环推进 |
| `_LabelCycle` | `widgets/keypoint_fill_mode.py` | 标签序列的解析、激活、前进、后退、跳转 |
| `KeypointToolWindow` | `widgets/keypoint_tool_window.py` | 独立浮动窗口容器，持有 `KeypointDockContent` |
| `KeypointDockContent` | `widgets/keypoint_tool_window.py` | 窗口内容组件：人员列表、关键点状态、进度条、自动激活开关、滚轮事件处理、焦点归还 |
| `LabelWidget` | `label_widget.py` | 控制器：创建/销毁窗口、响应快捷键、桥接 Canvas 与 FillMode |
| `Canvas` | `widgets/canvas.py` | 视图交互：鼠标点击创建 point shape、发射 `new_shape` 信号 |

---

## 6. 常见问题排查

| 现象 | 可能原因 | 排查点 |
|------|---------|--------|
| 按 K 没反应 | 当前图片没有 `group_id` 的 person | `enter_keypoint_fill_mode()` → `person_data` 为空 |
| 标注完一个点标签没自动切换 | `keypoint_fill_mode.advance()` 未执行 | `LabelWidget.new_shape()` 中的 fill mode 分支 |
| 删除一个关键点后列表未更新 | `refresh()` 未在删除后调用 | `delete_selected_shape()` 末尾 |
| 工具窗口数据不刷新 | `canvas.new_shape` 信号未连接 | `LabelWidget` 中创建窗口时的信号连接 |
| 切换到下一个人后模式未激活 | `switch_to_person()` 中 `activate()` 返回 False | 该 gid 的所有关键点是否已完成 |
| 单击 person 后仍需点击画布才能标注 | `canvas.setFocus()` 未执行 | `_on_person_selected()` / `switch_to_person()` 末尾 |
| 滚轮切换后没进入补全模式 | "自动锁定目标"未勾选 | `auto_activate_cb` 状态 |
| 滚轮切换后列表高亮未同步 | `setCurrentItem()` 未执行 | `switch_to_person()` 中的列表同步逻辑 |

---

## 7. 近期变更 (v4.0.0-beta.4+)

1. **单击/双击行为拆分**: 单击仅切换画面目标，双击才进入补全模式。
2. **鼠标滚轮支持**: 在 `person_list` 区域滚动滚轮可快速切换人员。
3. **自动锁定目标控制滚轮**: 滚轮切换是否自动进入补全模式受 "自动锁定目标" 复选框控制。
4. **焦点自动归还**: 所有切换操作（单击/双击/滚轮/快捷键）完成后自动将焦点还给画布，无需再点击一下。
5. **列表高亮同步**: 切换人员后自动同步 `person_list` 的选中高亮状态。

---

*文档生成时间: 2026-04-29*
