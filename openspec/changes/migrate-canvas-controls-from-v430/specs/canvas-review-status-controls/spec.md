## Purpose

在画布调整面板提供当前图片的三态审核入口，让用户可以就近设置验收结果，并使其与现有快捷键、文件列表、筛选和分阶段加载保持一致，不重新定义对象审核或复核工作流。

## ADDED Requirements

### Requirement: Canvas panel exposes the existing image review states
系统 SHALL 在画布调整面板提供互斥的“未验收”“合格”“不合格”，分别对应图片标注顶层 `checked` 的 `false`、`true`、`"failed"`；缺少字段视为未验收。重复选择同一项不切换到另一状态。

#### Scenario: Set a review status from the panel
- **WHEN** 当前有可用图片，用户选择不合格
- **THEN** 复用已有审核设置与保存流程，面板、菜单、文件列表状态图标和标题显示同一结果，保存字段为 `"failed"`

#### Scenario: No image is open
- **WHEN** 应用未加载图片或当前图片无效
- **THEN** 审核控件禁用或不接受操作，不创建标注文件，也不更改上一张图片的状态

### Requirement: Review controls reflect all existing update paths
系统 MUST 在加载图片、快捷键操作、菜单设置及既有自动标注重置审核后刷新面板状态；程序刷新面板不得再次触发保存，后台旧结果不得覆盖刚设置的状态。

#### Scenario: Switch images and use shortcuts
- **WHEN** 用户在不同审核状态的图片间切换，并通过快捷键设置合格
- **THEN** 面板先显示目标图片状态，随后与快捷键设置一致，不继承上一张状态或触发额外保存

#### Scenario: Background metadata finishes after review
- **WHEN** 用户通过面板设为合格后，较早开始的审核元数据扫描返回未验收
- **THEN** 最新人工状态继续有效，列表、搜索与面板一致，既有元数据版本保护仍生效

### Requirement: Review persistence keeps failures visible
系统 SHALL 沿用既有保存路径、输出目录与错误提示；保存失败时不得宣称已保存审核结果或把当前修改标为干净。面板操作不额外改变各对象的审核字段。

#### Scenario: Saving review fails
- **WHEN** 用户设置审核状态但标注文件无法写入
- **THEN** 显示保存错误并保留可重试的当前修改状态，面板反映当前内存状态，重新加载仍以实际保存的数据为准
