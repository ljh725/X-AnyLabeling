## Purpose

规范 Inspector（CUSTOM-109）与 Dense Review（CUSTOM-110）两个工作台在 P2 阶段
的呈现与交互细节：空间查漏网格、详情分节、快捷键作用域、界面文案本地化与主操作
图标。约束是只改呈现层，不改变检查/复核的判定、状态机与保存格式。

## ADDED Requirements

### Requirement: 空间查漏网格示意

工作台 SHALL 在空间查漏页显示按 `CoveragePlan` 等比映射的区域网格，使完成、
疑难、暂跳、待查四种状态可仅凭颜色区分；当前区域 SHALL 有独立描边。无区域计划
时 SHALL 显示空状态说明，而不是空白网格。

#### Scenario: 有计划时按状态着色

- **WHEN** 用户切到「空间查漏」页且当前图片已有区域计划
- **THEN** 网格按行/列与图像宽高比绘制，已完成绿色、疑难橙色、暂跳蓝色、待查浅底
- **AND** 与区域列表的选中项保持一致

#### Scenario: 点击网格定位区域

- **WHEN** 用户点击网格中的任一区域
- **THEN** 该区域成为当前区域，画布定位到对应范围
- **AND** 列表选中项同步变化，且不产生重复的状态写入

#### Scenario: 尚无区域计划

- **WHEN** 用户首次进入查漏页且尚未建立区域计划
- **THEN** 网格区域显示「尚无区域计划」说明，并提示可重建计划

### Requirement: Inspector 详情分节

Inspector 详情 SHALL 按「概要、规则命中、位置、建议、状态、备注」分节呈现，
节标题与正文颜色 SHALL 取自当前主题；证据指标 SHALL 以指标名/值成对显示，
不得以单段 HTML 文本墙输出。

#### Scenario: 选中一条带证据的问题

- **WHEN** 用户在问题表中选中一条包含两条规则证据的问题
- **THEN** 详情显示六个分节，规则命中节列出每条规则名、说明与指标键值
- **AND** 深色主题下正文与节标题仍满足对比度要求

#### Scenario: 空证据或无建议

- **WHEN** 问题没有证据项或没有建议动作
- **THEN** 对应节保留并显示「无」类占位说明，而不是整节消失

### Requirement: 快捷键作用域与提示

Dense Review 的快捷键 SHALL 仅在窗口激活时生效；Inspector SHALL 提供开始检查、
定位选中行与聚焦搜索的键盘入口。两窗口的界面提示 SHALL 与真实绑定一致。

#### Scenario: 焦点在画布时不误触

- **WHEN** Dense Review 窗口未激活而画布拥有焦点
- **THEN** `Alt+Return`、`Alt+N`、`Alt+X` 不触发工作台动作

#### Scenario: Inspector 键盘操作

- **WHEN** 用户在 Inspector 中按 `F5`
- **THEN** 在可运行条件下开始检查；按 `Enter` 定位当前问题；`Ctrl+F` 聚焦搜索

### Requirement: 界面文案可翻译

Inspector 与 Dense Review 的用户可见文案 SHALL 通过 `tr()` 提取，四套语言包
SHALL 包含对应条目；配置键、枚举值与数据字段 SHALL 保持原样，不参与翻译。

#### Scenario: 英文界面

- **WHEN** 用户将语言切换为 `en_US` 并打开两个窗口
- **THEN** 界面不出现本次范围内的中文残留（Qt 标准按钮除外，另行记录）

### Requirement: 主操作图标

两个窗口的主操作与常用导航按钮 SHALL 显示与语义一致的图标；次要按钮 MAY 保持
纯文字。图标 SHALL 在浅色与深色背景下均可辨认。

#### Scenario: 主按钮识别

- **WHEN** 用户打开任一工作台
- **THEN** 开始/完成类主按钮带图标，且不改变原有文案与尺寸
