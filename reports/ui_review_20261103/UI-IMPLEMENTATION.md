# Inspector / Dense Review UI 改造实施记录（P0）

- 日期：2026-11-03
- 范围：CUSTOM-109 Inspector、CUSTOM-110 Dense Review 的第一轮界面重构（P0）
- 依据：[UI-IMPROVEMENT-PLAN.md](UI-IMPROVEMENT-PLAN.md) §2、§3、§6.7
- 截图：本目录 `01`–`05`（浅色，改造后）、`07`–`08`（深色）

## 结果

| 指标 | 改造前 | 改造后 |
| --- | --- | --- |
| Inspector 队列可视高度 | 130px | **480px**（splitter 160 → 632） |
| Inspector 详情区高度 | 70px | **445px** |
| Inspector 表格 | 6 列固定 830px，横向滚动 | **5 列**，表头 638 / viewport 640，**无横向滚动** |
| Inspector 行高 | 30px | 34px |
| Inspector 主按钮 | 无 | 1 个 `#0071E3` 主按钮（实测 949 像素纯色填充） |
| Dense 批次行高 | 16px（文字被裁） | **70px** 卡片（名称/数量/进度/两维计数） |
| Dense 卡片 | 216px 固定网格，无边框 | **5 列自适应**（984px 宽 → 194px/列），色条 + 底板 + 角标 |
| 按钮高度 | 24px | 38px（沿用 `get_dialog_style()` 的 36 + 边框） |

## 变更文件

| 文件 | 改动 |
| --- | --- |
| `utils/style.py` | 新增 `get_workbench_qss()`（作用域按钮变体、表格、标签页、进度条）与 `blend_hex()`；`style.py +136` 行，未改既有规则 |
| `inspector/dialog.py` | 重写 `_build_ui`：两行工具条 + 左右分栏 + 右栏「详情 / 外部候选」标签 + 5 列表格 + 底部徽标状态行；表格空状态与详情占位；运行后自动选中首条；`setAutoDefault(False)` |
| `dense_review/workspace.py` | 重写 `_build_ui` / `_build_object_tab`：进度条工具条 + 状态行 + 批次卡片 + 卡片流 + 单行操作条；新增 `_BatchDelegate`、`_CardDelegate`、`_RegionDelegate`；网格列数随宽度自适应 |

未改动任何服务层逻辑、数据结构、保存格式或快捷键绑定。

## 关键实现

### 样式层

两个窗口统一：

```python
self.setObjectName("annotationInspector")  # / "denseReviewWorkspace"
self.setStyleSheet(get_dialog_style() + get_workbench_qss())
```

- 浅色模式下 `get_app_stylesheet()` 返回空串，所以必须显式接 `get_dialog_style()`；否则又是 Fusion 默认外观。
- 按钮强调用动态属性 `variant`（primary / quiet / danger），QSS 只作用于这两个窗口，不污染设置、点云等既有界面。
- 表格选中底色用 `blend_hex()` 按主题计算（浅色 `#DBEBFB`、深色 `#192B3E`），不再写死。
- 表格单独设置 `QPalette.HighlightedText`，否则深色模式下选中行文字会沿用错误的调色板颜色。

### Inspector

- 工具条一行：方案 / 阶段 / 范围 / 运行历史（`11-03 06:05 · 4 问题`）/ 加载 / 更多 / 取消 / 开始检查。原「继续、复制、导入、导出、导入旧问题、导出报告」收进「更多」菜单，入口没有丢。
- 表格 5 列：风险（仅该列着色）、规则、文件 · 对象（stretch）、机器状态、人工判断；长内容省略 + 逐列 tooltip。
- 队列用 `QStackedWidget` 切换表格与空状态；详情区未选中时显示占位说明。
- 五轴状态压缩为一行徽标：`执行 1/1 · 问题 0/4 · 对象 可用 · 空间 可用 · 正式 未改变`，完整句子进 tooltip，「说明」按钮展开详细信息与规则摘要。
- 运行结束后自动选中第一条问题，详情不用再手动点。

### Dense Review

- 顶部一行：进度条（已确认/总数）+ 摘要 + 开始/重建 + 复核配置 + 刷新 + 关闭；第二行只留完成状态与批次/类别统计。
- 批次列表改卡片行：名称、数量、进度条、`类别 0/13 · 框 0/13`，选中用主色描边。
- 卡片流用 `QStyledItemDelegate` 绘制：顶部 3px 状态色条（待审灰 / 疑难橙 / 暂跳蓝 / 已完成绿）、浅底缩略图、标题与状态、确认标记。列数按 viewport 宽度重算（`resizeEvent` + viewport 事件过滤器），最小 178px。
- 操作条单行：画布显示模式、看全图、更多（解除疑难/取消暂跳/加入批次/查看成员/重建队列/并排比较）、暂跳、疑难、完成并下一个、完成本批（主按钮）。
- 空间查漏页补 `_RegionDelegate`：状态圆点 + 区域 ID + 状态文字，选中浅底；「完成区域并下一区」改主按钮。

## 验证

| 检查 | 结果 |
| --- | --- |
| `tests/test_inspection` | **80 passed** |
| `tests/test_dense_review` | **78 passed** |
| 两模块合计 | **158 passed** |
| `tests/test_canvas` | **578 passed, 1 failed**，失败项 `test_groups::test_shape_label_keeps_fixed_screen_size_while_zooming` 为改造前既有失败（已核对基线记录） |
| flake8（三个改动文件） | 通过 |
| black `--check` | 通过 |
| 深色模式 | `07` / `08` 截图，无亮白块；选中行文字对比正常 |

## 未完成

- 空间查漏页的网格示意图（当前仍是列表）。
- 表格排序 / 搜索 / 大数据模型（上千条问题仍需整表重建）。
- 卡片上下文百分比、显示模式在关闭后恢复（沿用原逻辑）。
- 图标化主操作（仓库有 `new_icon_path`，本轮未接）。
- 真实数据集与真实屏幕的人工验收。

## 回退

- 代码：还原上述三个文件的本次改动即可；样式层是纯新增函数，删除 `get_workbench_qss()` 与两处 `setStyleSheet` 调用即回到 Fusion 默认外观。
- 数据：无变化，不涉及 `.xanylabeling/` 或标注 JSON。
