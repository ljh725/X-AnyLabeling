# 07 · 新建 person 自动实例化
#### Auto Create Person Instance

> 当标注员手动新建 `person` 矩形框时，系统自动生成一个新的 `group_id`，免去手动输入人物实例 ID 的负担。它是一套 `bind_draw > auto_person_instance > auto_use_last_gid > 手动输入` 优先级解析链中的关键一环。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

姿态/人物标注中，每个 `person` 都对应一个独立的**人物实例**（用 `group_id` 标识），其下的 `head`/`face` 框共享同一个 `group_id`。原生流程的痛点：

```
画一个 person 框
  → 弹出标签对话框，输入 "person"
  → 手动在 group_id 字段敲一个数字（还要回忆"现在到第几个了"）
  → 画下一个 person，再手动敲下一个数字
  → 容易跳号、重号、错号
```

人工管理 `group_id` 是**纯机械、易错、低价值**的操作——完全可以从已有数据自动推断（取 `max(existing) + 1`）。

---

## 方案：手动绘制路径上的按需生成

核心思路：**在 `new_shape` 提交一个 `person` 矩形时，自动生成新的 `group_id`**。

触发条件（同时满足才生成）：

| # | 条件 | 意图 |
|---|------|------|
| 1 | 新框 `label == "person"` | 只有 person 需要开新实例 |
| 2 | 新框 `shape_type == "rectangle"` | person 多边形/点不触发 |
| 3 | 设置 `auto_person_instance` 开启 | 用户可控开关 |
| 4 | 无 `bind_draw` pending（`bound is None`） | 不与「数字快捷绑定绘制」冲突 |
| 5 | 走手动绘制 `new_shape` 路径 | **不作用于 auto-labeling 结果落地**（Non-Goal） |

```python
# label_widget.py:6584-6614
def _apply_auto_person_instance(self, text):
    """Feature 1: 手动绘制 person 矩形时为它生成新的 group_id。"""
    if (
        text == "person"
        and getattr(self.canvas.shapes[-1], "shape_type", None)
        == "rectangle"
        and self._config.get("auto_person_instance")
    ):
        new_gid = self.canvas.gen_new_group_id()  # max(existing) + 1
        self.status(self.tr("已创建 person #%d") % new_gid, 2000)
        ...
        return new_gid
    return None
```

`group_id` 来源是 `canvas.gen_new_group_id()`——扫描当前所有 shape 取 `max(group_id) + 1`，天然避免重号。

---

## 技术亮点

### 1. 优先级解析链：一处仲裁，零冲突

`new_shape` 中有**三个**竞相为 `group_id` 赋值的来源。我把它们排成一条明确的优先级链，用 `if/elif` 串联，避免互相覆盖：

```
bind_draw pending  >  auto_person_instance  >  auto_use_last_gid  >  手动输入
（数字快捷绑定）     （本功能）                （沿用上一组 ID）
```

```python
# label_widget.py:6668-6714（节选）
if self.digit_to_label is not None:
    text = self.digit_to_label
    self.digit_to_label = None
    bound = self._consume_digit_bind(last_gid)   # ① bind_draw 优先
    if bound is not None:
        text, group_id = bound
    elif last_gid is not None:
        group_id = last_gid                        # ② auto_use_last_gid

# ③ auto_person_instance：仅在 bind_draw 未消费时覆盖
if bound is None:
    person_gid = self._apply_auto_person_instance(text)
    if person_gid is not None:
        group_id = person_gid                      # 覆盖 auto_use_last_gid
```

**关键守卫**：`if bound is None`——只要 `bind_draw` 消费了 pending，`auto_person_instance` 根本不会被调用，从结构上杜绝冲突。

### 2. 与 `auto_use_last_label` 正交共存

`auto_use_last_label`（连续画框复用上一个 label）和 `auto_person_instance`（每个 person 生成新 gid）看似矛盾，实则**正交**：

- `auto_use_last_label` 控制 **label 是否复用** → 连续画 person，label 自动填 "person"
- `auto_person_instance` 控制 **group_id 是否新开** → 每个 person 拿到不同的 gid

两者同时开启时，连续绘制 person 会得到「同名 label + 不同 group_id」——这正是想要的行为。状态栏会提示「连续绘制 person 将自动生成新的 group_id」。

### 3. Non-Goal 用静态测试钉死

