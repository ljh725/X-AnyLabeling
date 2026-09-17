## Why

矩形边界微调依赖精细鼠标拖动；已有四极值创建与修正流程又通过主画面勾选和创建后自动进入修正耦合在一起。用户需要通过工具菜单显式选择任务，用可配置边界键完成定位，并让数字标签操作、四极值创建与键盘拟合有清楚且互斥的触发规则。

## What Changes

- 新增独立的“键盘快速拟合”会话：选中唯一普通矩形后显式进入，边界键立即定位，Enter／完成／Esc 退出并保留已提交修改，Ctrl+Z 撤销。
- **BREAKING**：移除主画面的“矩形工作台”启用勾选及常驻面板入口，改为“工具 → 矩形工具”；旧 enabled 配置不再决定功能可用性或启动时接管按键。
- **BREAKING**：普通矩形与四极值创建完成后都回到普通编辑状态，不自动进入修正或拟合。继续创建、旧单边精修、键盘快速拟合分别由显式动作触发。
- 四极值接入数字快捷键管理器，映射保存标签、rectangle 类型和绘制方式，兼容现有数字分页、重命名及绑定绘制。
- 四条边共享可配置键位，提供 QWER／1234 预设；按状态统一分派，拒绝输入不穿透到标签操作或其他快捷键。
- 按当前矩形中心实施半区保护；定位仅改一条边，不跨中心、不交换对边，不猜测用户意图。
- 统一四极值与拟合的浮动提示、边名顺序和反馈；显示可用键，成功与拒绝均有按键反馈。

## Capabilities

### New Capabilities

- `rectangle-tool-lifecycle`: 工具菜单入口、创建与修正解耦、草稿及拟合的完整生命周期。
- `rectangle-keyboard-fitting`: 可配置边界键、上下文分派、半区保护、原图坐标定位、浮窗及撤销。
- `digit-shortcut-rectangle-method`: 数字管理器中的矩形绘制方式、兼容存储及重命名／绑定绘制协调。

### Modified Capabilities

无。上述行为尚无对应已同步主规格；已有 `design-rectangle-creation-and-refinement` 等变更中的相关行为由本变更新决策取代，关系与收敛步骤见 design.md。

## Impact

- UI／控制：`widgets/rectangle_workflow.py`、`label_widget.py` 的工具动作和主布局、`widgets/canvas.py` 的输入及事务接点。
- 几何／反馈：`review_refinement/extreme.py`、现有单边修改及撤销基础设施，新拟合规则保持纯 Python 可测试。
- 数字映射：`widgets/label_dialog.py`、`digit_bind_draw_manager.py`、数字键分派；审计所有数字映射读写点，防止丢失绘制方式。
- 设置／兼容：`settings/schema.py`、`controller.py`、`runtime_applier.py`、默认 YAML 与中文／英文翻译。
- 复用普通 rectangle 的 JSON 格式、身份、标签、属性、分组、保存链路；不新增模型或第三方依赖，不引入梯度吸附。
- 本变更仅建立待实施设计；不宣称已实现或已验证操作效率。
