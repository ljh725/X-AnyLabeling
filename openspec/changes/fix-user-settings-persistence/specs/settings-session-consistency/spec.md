## Purpose

确保通用设置、数字快捷键管理器和其他配置入口在同一会话中使用一致的有效值，使保存、取消与重置只作用于用户明确修改的范围，避免旧草稿清空其他入口已经保存的内容。

## ADDED Requirements

### Requirement: Settings save preserves unrelated updates
系统 SHALL 仅保存本次明确修改的字段，保留其他入口已保存的数字映射、快捷键和其他配置；同一会话中的操作入口 SHALL 在后续展示或使用时反映最新已提交值。

#### Scenario: Save digits before general settings
- **WHEN** 用户保存数字 1 的矩形类别映射，随后修改并保存一个通用设置，退出并重启
- **THEN** 数字 1 的模式和类别完整保留，通用设置采用新值，数字映射不会回到空值

#### Scenario: Save a shortcut before another entry
- **WHEN** 用户保存自定义快捷键后，通过数字管理器、模型管理或显示菜单保存其他配置
- **THEN** 自定义快捷键继续生效并在重启后保留，其他配置按各自的修改更新

### Requirement: Draft cancellation and reset have explicit scope
系统 MUST 保留设置草稿的显式保存语义；关闭或取消未保存草稿不得撤销其他入口的已提交修改。页面重置仅影响该页面字段，通用设置的全部重置仅影响其实际管理字段；数字映射的清空只由数字管理器中明确确认并提交的操作触发。

#### Scenario: Cancel while digits were saved elsewhere
- **WHEN** 通用设置有未保存草稿，用户在数字管理器保存新映射后关闭通用设置
- **THEN** 草稿及预览按原规则撤销，新数字映射继续保留，取消不写入旧配置副本

#### Scenario: Reset a shortcut page
- **WHEN** 用户重置并保存一个快捷键页面
- **THEN** 该页面恢复默认，其他页面和数字映射保持原值

### Requirement: Stale sessions cannot silently replace changed fields
当本次拟保存字段自草稿基线起已被其他入口修改且新值不同，系统 SHALL 报告冲突并保留草稿；无关字段变化 SHALL 自动保留。用户可重新载入最新值后重新编辑并提交，系统不得静默选择旧值。

#### Scenario: Conflicting changes in two settings entries
- **WHEN** 两个入口从同一基线修改同一个快捷键并先后保存不同值
- **THEN** 首次保存保留，第二次保存提示冲突且不覆盖，用户未保存修改仍可查看和重新编辑

### Requirement: Closing an unchanged window cannot undo saved preferences
系统 MUST 在退出时仅处理本窗口尚需持久化的修改，不得用启动时快照或默认模板重写未修改字段；保存失败或冲突的草稿不得在关闭设置窗口时无提示丢弃，退出应用前 SHALL 提供重试或明确放弃的选择。

#### Scenario: Close an older application window
- **WHEN** 另一个窗口已保存数字映射及快捷键，未编辑这些字段的旧窗口随后退出
- **THEN** 已保存映射及快捷键不被旧窗口的退出操作还原