「不作用于 auto-labeling 结果落地」是硬约束。我没有只靠注释保证，而是用 `inspect.getsource` 写了**静态源码级断言**：

```python
# tests/test_auto_person_instance.py:341
def test_7_16_auto_labeling_path_does_not_use_auto_person_instance():
    new_shape_src = inspect.getsource(LabelingWidget.new_shape)
    finish_src = inspect.getsource(LabelingWidget.finish_auto_labeling_object)
    assert "auto_person_instance" in new_shape_src       # 手动路径必须有
    assert "auto_person_instance" not in finish_src      # 自动落地路径必须没有
```

任何人将来若误把该逻辑挪进 auto-labeling 落地路径，测试立刻红。

### 4. 按需读取，零状态同步

设置项**不缓存到 widget 属性**——`runtime_applier` 只把 key 路由进 `behavior_flags` 桶，没有 eager 同步动作。每次 `new_shape` 时现读 `self._config.get("auto_person_instance")`。

好处：在设置对话框里改完点确定，下一个绘制的 person 立刻吃到新行为，无需额外的「应用」步骤或状态转移逻辑。

---

## 代码定位

| 位置 | 说明 |
|------|------|
| [`label_widget.py:6584-6614`](../../anylabeling/views/labeling/label_widget.py) | `_apply_auto_person_instance` 触发助手 + gid 生成 |
| [`label_widget.py:6702-6714`](../../anylabeling/views/labeling/label_widget.py) | `new_shape` 中优先级解析 + `if bound is None` 守卫 |
| [`label_widget.py:6567-6582`](../../anylabeling/views/labeling/label_widget.py) | `_consume_digit_bind`（bind_draw 消费 + 回填） |
| [`label_widget.py:8809`](../../anylabeling/views/labeling/label_widget.py) | `finish_auto_labeling_object`（Non-Goal 路径，0 引用该 key） |
| [`schema.py:402-416`](../../anylabeling/views/labeling/settings/schema.py) | `SettingField("auto_person_instance", "bool", "General"/"Behavior"/"Manual Annotation")` |
| [`xanylabeling_config.yaml:240`](../../anylabeling/configs/xanylabeling_config.yaml) | 默认 `false` |
| [`runtime_applier.py:280`](../../anylabeling/views/labeling/settings/runtime_applier.py) | 路由到 `apply_behavior_flags`（按需读，无 eager 同步） |

---

## 测试覆盖

[`tests/test_auto_person_instance.py`](../../tests/test_auto_person_instance.py)（8 个测试函数，headless Qt）：

| 测试 | 验证点 |
|------|--------|
| `test_7_1_*` | 开启后生成 `max(existing)+1`（已有 gid 1,3 → 新框得 4） |
| `test_7_2_*` | 与 `auto_use_last_label` 共存：label 复用、gid 新开 |
| `test_7_3_*` | **优先级**：与 `auto_use_last_gid` 同时开 → 新 gid 覆盖沿用值（last_gid=2 → 得 3 而非 2） |
| `test_bind_draw_*` | **优先级**：`bind_draw` 的 gid(7) 不被本功能覆盖 |
| `test_7_1b_*` | 关闭时 `gid is None`（回退到原生行为） |
| `test_7_1c_*` | 仅 rectangle 触发：person 多边形不生成 gid |
| `test_7_3b_*` | 仅 person 触发：head/face 不生成 gid |
| `test_7_16_*` | **静态 Non-Goal**：key 在 `new_shape` 里、不在 `finish_auto_labeling_object` 里 |

另有跨功能测试 `tests/test_digit_bind_draw_manager.py:223` 验证「未选中 + person 数字键 → 启动未绑定 person 绘制」的边界。

---

## 与相关功能的边界

| 场景 | 行为 |
|------|------|
| 未选中对象，目标是 person/rectangle，本功能开启 | 进入新建 person 实例绘制，完成后生成新 gid |
| 选中 person/head/face 来源对象 | 进入 [数字快捷绑定绘制（08）](08-digit-bind-draw.md)，继承/回填来源 gid |
| 未选中对象，目标是 head/face | 拒绝，提示先选中来源对象 |

这条优先级链是本功能与「数字快捷绑定绘制」协同的核心契约，双方都通过 `bound is None` / `_can_start_unbound_person_instance` 双向守卫。

---

## 截图

> `[截图待补]` — 计划补充：连续绘制 person 自动递增 group_id 的状态栏演示
