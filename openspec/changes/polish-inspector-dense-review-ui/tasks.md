## 1. 基线与变更登记

- [x] 1.1 确认工作区干净、基线提交与 `backup/pre-p2-20261103` 标签存在。
- [x] 1.2 新建 OpenSpec 变更与 CUSTOM-109/110 的 P2 修订行，记录范围与不做项。

## 2. 空间查漏网格

- [x] 2.1 新增自绘网格控件：按 `CoveragePlan` 等比映射，四态着色，当前区域描边，无计划空状态。
- [x] 2.2 点击网格等同列表选中：复用 `set_current_region` 与 host 定位，不与列表互相递归。
- [x] 2.3 查漏页布局改为「网格 + 区域列表」并排；列表保留键盘操作。
- [x] 2.4 补测试：状态着色映射、点击定位、无计划空状态、选中同步、深色主题取色。

## 3. Inspector 详情分节

- [x] 3.1 重写 `_show_selected_details()`：概要 / 规则命中 / 位置 / 建议 / 状态 / 备注六节。
- [x] 3.2 删除硬编码颜色，全部取 `get_theme()`；证据指标改两列表格。
- [x] 3.3 验证空证据、无建议、长路径与多对象的显示；深色截图核对。

## 4. 快捷键与提示

- [x] 4.1 Dense 五个快捷键改 `WindowShortcut`，窗口失焦不触发。
- [x] 4.2 Inspector 增加 `F5` / `Enter`（表格内），不注册 `Esc`；`Ctrl+F` 因无搜索框且属 P1，本轮不接线。
- [x] 4.3 两窗口提示文案改为真实绑定（`Ctrl+Return` / `Alt+Return`），Dense 按配置动态生成。
- [x] 4.4 补测试：作用域、门控、快捷键触发与不误触。

## 5. 本地化与图标

- [x] 5.1 Inspector 可见中文串包 `self.tr()`；不包配置键、枚举值与数据键。
- [x] 5.2 `pylupdate6` 重生成四语言 `.ts`，`lrelease` 编译 `.qm`，`rcc` 重生成 `resources.py`；en_US/zh_CN 补全，ja_JP/ko_KR 各余 413 条待译。
- [x] 5.3 主操作接入 `new_icon_path()` + `themed_icon()` 图标，深色/浅色截图核对。
- [x] 5.4 `en_US` 下重渲染两窗口，确认工作台无中文残留（qtbase 标准按钮除外，已记录为范围外）。

## 6. 回归与验收

- [x] 6.1 `tests/test_inspection`、`tests/test_dense_review` 回归通过（170 passed）；`tests/test_canvas` 578 passed、1 项既有失败。
- [x] 6.2 同参数重出浅色/深色截图（`01`/`03`/`05`/`06`/`08`），供与 P0 对比。
- [x] 6.3 写 `verification.md`、更新实施记录与 CUSTOM 状态；`openspec validate --strict` 通过。
