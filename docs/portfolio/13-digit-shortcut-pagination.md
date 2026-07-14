# 13 · 数字快捷键分页扩展
#### Digit Shortcut Pagination Extension

> upstream beta.4 已有基础「按数字键进入对应 label 的绘制」，但**只有 0-9 共 10 个槽位**。本扩展给数字键加**分页层**：10 个物理键 × N 页 = 最多 10N 个逻辑槽位，`F1` 切页，单页时与 upstream 行为完全一致（向后兼容）。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 诚实定位：扩展层 vs upstream 基线

**这是对 upstream 已有功能的扩展，不是从零新建。**

upstream baseline `b99efef`（CVHub520 beta.4）**已经有**：
- `create_digit_mode(digit_num)` — 按数字键查 `digit_shortcuts[digit_num]`，取 label+mode 进入绘制
- `digit_shortcut_0..9` 十个 action（绑物理键 "0".."9"）
- `DigitShortcutDialog` — 固定 10 行的编辑对话框

**我的扩展**（commit `eaa6f40`）：在 `create_digit_mode` 里加一层 `get_actual_index` 索引映射，让物理键按当前页解析到不同逻辑槽位。

---

## 解决的痛点

一个标注任务常常需要 **>10 种** label+shape_type 组合（person/head/face 矩形 + 各部位关键点 + 多边形……），但数字键只有 0-9：

```
10 个数字键 ← 但我有 15 种要画的 label
→ 只能牺牲 5 种，或者记住"数字 1 现在是 head 还是 keypoints？"
```

分页解决：每个物理键随当前页指向不同槽位，2 页 = 20 槽、3 页 = 30 槽。

---

## 方案：分页索引层

`DigitShortcutPageManager`（311 行，`QObject`）作为 `create_digit_mode` 和 `digit_shortcuts` 字典之间的**索引翻译层**：

```
物理键 digit_num ──get_actual_index──► 逻辑索引 actual_index ──► digit_shortcuts[actual_index]
                  current_page × 10 + digit_num
```

```python
# digit_shortcut_page_manager.py:151-172
def get_actual_index(self, digit_num: int) -> int:
    if not 0 <= digit_num <= 9:
        logger.warning("Invalid digit_num: %d, expected 0-9", digit_num)
        return digit_num
    return self._current_page * self.PAGE_SIZE + digit_num   # 页×10+键
```

例：page 0 + digit 5 → 索引 5；page 1 + digit 5 → 索引 15。`PAGE_SIZE = 10`。

---

## 技术亮点

### 1. 向后兼容：单页 = upstream 行为

默认 `digit_shortcut_pages = 1`，`is_single_page` 为 True，`get_actual_index` 返回 `0×10 + digit = digit`——与 upstream 单页系统**完全等价**。已有用户的配置零迁移。

### 2. 循环切页 + 信号通知

`switch_page()` 循环前进 `(current + 1) % total`，emit `page_changed` 信号；只有 1 页时警告。绑 `F1`，状态栏显示当前页信息。

### 3. 配置驱动页数

页数从 `digit_shortcut_pages` 配置读，`sync_to_config` 持久化。`_calculate_total_pages` 做边界校验。用户改配置即可扩缩槽位，无需改代码。

---

## 代码定位

| 位置 | 说明 |
|------|------|
| [`digit_shortcut_page_manager.py`](../../anylabeling/views/labeling/widgets/digit_shortcut_page_manager.py) | 311 行，`DigitShortcutPageManager`（分页层） |
| [`digit_shortcut_page_manager.py:151-172`](../../anylabeling/views/labeling/widgets/digit_shortcut_page_manager.py) | `get_actual_index` 核心映射 |
| [`label_widget.py:3914-3915`](../../anylabeling/views/labeling/label_widget.py) | `create_digit_mode` 调用分页索引 |
| [`label_widget.py:3928-3933`](../../anylabeling/views/labeling/label_widget.py) | `switch_digit_shortcut_page` action（F1） |

提交：`eaa6f40`（ljh725，2026-04-28）。upstream baseline `b99efef` 含无分页版本。

---

## 与其他数字快捷功能的关系

数字快捷键有三个互斥/协作的扩展，都在 `create_digit_mode` 入口分流：

| 功能 | 模式 | 文档 |
|------|------|------|
| 分页（本篇） | draw 模式下索引分页 | 13 |
| 改名 | 编辑模式下按数字键改 label | [→ 14](14-digit-rename.md) |
| 绑定绘制 | bind_draw 模式下继承 gid | [→ 08](08-digit-bind-draw.md) |

---

## 截图

> `[截图待补]` — 计划补充：F1 切页 + 状态栏页码提示
