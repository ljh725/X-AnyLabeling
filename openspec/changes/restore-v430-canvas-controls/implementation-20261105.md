# 画布控件恢复：任务实施记录（2026-11-05）

本轮承接 [tasks.md](tasks.md)，用户已明确授权实施代码。仅在现有实现上修复缺陷并补齐验证，未整体恢复旧文件、未回退主工作区、未归档或重复发布规格。

## 本轮产品代码

| 文件 | 改动与原因 | 验证 |
| --- | --- | --- |
| `widgets/toolbar.py` | 横向分量不再二次取反；保留纵向转横向策略及事件消费。 | viewport 派发正负 angle/pixel、边界、不穿透画布。 |
| `label_widget.py` | 成组/解组复用 `_apply_field_patch`，记录一次撤销并刷新现有 UI；去除重载文件，避免关闭自动保存时丢失未保存标注。维持整组最小组号合并/整组解组语义；任一涉及成员锁定时不做部分修改；清理旧组悬停/选择标记。 | 手动保存模式下成组、撤销/重做、保存重开、解组撤销、跨组未选成员/无关组、锁定组成员。 |
| `settings/dialog.py` | 将字段定位的无上下文 singleShot lambda 改为归属设置窗口的单次 QTimer，关闭窗口停止定位；避免窗口销毁后延迟回调访问已删除 QScrollArea。 | 快速定位字段后关闭/销毁窗口的正式反例，设置应用/失败/重试/取消及重新打开。 |

前一轮 R1/R2 的修复沿用，未再次改写视图折算或配置 writer。本轮无新增用户文案、依赖或标注字段。

新增 `tests/test_labeling/test_canvas_controls_integration.py`，扩充原工具栏及填充专项。覆盖真实鼠标事件的拖边/单点拟合提交与取消、最新模式覆盖、切图/关闭、锁定/多选与外侧滚轮调边、保存后身份、1×1/8192×256/256×4096 图像、适应宽度/窗口、导航器、右键/空格平移、八类显示状态、16 位灰度切图与原图哈希。两个独立应用进程验证关闭后重新启动，保留模式/亮度保持/数字映射/通用快捷键，同时透明度值及保持开关回到会话默认。

## 三方职责与来源（2.3）

逐字节来源指纹和 AST 方法清单保存在 `.local/canvas-implementation-20261105/three-way-symbols.json`；恢复对象仍以原 `receipt.json` 及 blob SHA-256 为准。方法存在只是定位证据，行为以本轮测试为准。

| 职责 | 迁移前 `57679338` | 已核验恢复对象 | 当前保留位置与验证 |
| --- | --- | --- | --- |
| 填充透明度 | `Shape.paint` 无填充乘数，画布全局透明度。 | 恢复 canvas 传入乘数；配套 shape/面板按规格重建。 | `Shape.paint(fill_opacity)`、画布普通/笔刷掩码与创建路径；12 项像素及混合标记验证。 |
| 滚轮、视图与共享中心 | 旧 Ctrl 工具手势，无两模式配置。 | canvas blob 含两模式/手势；label_widget blob 含视图折算。 | `apply_wheel_navigation_mode`、`_apply_shared_view`、`constrain_canvas_pan`；保留按尺寸共享、导航器和既有矩形算法，补交互结束/关闭矩阵。 |
| 图片审核 | 既有 checked、保存、metadata generation/revision。 | 面板三态为复用入口；配套控件重建。 | `set_annotation_checked`/`_sync_annotation_checked_state`、后台 revision 隔离；审核/切图回归，本轮不另建审核状态。 |
| Dense Review 历史与重做 | 当时的历史实现仅作比较，不用旧实现覆盖后续成果。 | 恢复候选不代表当前统一历史的全部能力。 | 当前 `undo_shape_edit`/`redo_shape_edit`、Canvas 快照、`dense_review/session.py` 与 workspace 的事务衔接；本轮 workspace/session/persistence/export/thumbnails 回归。 |
| 异步缩略图与节流 | 保留当时基线供对照。 | 不以旧候选替换当前后台解码/代际策略。 | `dense_review/thumbnails.py` 的 generation、workspace 节流与指针操作隔离；相关子集通过。 |
| Inspector 交接 | 旧入口及报告仅作定位。 | 不整份覆盖 label_widget 或 Inspector。 | 当前 `inspector/controller.py`、`inspection/handoff.py`；本轮 handoff/dialog 选定回归通过。 |
| 锁定、身份、矩形编辑 | 保留旧几何和稳定身份契约。 | 旧 blob 是功能来源，不替换后续 point_fit/preview 改动。 | 原拖边/拟合/预览代码及持久 ID 不变；新增成组字段事务保留身份与锁定，并使用已有撤销链。 |
| 配置与翻译加载 | 不含本轮独立持久化修复。 | 不把恢复对象当作配置保存的最终实现。 | `user_config.py` 及 controller/writer 属配置修复；`app.py::load_translator` 与嵌入资源属既有恢复衔接。本轮只修设置窗口定位生命周期，未另造存储。 |

