# CUSTOM-117：Ctrl + 左键拖拽框选

- 状态：已实现并通过用户验收，已独立提交并同步 GitHub；2026-11-06 用户实测确认“实际测试没有问题了”。该确认仅覆盖本次框选功能。
- 功能分类：新增本地能力（画布多选交互）。
- 实现基线：`1ef860fa6dfc3056a386ee0cc410ece3d773144e`；交付整理起点：`b27f122a`，承接已同步的单点拟合修复。框选源码、测试及配套资料独立归集，精确提交号见 Git 交付补记。
- 修改：`anylabeling/views/labeling/widgets/canvas.py`；调整 `tests/test_canvas/test_drag_refresh.py`，新增两份框选专项测试。
- 数据影响：不新增标注 JSON 字段或持久配置。

- 编辑模式下按住 Ctrl，使用鼠标左键拖出选区；松开左键后，将与选区重叠的可见标注追加到当前选择，部分覆盖即可选中。
- 可从空白处、已有标注内部、顶点或边缘开始拖拽，支持任意拖拽方向以及缩放、平移后的画布。
- 选区使用蓝色虚线和半透明填充。Ctrl + 单击仍按原有逻辑逐个选择，普通左键拖拽仍移动已选标注。
- Esc、窗口失焦、模式切换、加载标注或重置画布会取消框选。框选不会修改标注几何、创建撤销记录或触发自动保存。
- 隐藏标注不加入框选；锁定标注可以被选择，原有锁定限制继续生效。

## 验证

2026-11-06，Python 3.12.12 / PyQt6，离屏测试：

- 新增 26 项画布交互测试和 4 项真实主窗口集成测试，全部通过；集成测试覆盖标注列表同步、批量操作启用、批量删除及连续六次框选。
- 相关回归：225 项通过、6 个子测试通过、1 项排除。范围包含选择、拖动、锁定、矩形边缘调整、旋转、多面体、顶点擦除、Shift 贴合和画笔编辑。
- 排除的 `test_main_window_exposes_translated_edge_toggle` 在窗口初始化期间被配置保存错误弹窗阻塞。
- 扩大画布回归未全通过：字体缩放测试 `test_shape_label_keeps_fixed_screen_size_while_zooming` 在未修改的 Git HEAD Canvas 上也复现 `179 != 139`；部分旧导航测试同样被窗口初始化的配置错误弹窗阻塞。
- 调整已有多选移动测试，改用普通左键拖动，以匹配 Ctrl + 拖动的新框选手势。

## 部分覆盖与连续操作修复

- 用户反馈蓝色选区可正常拖出，部分覆盖时只选中一个或一个也未选中。原先的完全包含规则改为标注几何与选区相交；点标注按点是否在选区内判断。
- 补充复现了两个事件边界问题：释放前的无按键移动事件会清空尚未提交的选区；连续按下被 Qt 判定为双击时不会启动框选。现在捕获状态保留到明确释放或取消，Ctrl + 左键双击事件也走框选按下入口。
- 连续六次主窗口测试包含首次全包、后续部分覆盖、正反方向、双击按下和释放前的无按键移动事件；分别使用直接事件和 QtTest 鼠标按下/释放运行，全部通过。
- 当前用户窗口可读取控件树，但截图接口返回 `FrameArrived timed out` 和 `window capture timed out`，未将此计为在用户窗口完成的鼠标实操验证。

## 交付验证与资料整理（2026-11-06）

用户明确要求将剩余改动整理、提交并形成 GitHub 备份。本次没有新增框选交互规则，保留已验收实现，统一更新功能索引、项目总览及保存状态。

```powershell
& C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe -m pytest tests/test_canvas/test_marquee_selection.py tests/test_labeling/test_marquee_selection_integration.py tests/test_canvas/test_drag_refresh.py -q --color=no -p no:cacheprovider --tb=short --basetemp=.tmp/marquee-delivery-20261106 --junitxml=.tmp/marquee-delivery-20261106.xml
```

结果：**41 passed in 15.43s**。包含 26 项框选交互、4 项真实主窗口集成、11 项拖动刷新回归；使用隔离配置、QSettings、合成图片和离屏窗口，没有操作用户当前真实标注。持久化证据：[JUnit](../../reports/marquee_delivery_20261106/tests.xml)。上述 41 项与历史 225 项存在重叠，不相加作为独立测试总数。

资料同步范围：本功能记录、定制功能索引、项目改动总览、相对上游的源码清单。之前单点拟合交付记录保留当时的提交边界，并补上后续框选交付入口。

迁移时按 `Canvas` 的 `_marquee_*` 状态、框选辅助方法和鼠标/键盘/加载/绘制入口定位；回退本功能提交时保留已有单点拟合修复。正式标注格式和配置格式不变，不生成安装包，也不据此宣称全项目回归通过。

## Git 交付补记

- 功能与资料提交：[c58e16b6](https://github.com/ljh725/X-AnyLabeling/commit/c58e16b6)，`feat(canvas): save accepted Ctrl-drag marquee selection`，共 10 个文件。
- 此提交包含原先剩余的 8 个文件、41 项交付测试的 JUnit 证据，以及单点拟合记录中指向本次后续交付的说明更新。
- 已原子快进推送至个人仓库 `origin/codex/4.2.1-baseline-organization` 和 `origin/versions/4.2.1`，两者从 `b27f122a` 更新为 `c58e16b6`。
- 本段为实现推送后的交付补记，随后文档提交同样同步上述两个分支；最终分支头包含该补记，实现提交号始终为 `c58e16b6`。
