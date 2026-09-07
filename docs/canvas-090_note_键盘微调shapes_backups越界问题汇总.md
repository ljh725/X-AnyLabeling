# IndexError: shapes_backups 越界问题汇总

> 分析日期：2026-09-07
> 分支：`feature/selection-optimization`
> 状态：已定位根因，待修复

## 一、问题现象

| 项 | 内容 |
|---|---|
| 报错位置 | `anylabeling/views/labeling/widgets/canvas.py:6582`，`keyReleaseEvent` |
| 异常类型 | `IndexError: list index out of range` |
| 出错语句 | `self.shapes_backups[-1][index].points != self.shapes[index].points` |
| 触发时机 | 键盘移动/旋转选中的形状后，**松开按键的瞬间** |
| 影响 | 按键释放事件崩溃，微调动作的状态收尾（`store_shapes`、`shape_moved` 信号）未执行，undo 备份与形状状态可能脱节 |
| 涉及工作流 | 质检复核 / 数据检查导航、数据集缩略图导航、标签列表点击选中、Ctrl+A 全选 |

原始 traceback：

```text
Traceback (most recent call last):
  File "D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4\anylabeling\views\labeling\widgets\canvas.py", line 6582, in keyReleaseEvent
    self.shapes_backups[-1][index].points
    ~~~~~~~~~~~~~~~~~~~^^^^
IndexError: list index out of range
```

## 二、根因

`keyReleaseEvent` 在比对「移动前 vs 移动后」的 points 时，**裸访问**
`self.shapes_backups[-1][index]`，未做任何越界保护。此刻
`shapes_backups` 为空列表（或最后一帧短于当前 shapes 列表）。

仓库里存在同一比对的两份拷贝，一份有保护、一份没有：

| 位置 | 保护情况 |
|---|---|
| `store_moving_shape()`，canvas.py:687-689 | ✅ 有保护：`len(shapes_backups) > 0 and index < len(shapes_backups[-1])` |
| `keyReleaseEvent()`，canvas.py:6582 | ❌ 无保护，直接下标访问 |

## 三、触发链路（三阶段）

### 阶段 1：备份被清空且不落盘

1. 打开文件 → `load_file` → `reset_state()` → `canvas.reset_state()`
   清空 `shapes_backups = []`（canvas.py:6811）
2. 随后 `load_shapes(..., store_backup=False)`（label_widget.py:9634）走
   「延迟初始备份」机制：只置 `_pending_initial_backup = True`，
   **不追加任何备份**（canvas.py:6705-6709）

### 阶段 2：程序化选中，跳过备份冲刷

3. 程序化选中形状，不经过画布鼠标事件：
   - Inspector 导航 `_on_inspector_navigate`（label_widget.py:6654，
     同时服务「数据检查」和「质检复核」两个 Tab）→ `canvas.select_shapes([shape])`
   - 缩略图导航 `_navigate_from_thumbnail`（label_widget.py:4636，
     source="inspector"）
4. 关键漏洞点：`_pending_initial_backup` 的**唯一冲刷点**在画布
   `mousePressEvent`（canvas.py:2311-2312）。程序化选中不触发
   mousePress，备份始终保持为空

### 阶段 3：键盘移动 → 释放时崩溃

5. 按方向键 → `keyPressEvent` → `_editing_arrow_dispatch`
   （canvas.py:6388）→ `move_by_keyboard` 置 `moving_shape = True`
   （canvas.py:6309），该函数也不调 `store_shapes()`；按 Z/X/C 旋转键走
   `rotate_by_keyboard`，同理置 `rotating_shape = True`
6. 松开按键 → `keyReleaseEvent`（canvas.py:6566）→ 前置守卫全部通过
   （`editing()` ✓、`moving_shape` ✓、选中形状在列表中 ✓）→
   对空列表取 `[-1]` → **IndexError**

链路总览：

```text
load_file
  └─ reset_state → canvas.reset_state → shapes_backups = []          [备份清空]
  └─ load_shapes(store_backup=False) → _pending_initial_backup=True [延迟落盘]
       └─ 程序化 select_shapes（无画布 mousePress）                    [冲刷被跳过]
            └─ 方向键 keyPress → move_by_keyboard → moving_shape=True
                 └─ keyReleaseEvent → shapes_backups[-1][index] → IndexError
```

## 四、复现条件与受影响工作流

**最小复现步骤**：打开一张带标注的图 → 不在画布上点击，通过以下任一
方式程序化选中形状 → 按方向键微调 → 松开 → 崩溃。

| 工作流 | 是否受影响 | 原因 |
|---|---|---|
| 质检复核 / 数据检查导航跳转 | ✅ 受影响 | `load_file` + `select_shapes` 全程序化 |
| 数据集缩略图导航 | ✅ 受影响 | 同上（label_widget.py:4636） |
| 右侧标签列表点击选中 | ✅ 受影响 | 点击落在 QListWidget，不触发画布 mousePress |
| Ctrl+A 全选后方向键微调 | ✅ 受影响 | 全选不经画布 |
| 常规手标（画布点选 → 键盘微调） | ❌ 不受影响 | 画布 mousePress 会冲刷延迟备份（canvas.py:2311） |

## 五、为什么常规流程踩不到

手动标注流程中，用户总是先在**画布上点击**选中形状，mousePress 会把
`_pending_initial_backup` 冲刷进 `shapes_backups`，之后的键盘微调比对
就是安全的。本分支新增的质检复核/缩略图导航工作流恰好是「程序化选中 +
键盘微调」的组合，绕过了这唯一的冲刷点——属于**新工作流暴露的老防御
缺口**，而非新引入的逻辑错误。

## 六、修复建议（两层，建议都做）

1. **防御层**（必做）：`keyReleaseEvent` 的比对补上与
   `store_moving_shape`（canvas.py:687-689）完全一致的前置条件——
   `len(self.shapes_backups) > 0 and index < len(self.shapes_backups[-1])`
2. **根因层**（建议）：在 `move_by_keyboard` / `rotate_by_keyboard`
   入口处，若 `_pending_initial_backup` 为 True 先冲刷一次备份；或在
   程序化 `select_shapes` 路径上落盘初始备份，保证「选中即可安全微调」
   的不变量

## 七、关键代码位置速查

| 位置 | 作用 |
|---|---|
| canvas.py:6566-6594 | `keyReleaseEvent`，崩溃点（6582） |
| canvas.py:674-704 | `store_moving_shape`，带保护的同款比对（687-689） |
| canvas.py:6302-6321 | `move_by_keyboard` / `rotate_by_keyboard`，置位 `moving_shape`/`rotating_shape` |
| canvas.py:6405-6434 | `_editing_arrow_dispatch`，方向键分发 |
| canvas.py:659-672 | `store_shapes`，含 `_pending_initial_backup` 冲刷逻辑 |
| canvas.py:2311-2312 | mousePress 中的唯一备份冲刷点 |
| canvas.py:6687-6709 / 6811 | `load_shapes`（store_backup=False 路径）/ `reset_state`（清空备份） |
| label_widget.py:9634-9638 | `load_file` 以 store_backup=False 加载 |
| label_widget.py:6654-6702 | `_on_inspector_navigate`，程序化选中的入口之一 |
| label_widget.py:4607-4643 | `_navigate_from_thumbnail`，程序化选中的入口之二 |

> 注：行号基于 `feature/selection-optimization` 分支工作区当前状态，
> 后续改动可能使行号偏移，以函数名/语句内容为准。