本轮三个产品文件与实施开始快照的差异可单独复核；其他已经存在的 Inspector、Dense Review、配置、翻译和预览修改均不算本轮新增成果。

## 恢复前证据审计（2.1）

本轮校验备份补丁 SHA-256 与原回执一致：`4ca5efae8ad2fc8a062427866f95462c9208e3834b5094947f5b1be38f200d8e`。在独立目录将 `67c98a80` 加该补丁并复制备份未跟踪文件，可重建工作区，但其中 canvas 指纹为 `dcf259eb…`，已包含填充透明度/两模式。旧 verify-clone 也包含这些能力；两条当前专项在这两种副本上通过，不能把它们当成“恢复前功能缺失”的失败证据。

另从 `67c98a80` 单独导出未套补丁的已提交源码，实际导入路径与 canvas SHA-256 已记录在 `.local/canvas-implementation-20261105/committed-baseline-probes.json`。执行当前两条专项函数，负例为：

- `test_shape_fill_alpha_is_scaled_without_touching_outlines`：`Shape.paint` 无新增参数，TypeError。
- `test_traditional_bare_wheel_scrolls_without_zooming`：Canvas 不支持 `wheel_navigation_mode`，TypeError。

这证明已提交基线缺少能力，不证明恢复当时完整混合工作区的失败集合；原先未执行的历史回归不能补造。任务 2.1 以“完成证据审计、可执行负例并明确不可可靠重建的历史缺口”关闭，不宣称历史测试已补齐。

## 实际执行与结果

所有测试使用既有 Conda `x-anylabeling-cu12` / Python 3.12 / PyQt6。离屏测试隔离配置、QSettings、图片及输出；本地 `pytest_tmp_mode` 只处理临时目录权限。旧显式 config 窗口回归额外使用 `pytest_canvas_session` 安装真实隔离会话，未使用跳过产品保存的旧 `pytest_restore_env` 插件。

- 混合渲染专项：12 passed。
- 首次集成暴露成组数据丢失及两处测试准备问题；修正后原 19 项集成通过。
- 导航边界/滚轮组合：9 passed；最新模式/平移/真实进程重启子集：6 passed。
- 设置延迟回调修复后单独复验配置控制器/双窗口持久化：**17 passed，10.70s**。
- 受影响 17 模块：**403 passed / 1 failed，194.77s**。失败仍为已记录的 `test_shape_label_keeps_fixed_screen_size_while_zooming`（179 != 139，字体环境）；未将其隐藏或写成全通过。本轮未改字体绘制实现。
- 组合专项又复现设置字段定位回调访问已销毁对象，已修复并加入正式反例；**最终八模块专项 127 passed，250.20s**，有完整 JUnit，未使用抑制异常的测试插件。

