## Purpose

提供一个与主标注窗口共享权威文档的第二矩形编辑窗口，使主窗口持续保留全局上下文，而巡检窗口以低干扰轮次完成类别纠错和矩形修整。

## ADDED Requirements

### Requirement: Main and review windows have distinct visible roles
主窗口 SHALL 始终显示当前图片的全部对象并保留全局编辑能力。第二窗口 SHALL 采用单轮次大画布，仅显示当前轮次普通矩形；其他轮次对象和非矩形对象 SHALL 完全隐藏且不可悬停、选择、框选或编辑。

#### Scenario: Current round visibility
- **WHEN** 第二窗口处于某个包含 10 个矩形的轮次
- **THEN** 第二窗口 SHALL 仅绘制和允许交互这 10 个矩形，而主窗口 SHALL 继续显示当前图片全部对象

#### Scenario: Labels use color-first presentation
- **WHEN** 矩形既未悬停也未选中
- **THEN** 两个窗口 SHALL 保留其配置类别颜色但不强制显示标签文字；悬停或选中时 SHALL 显示标签名称

#### Scenario: Review display follows the main window without masks
- **WHEN** 主窗口修改标签、文字、分数、属性、关系、矩形尺寸文字或颜色外观等显示方式
- **THEN** 第二窗口 SHALL 立即采用相同显示方式和颜色信息，但其 `show_masks` SHALL 始终保持关闭且不绘制任何掩码

### Requirement: Review window is a focused rectangle editor
第二窗口 SHALL 只提供大画布和精简巡检栏，不得复制主窗口的标签信息面板、左侧工具栏、主工具栏或其他 Dock。它 SHALL 支持矩形单选/多选、新建、复制、删除、改类别、移动、缩放、撤销和重做，并 SHALL 复用主窗口的标签对话框、标签定义、颜色和最近使用标签。

#### Scenario: Edit a label in the review window
- **WHEN** 用户在第二窗口对矩形执行修改类别
- **THEN** 系统 SHALL 使用主窗口同一标签选择定义提交修改，并立即在两个窗口更新类别颜色和文字

#### Scenario: Relabel selected rectangles with a digit shortcut
- **WHEN** 第二窗口具有一个或多个选中矩形且用户按下已在数字快捷重命名管理器中配置的 `0`-`9`
- **THEN** 系统 SHALL 复用该数字的现有重命名映射修改全部所选矩形，并将该操作写入双窗口共享撤销/重做历史

#### Scenario: Digit shortcut is guarded while editing controls
- **WHEN** 焦点位于轮次或每轮上限输入控件，或者第二窗口没有选中矩形
- **THEN** 数字快捷键 SHALL 不修改任何标签名称

### Requirement: Both windows share one authoritative annotation document
两个窗口 SHALL 始终显示同一张图片，并 SHALL 将所有编辑提交到同一权威标注文档。主窗口 SHALL 是唯一文件保存责任方，第二窗口不得独立写标注文件。两个窗口 SHALL 共享一个按时间排序的撤销/重做历史。

#### Scenario: Edit geometry in the review window
- **WHEN** 用户在第二窗口拖动或缩放矩形
- **THEN** 主窗口 SHALL 在操作期间实时显示几何变化，完成后的单次编辑 SHALL 进入共享撤销历史并由主窗口负责保存

#### Scenario: Undo from either window
- **WHEN** 用户在任一窗口执行撤销
- **THEN** 系统 SHALL 撤销全局最近一次编辑并在两个窗口同步结果

### Requirement: Object edits are temporarily locked by owner window
系统 SHALL 在拖动、缩放、改类别、删除或属性编辑期间按对象身份授予发起窗口临时编辑锁。另一窗口 SHALL 继续显示变化但不得同时修改已锁对象；其他未锁对象 SHALL 保持可编辑。操作完成、取消、对话框关闭或窗口异常关闭时 SHALL 释放锁。

#### Scenario: Competing edit is rejected
- **WHEN** 第二窗口正在拖动某个矩形且主窗口尝试编辑同一矩形
- **THEN** 主窗口 SHALL 拒绝该编辑但继续实时重绘该矩形，并在第二窗口操作结束后恢复可编辑状态

### Requirement: Selection synchronization is asymmetric and explicit
第二窗口选择 SHALL 立即替换并高亮主窗口选择。主窗口选择 SHALL 先成为待同步选择，不得自动改变第二窗口轮次；仅在用户执行确认动作后，第二窗口 SHALL 跳转到所选对象所属轮次并同步选择。第二窗口的新选择 SHALL 清除尚未确认的主窗口待同步状态。

