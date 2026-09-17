## Purpose

扩展数字快捷键管理器以选择矩形的两点或四极值创建方式，在保持现有数字分页、标签重命名、普通矩形文件格式及绑定绘制事务的条件下，使数字快捷创建能与独立键盘拟合明确协调。

## ADDED Requirements

### Requirement: Rectangle drawing methods are configurable per digit
数字快捷键管理器 SHALL 提供矩形两点与四极值两种绘制选项，每个数字页映射独立保存标签与绘制方式，并在编辑、翻页、保存和重启后保留。

#### Scenario: Configure paged four extremes
- **WHEN** 用户在某数字页将一个键设置为 person 矩形四极值，保存并重启
- **THEN** 同页仍显示该标签和四极值方式，在普通绘制情形按该键启动对应草稿

### Requirement: Method configuration preserves shape compatibility
数字映射 SHALL 使用 rectangle 几何类型与独立 drawing_method 表示绘制方式，缺省方法 SHALL 为 two_points。生成标注 SHALL 保持普通 rectangle 格式；未知方法 SHALL 保留配置并提示修正，不能静默启动另一种工具。

#### Scenario: Legacy mapping
- **WHEN** 加载只有 mode=rectangle 与 label 的旧映射
- **THEN** 仍按两点绘制且标签不丢失

#### Scenario: Four-extreme output
- **WHEN** 从数字映射完成四极值创建
- **THEN** 输出普通 rectangle，工具方法和临时极值点不写入标注 shape

### Requirement: Ordinary digit rename priority is unchanged
未在草稿／拟合中且处于选中对象的数字重命名情形时，数字键 SHALL 继续使用重命名映射。用户 SHALL 可通过取消选择后数字启动，或显式菜单／继续创建动作启动四极值。管理器 SHALL 告知这些适用条件。

#### Scenario: Selected object uses rename
- **WHEN** 重命名模式下选中对象，按同时配置了四极值绘制的数字
- **THEN** 执行原重命名行为，不启动四极值

#### Scenario: Unselected object starts method
- **WHEN** 用户取消选择，在普通绘制情形按四极值映射数字
- **THEN** 使用当前页标签和四极值方法进入草稿

### Requirement: Bind drawing supports four extremes atomically
绑定绘制模式 SHALL 先完成既有源目标、类别、分组和重复校验，再按数字映射的矩形方法进入创建；四极值 SHALL 与两点使用相同绑定提交保证，不放宽支持类别。取消、切图或提交失败 MUST NOT 因绘制方法变化回填源对象或留下部分绑定形状。

#### Scenario: Cancel bound four extremes
- **WHEN** 用户从合法源对象启动需延后回填 gid 的四极值绑定创建，然后取消草稿
- **THEN** 源对象不变，无新正式形状，无残留绑定待提交状态

#### Scenario: Commit bound four extremes
- **WHEN** 合法四极值绑定草稿完成且提交复验成功
- **THEN** 标签、目标分组及必要源回填按原绑定事务一起提交，回到普通编辑而非拟合

### Requirement: Temporary digit ownership preserves mappings
草稿和拟合期间 SHALL 暂停裸数字标签动作并显示提示，映射内容和当前页 SHALL 保留；退出后 SHALL 恢复既有行为。输入框中的数字 SHALL 始终作为文本输入处理。

#### Scenario: Resume mappings after fitting
- **WHEN** 用户退出键盘拟合后在普通状态使用数字键
- **THEN** 原数字页、绘制方法、重命名或绑定模式继续有效，不需要重新配置