最终专项命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONPATH='D:\X-AnyLabeling-4.2.1\.local\restore-v430-20261104'
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' -m pytest tests/test_canvas/test_fill_opacity.py tests/test_canvas/test_wheel_navigation.py tests/test_config/test_wheel_navigation_config.py tests/test_labeling/test_canvas_display_retention.py tests/test_labeling/test_review_status_panel.py tests/test_labeling/test_toolbar_display_actions.py tests/test_settings/test_wheel_gesture_strings.py tests/test_labeling/test_canvas_controls_integration.py -q -p no:cacheprovider -p pytest_tmp_mode --basetemp .tmp/canvas-apply-final2-20261105 --junitxml=.tmp/canvas-apply-final2-20261105.xml
```

本机 JUnit：`.tmp/canvas-apply-regressions-20261105.xml`、`.tmp/canvas-apply-final2-20261105.xml`。单轮 Qt 回调退出不能当成完整通过，旧 `.tmp/canvas-apply-final-20261105` 没有最终 XML，不作为通过证据。

## 性能实测（8.3 保留未完成）

使用同一 `.local/canvas-implementation-20261105/benchmark_controls.py`、同一 Python/Qt 和固定 30/300 矩形样本，对备份重建副本与当前源码分别测量。每个规模 20 次拖动预热后统计 100 次完整 press/move/release+事件循环，切图预热两次后统计 20 次；均为 offscreen、关闭自动保存、未进入密集工作区。原始结果为同目录 `performance-before.json`、`performance-after.json`。

| 对象数 | 拖框 p95 对照 → 当前 | 切图 p95 对照 → 当前 |
| --- | --- | --- |
| 30 | 15.75 → 15.61 ms（约 -0.9%） | 39.32 → 39.01 ms（约 -0.8%） |
| 300 | 132.52 → 134.33 ms（约 +1.4%） | 239.96 → 253.32 ms（约 +5.6%） |

对照副本已含部分恢复能力，不是完整功能缺失基线，且副本到当前还含其他既有变更；不能把该差异归因于本轮三个局部修复。当前没有向鼠标事件添加文件遍历或同步绘制，但未取得“恢复前后无性能回退”的充分证据；300 对象切图 p95 恶化单列，8.3 不勾选，后续需匹配基线、控制后台负载并复验。

## 原生界面实测（8.4 部分完成）

在 `QApplication.platformName()==windows` 的原生窗口上，使用中文、自制图片和隔离配置，检查 940×720 窄窗口的明/暗主题；分别以 `QT_SCALE_FACTOR=1`/`1.5` 实测窗口 DPR 1.0/1.5。面板均完全位于 viewport 内，收起高度 28，展开 137–143；按钮不抢焦点，工具栏横向范围 508，末端可滚达。四张窗口屏幕截图已目视复核，面板文字、按钮和布局可读。

证据：`.tmp/canvas-native-20261105/{light,dark}-scale-1.png`、`.tmp/canvas-native-150-20261105/{light,dark}-scale-1.5.png` 及各自 results.json。未改变用户 Windows 显示缩放设置；此处 1.5× 是应用级 DPI 模拟，不能冒充不同实际系统缩放或多屏 DPI 切换已验收，8.4 继续保留未完成。

## 保存、恢复与回退

实施开始状态、原始差异及目标文件原字节保存在 `.local/canvas-implementation-20261105/{before.json,before/,working-tree-before.patch,status-before.txt}`。三个产品文件按功能差异回退，禁止整份回滚 label_widget/settings 文件而覆盖其他成果。

独立交付仓库为 `.local/canvas-implementation-20261105/delivery`：父提交 `484977f` 单独保留实施开始时的既有工作区源码/文档，明确不算本轮成果；修复提交 `a2e4282ce5881151ce4d8020e349deabbdd3ffab` 仅包含本轮 10 个文件，三个产品文件合计为局部修改。另一个无硬链接克隆 `verify-delivery` 的 10 个交付文件 SHA-256 与主工作区一致；在该克隆运行填充、两模式、保持、审核、工具栏、成组、设置关闭和实际交互等 **23 项通过（29.72s）**。最终收尾文档提交不改变产品/测试源码，哈希、bundle 及版本号统一记录在 `delivery-receipt.json`。主项目 HEAD 仍为 `67c98a80`，没有将用户原有混合修改提交到主分支。图片/标注不做逆向转换；成组修复只沿用原 group_id/身份和保存格式。性能与实际系统缩放验收仍是保留项。

## 收尾检查

- 最终专项 127 passed，配置修复后回归 17 passed，独立还原关键验证 23 passed；受影响回归 403 passed / 1 项既有字体失败。
- Black 检查本轮工具栏及三个测试文件通过，新成组方法单独检查格式，避免重排既有大文件；三个产品文件语法检查通过。
- OpenSpec strict、任务编号/链接/空白检查及本轮差异检查通过。
- 当前任务 29/31 完成，8.3 与 8.4 保留限制；未归档任何变更，未修改真实用户配置、标注或 Windows 系统缩放。
