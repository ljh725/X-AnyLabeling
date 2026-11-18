## Why

用户决定在开始下一轮功能讨论前退出 Inspector 和 Dense Review。两项功能与普通标注、配置和修正成本统计在 Git 历史中交织，从当前代码定向移除可以保留已交付的其他能力及整理记录。

## What Changes

- **BREAKING**：移除 Inspector 独立检查窗口、规则检查、结果导航和复查入口，以及 Dense Review 工作区、批次复核、关联显示和两者的交接入口。旧快捷键和配置不能重新开启已退役功能。
- 普通画布继续支持现有矩形操作、对象筛选和分组、撤销重做、标注保存与导出、图片三态审核及修正成本统计。普通批处理及属性对话框继续使用原有原子 JSON 写入行为。
- 已有标注 JSON 的扩展数据继续往返保留。历史密集复核数据不再由产品解释或刷新。现存数据集附属文件、报告、测试证据和 Git 恢复点保留。
- 退役两项功能的现行规格、用户导航和活跃变更，修订保留功能的交叉引用，区分已退役、历史验证与仍需执行的待办。

## Capabilities

### New Capabilities

- `retired-review-data-compatibility`：记录功能退役后的产品边界、旧配置兼容及标注扩展数据的往返保留约定。此规格描述兼容行为，无新增操作入口。

### Modified Capabilities

- `canvas-controls-recovery`：更新画布恢复应保留的工作流与验证场景。
- `duplicate-box-inspection`：退役当前 Inspector 的重复框检查契约。
- `inspection-execution`：退役检查执行契约。
- `inspection-profiles`：退役检查规则方案契约。
- `inspection-result-navigation`：退役检查结果导航契约。
- `inspection-review-handoff`：退役 Inspector 与复核工作流的交接契约。
- `inspection-review-queue`：退役 Inspector 问题队列契约。
- `inspector-focused-review`：退役 Inspector 独立窗口与聚焦复核契约。

## Impact

- 生产范围涉及 `anylabeling/services/`、`anylabeling/views/labeling/`、应用配置及四语言资源。验证重点为画布、标注、设置、批处理、标签属性和修正成本统计。
- 文档范围涉及 `openspec/`、当前用户手册、定制与版本台账。专属开发脚本和测试随其功能退役，共用用例继续维护。
- 本地起点为 `ade2d67c`，工作分支为 `codex/4.2.1/remove-inspector-and-dense-review`，约定集成目标为 `codex/4.2.1-baseline-organization`。
