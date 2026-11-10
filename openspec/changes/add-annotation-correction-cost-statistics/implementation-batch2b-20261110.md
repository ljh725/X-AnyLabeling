# 第 2 批 B 段实施记录（2026-11-10）：几何归属、类别改名与计时接线

范围：tasks.md **4.5、4.6、6.1、6.3**（本批确认完成），以及 6.2/6.4–6.6 的剩余缺口说明。
依据：[批次 2 需求规格](../../../.local/stage/batch2-doublecheck-spec.md)（用户已确认：4.5+4.6+6.x、面板继续悬浮子窗口、全局改名仅影响已有轮次）。

## 1. 4.5 几何编辑归属到对象

**改动**（`label_widget.py::_on_geometry_committed`）：

```python
notify_metrics(self, "edit", "geometry", changed=list(self.canvas.shapes))
```

画布在一次交互结束时把全部形状交给 controller；`CorrectionRound.patch()` 与当前草稿做集合差集，**只有几何真正变化的对象**被记录。拖动帧内不写事件，也不逐帧调用。

**验证**（8 个用例，`tests/test_correction_metrics/test_geometry_wiring.py`）：

- `shape_moved.emit()` 实测 **6 处**：`canvas.py` 537（store_moving_shape）、1659（笔刷提交）、5870（Alt+滚轮）、6201（keyRelease），`point_fit.py:316`（Shift 与 Shift+Alt 共用提交点）、`rectangle_edge.py:266`（拖边/拖角）。拖动、拖边、两种单点拟合、键盘微调**全部**经由唯一槽 `_on_geometry_committed`。
- **无双触发**：`mouseReleaseEvent` 在点拟合/拖边消费后提前 `return`，走不到 `store_moving_shape`；后者另有 `moving_shape` + 逐对象比点 + 命中即 `break` 三重守卫。
- **无漏发需要修的边界**，源码零改动。唯一理论缺口（`keyReleaseEvent` 只比较 `selected_shapes[0]`）因 `bounded_move_shapes` 用同一 pos 全局钳制、锁定分组提前返回而不可达，已记录理由。
- 断言精确值：2 框移动 = 1 事务 / 2 touches / 2 unique / `geometry_changed=2`，且不再出现 `unidentified-geometry`；未变化 = 0 事务；同内容重复通知 3 次事务恒为 1；多选拖边 = 1 事务；键盘微调每次 1 事务。

**已知口径问题（未改，仅记录）**：Alt+滚轮一格记一笔事务；拖拽中鼠标移出控件会把一次拖拽拆成两笔；点拟合会多推一版 undo 快照（不影响统计净值）。

## 2. 4.6 全局类别改名

**改动**（`controller.taxonomy_saved`）：

```python
taxonomy_saved(image_path, label_path=None, shapes=None, mapping=None, comparable=True)
```

与 `LabelModifyDialog.modify_label()` 既有调用对齐；**只对已有轮次生效**：当前打开的图片应用映射，其它图片经 `store.latest()` 命中已有轮次后应用；没有轮次的历史图片直接返回 False，**不新建轮次**（用户已确认）。

**验证**（5 个用例，`tests/test_correction_metrics/test_taxonomy_wiring.py`）：

| 场景 | 实测 |
| --- | --- |
| 一对一 cat→feline | `class_changed=0`、`unchanged=3`、`comparable=True`、transactions=0 |
| 先个人改 dog→cat 再全局改名 | `transactions=1`、`class_changed=1`、`unchanged=2` |
| 合并 cat+dog→animal | `comparable=False`，C/modified/unchanged/两率均 None，几何仍可算 |
| 未纳入统计的图片 | `count()` 0→0，不建轮次，磁盘改名仍生效 |
| 非当前图片的已有轮次 | `store.latest` 命中同一 round_id 并应用 |

`taxonomy_saved` 五参数未抛 TypeError；`logger.exception` 与外层 `logger.error` 路径均未被命中（logger spy + 返回 True 证明）。

**测试可信度教训（重要）**：只断言净变化（C=0/unchanged=n）**不能证明通知发生过**——通知从未触发时数值完全相同。最终用例同时断言轮次内部状态（draft 标签 + `alias["cat"]=="feline"`）作为真正接线证据。

## 3. 6.x 计时

**接线**（`controller.py`）：

- `_install_clock_adapter()`：有 Qt 时用 `clock_adapter.QtClockAdapter` 接管计时（前台/最小化/会话挂起/锁屏 + 精确心跳），controller 改用适配器持有的 `WorkClock`，并停用自己的秒表；
- `time_checkpoint(round_id, session_id, totals, closed)`：适配器回调写入**绝对快照**（重复心跳不累加），非当前 round 忽略；
- `pause()` 走 `WorkClock.change(paused=...)`，显式暂停不会被前台激活解除。

**验证**（30 个用例，`tests/test_correction_metrics/test_timing.py`）：状态互斥与优先级、各状态和=墙钟（31 s 精确）、`audit.segments` 首尾相接不重叠、119/120/130 s 空闲阈值与 confirm 只扣一次、`max_gap` 边界（5 s 计入 / 30 s 记缺口）、时钟回退无负时长、`adjusted_working == working - excluded_idle`、`audit` 可 JSON 序列化；另 3 个 controller 层用例证明绝对快照不翻倍。缺陷 0。

## 4. 本批验证汇总

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 统计测试全量 | `pytest tests/test_correction_metrics -q -p no:cacheprovider` | **159 passed / 0 failed**（3.06 s） |
| 新增用例 | — | geometry 8 + taxonomy 5 + timing 30 + wiring 2 = 45 |
| OpenSpec 校验 | `openspec validate add-annotation-correction-cost-statistics --strict` | valid |

## 5. 仍然未完成的项

| 任务 | 缺口 |
| --- | --- |
| 4.1 / 4.2 | `AutoLabelingResult` 无 `provenance`；替换/追加模式缺字段时默认 replacement |
| 4.3 | 批量预标注直写 JSON 未接入 |
| 4.4 | 创建/删除/复制/粘贴 hooks 已带对象，但**缺逐入口 GUI 回归** |
| 4.7 | 撤销缺 `undo_of` 关联；密集复核确认未接入 |
| 5.2–5.6 | 取消导航未验证；批量完成、完成失效、质量状态展示未做 |
| 6.2 | 标注弹窗/图片可交互状态未接线；取消切图不分配时间未验证 |
| 6.4–6.6 | 空闲提示 UI 与扣除确认、模型运行与阻塞等待单列、崩溃尾段处理未做 |

## 6. 术语歧义（AMB-1）

任务书把 `closed` 描述为最低优先级；实现先判 `completed/attach(None)` → `closed`（即使同时 paused）。按 work-timing spec「明确完成停止计时」，当前实现更合理；测试按实现锁定，未改代码。
