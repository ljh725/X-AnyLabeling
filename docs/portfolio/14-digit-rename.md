# 14 · 数字快捷键改名
#### Digit Shortcut Rename

> 选中一个或多个 shape，按数字键**瞬间批量重命名**为该键绑定的 label——无需打开标签对话框、无需手敲。upstream beta.4 完全没有此能力，这是从零实现的扩展，含独立的 `DigitRenameManager`（400 行）和配置对话框。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

改一个已有 shape 的 label，原生流程：

```
双击 shape → 弹出标签对话框 → 在 label 下拉里翻找 → 选中 → 确定
→ 一次只改一个，改 50 个标错的框要点 50 次对话框
```

尤其在「AI 预标注批量修正」场景：模型把一批 head 标成了 face，要逐个改回去——对话框流程慢到无法用。

---

## 方案：选中 + 数字键 = 批量重命名

`DigitShortcutMode = rename`（默认）下，编辑模式选中 shape 后按数字键，**所有选中 shape** 的 label 立刻改成该键绑定的 label：

```
选中 5 个 shape（它们 label 各异）
  → 按数字键 3（绑定了 "head"）
  → 5 个全部变成 head，一步到位
```

触发条件（`is_rename_mode_active`）：`canvas.editing()` 且 `selected_shapes` 非空。

---

## 技术亮点

### 1. 与 upstream 绘制分流互斥

upstream 的 `create_digit_mode` 只处理「按数字键进绘制」。我在入口加 `rename` 分流：编辑模式 + 有选中 → 走改名；否则走原绘制路径。两个模式通过 `digit_shortcut_mode` 配置切换，**互斥不冲突**。

### 2. 独立管理器 + 完整副作用链

`DigitRenameManager`（400 行）的 `_apply_rename` 一次重命名完整处理所有副作用：

- `canvas.store_shapes()` 推 undo 快照（可撤销）
- `shape.label = rename_label` 改值
- 更新列表项文本 + 背景色
- 加入 label 历史、更新唯一 label 列表
- 标记 dirty、刷新筛选

### 3. 独立配置 + 独立对话框

`rename_shortcuts` 配置（`{index: {label}}`）与 draw 的 `digit_shortcuts` **分开**——改名映射和绘制映射互不干扰。`DigitRenameShortcutDialog`（10 行表格，`Alt+R` 打开）独立编辑。

### 4. 与分页协同

改名也走 `digit_page_manager.get_actual_index`，所以分页扩展（[→ 13](13-digit-shortcut-pagination.md)）对改名同样生效——多页时每页 10 个改名槽位。

---

## 代码定位

| 位置 | 说明 |
|------|------|
| [`digit_rename_manager.py`](../../anylabeling/views/labeling/widgets/digit_rename_manager.py) | 400 行，`DigitRenameManager` + `DigitRenameShortcutDialog` |
| [`digit_rename_manager.py:83-87`](../../anylabeling/views/labeling/widgets/digit_rename_manager.py) | `is_rename_mode_active` 触发判定 |
| [`digit_rename_manager.py:118-193`](../../anylabeling/views/labeling/widgets/digit_rename_manager.py) | `_apply_rename` 核心重命名 + 副作用链 |
| [`digit_rename_manager.py:203`](../../anylabeling/views/labeling/widgets/digit_rename_manager.py) | `DigitRenameShortcutDialog` 配置对话框 |
| [`label_widget.py:3907-3909`](../../anylabeling/views/labeling/label_widget.py) | `create_digit_mode` rename 分流入口 |
| [`label_widget.py:3686`](../../anylabeling/views/labeling/label_widget.py) | `digit_rename_shortcut_manager` action（Alt+R） |

提交：`0d3d5f9`（ljh725，2026-04-30，全新加入），后经 `fe070e7`（健壮性）、`3d43001`（功能修改）加固。upstream baseline `b99ef725` 无任何改名代码。

---

## 与其他数字快捷功能的关系

| 功能 | 触发 | 文档 |
|------|------|------|
| 改名（本篇） | 编辑模式 + 选中 + 数字键 | 14 |
| 分页 | draw/rename 共用的索引层 | [→ 13](13-digit-shortcut-pagination.md) |
| 绑定绘制 | bind_draw 模式 + 选中来源 + 数字键 | [→ 08](08-digit-bind-draw.md) |

三个扩展共享 `digit_page_manager` 分页层，在 `create_digit_mode` 入口按 `digit_shortcut_mode` 和当前状态分流。

---

## 截图

> `[截图待补]` — 计划补充：多选 shape → 按数字键 → 批量改名的演示