#### Scenario: Select in the review window
- **WHEN** 用户在第二窗口选中一个或多个当前轮次矩形
- **THEN** 主窗口 SHALL 立即高亮同一对象集合

#### Scenario: Select in the main window without confirmation
- **WHEN** 用户在主窗口选择属于其他轮次的矩形但未执行同步确认
- **THEN** 第二窗口 SHALL 保持当前轮次和选择，主窗口 SHALL 显示明确的待同步状态

#### Scenario: Confirm a main-window selection
- **WHEN** 用户执行 `Ctrl+J` 且主窗口所选矩形均属于同一轮次
- **THEN** 第二窗口 SHALL 跳转到该轮次并同步该选择，待同步提示 SHALL 消失

#### Scenario: Reject cross-round multi-selection
- **WHEN** 用户执行 `Ctrl+J` 且主窗口所选矩形分属多个轮次
- **THEN** 系统 SHALL 保持第二窗口不变并明确提示所选对象跨越多个轮次

### Requirement: Viewports remain independent
两个窗口 SHALL 只同步对象状态，不得同步缩放、平移或视口位置。第二窗口切换轮次 SHALL 保持其当前视口；切换图片 SHALL 自动适应窗口。主窗口 SHALL 继续遵循既有视口行为。

#### Scenario: Switch review round while zoomed
- **WHEN** 第二窗口处于自定义缩放和平移状态并切换轮次
- **THEN** 第二窗口 SHALL 保持该视口不变，主窗口视口 SHALL 不受影响

#### Scenario: Load another image
- **WHEN** 主窗口加载不同图片
- **THEN** 第二窗口 SHALL 加载同一图片、建立第 1 轮并自动适应窗口

### Requirement: Review visibility overrides are isolated and reversible
巡检开启时系统 SHALL 临时暂停类别筛选、单对象隐藏和其他会隐藏部分对象的隔离/复核模式，并 SHALL 阻止巡检期间启用冲突模式。退出巡检时 SHALL 恢复进入前的状态，且不得把巡检可见性写入标注数据。

#### Scenario: Enter with active filters
- **WHEN** 用户在类别筛选和单对象隐藏均存在时开启巡检
- **THEN** 主窗口 SHALL 临时显示全部对象、第二窗口 SHALL 对全部矩形分轮，退出后 SHALL 恢复原筛选与隐藏状态

### Requirement: Users can temporarily inspect all rounds without enabling interaction
第二窗口 SHALL 支持按住 `V` 临时显示全部矩形。临时出现的非当前轮次矩形 SHALL 保持不可交互；松开按键 SHALL 恢复当前轮次，且不得改变轮次、选择、冻结分区或撤销历史。

#### Scenario: Hold and release all-preview key
- **WHEN** 用户在第二窗口按住并随后松开 `V`
- **THEN** 系统 SHALL 只在按住期间绘制全部矩形，且任何非当前轮次矩形均不得被选择或编辑

### Requirement: Navigation and synchronization actions are discoverable and guarded
系统 SHALL 提供精简栏按钮和可配置快捷键：`F10` 切换巡检窗口、`[`/`]` 切换轮次、`Ctrl+J` 确认主窗口选择、按住 `V` 临时全量预览。输入框编辑、标签对话框打开或矩形正在拖动时 SHALL 暂停冲突的导航快捷键。

#### Scenario: Shortcut blocked during drag
- **WHEN** 任一窗口正在拖动矩形且用户触发轮次切换快捷键
- **THEN** 系统 SHALL 保持当前图片和轮次，直到编辑完成或取消

### Requirement: Window lifecycle persists layout but not active review state
系统 SHALL 记住第二窗口的显示器、位置和尺寸，但应用启动时 SHALL 默认关闭巡检模式。手动打开时 SHALL 尝试恢复保存布局；目标显示器不可用时 SHALL 回退到主窗口所在屏幕。系统 SHALL 仅记录并展示上次关闭巡检时的图片名称，不得自动定位图片、恢复轮次或维护完成状态。

#### Scenario: Reopen review window in a later session
- **WHEN** 用户重新启动应用并手动按 `F10`
- **THEN** 第二窗口 SHALL 恢复可用的保存布局但保持新巡检会话，且 SHALL 仅把上次关闭图片名称作为信息显示

#### Scenario: Close review window
- **WHEN** 用户按 `F10` 或关闭第二窗口
- **THEN** 系统 SHALL 记录当前图片名称、退出巡检、恢复暂停的可见性状态，并保留已提交编辑
