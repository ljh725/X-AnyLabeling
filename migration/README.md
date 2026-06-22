# Pose Category Layout — 迁移包

将「类别分组」布局模式（`category`）迁移到目标项目所需的全部代码与说明。

## 文件清单

| 文件 | 用途 |
|------|------|
| `pose_category_layout.py` | **自洽主模块**。包含 `layout_category()` 及其全部依赖函数（`_body_part_group`/`_is_lateral_prefix`/`_head_lateral_rank`/`_original_label`/`_compute_bbox`）。零 host 项目依赖，只依赖 PyQt6 + 标准库。 |
| `test_pose_category_layout.py` | 自包含单元测试，含 mock 的 `PoseLabelItem`/常量，可独立运行。 |
| `README.md` | 本文件，迁移步骤清单。 |

## 布局效果

```
       [l_ear][l_eye][nose][r_eye][r_ear]   ← head(上沿横向)
    ┌────────────────────────────────┐
 [la]│                                │[ra]
 [la]│           person               │[ra]   ← arm(上部)
 [la]│                                │[ra]
 [ll]│                                │[rl]
 [ll]│                                │[rl]   ← leg(下部)
 [ll]│                                │[rl]
    └────────────────────────────────┘
```

- 头部 5 标签横排，nose 居中，左/右眼耳按前缀分居两侧
- la+ll 堆在 bbox 左侧（la 在上、ll 在下），各自内部按 Y 排序
- ra+rl 堆在 bbox 右侧（ra 在上、rl 在下）
- leader line 指回各自关键点

## 迁移步骤

### 1. 复制主模块

把 `pose_category_layout.py` 放到目标项目的布局模块目录（例如与现有 `pose_layout.py` 同级）。

### 2. 接入 dispatcher

在目标项目的布局分发函数（X-AnyLabeling 中为 `apply_layout()`）增加 `"category"` 分支：

```python
from .pose_category_layout import layout_category

def apply_layout(items, mid, bbox, layout_mode, ...):
    ...
    if layout_mode == "category":
        # 注意：显式传入 host 的常量，使迁移模块保持零依赖
        layout_category(
            items,
            mid,
            bbox,
            column_gap,
            coco_keypoint_index=COCO_KEYPOINT_INDEX,
            body_parts=BODY_PARTS,
        )
    elif layout_mode == "direct":
        ...
```

> **设计要点**：`layout_category()` 把 `COCO_KEYPOINT_INDEX` 和 `BODY_PARTS` 作为参数传入，而不是 import，这样迁移模块与 host 项目的常量定义解耦——无论目标项目如何命名/组织这两个常量，只需调用时传入即可。

### 3. 添加 UI 入口

在布局模式选择控件（X-AnyLabeling 中为 `pose_settings_panel.py` 的按钮组）增加一项：

```python
("category", self.tr("类别分组")),
```

### 4. 更新 config 枚举注释（可选）

```python
layout_mode: "direct" | "anti" | "column" | "category"
```

### 5. 运行测试

```bash
pytest migration/test_pose_category_layout.py -v
```

测试用 mock 对象模拟 `PoseLabelItem` 和常量，不依赖 host 项目结构，可在任何环境独立验证 `layout_category()` 的行为正确性。

## 依赖契约

主模块仅依赖：

| 依赖 | 来源 |
|------|------|
| `PyQt6.QtCore`（QRect / QPointF / QPoint / QRectF） | 第三方 |
| `typing` / `__future__` | 标准库 |
| `PoseLabelItem`（调用方传入，鸭子类型） | host 项目 |
| `COCO_KEYPOINT_INDEX: Dict[str, int]`（参数传入） | host 项目常量 |
| `BODY_PARTS: Dict[str, List[str]]`（参数传入） | host 项目常量 |

### PoseLabelItem 鸭子类型契约

迁移模块通过 duck typing 访问 item，只要对象拥有以下属性即可：

| 属性 | 类型 | 用途 |
|------|------|------|
| `shape_ref` | 带 `.label: str` 的对象 | 恢复原始标签前缀 |
| `label` | str | 回退显示文本 |
| `keypoint_index` | int | COCO 0..16 |
| `anchor` | QPointF | 关键点位置 |
| `rect` | QRect（可变） | 标签矩形，原地修改 |
| `leader_start` / `leader_end` | QPointF / QPoint | 引线起止 |

## 已知限制

- `mid` 参数当前未参与 category 的位置计算（仅保留以匹配 dispatcher 签名）。如需用中线做额外约束，可在 head row 的 `tcx` 处替换为 `mid[0]`。
- 当 `bbox=None` 且 anchor 退化（所有点重合）时，`_compute_bbox` 可能返回过小矩形，导致标签堆叠异常。生产环境建议始终传入真实 person bbox。
