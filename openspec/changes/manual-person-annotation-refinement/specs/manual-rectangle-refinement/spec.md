## ADDED Requirements

### Requirement: 精修拖动降低图像坐标控制增益

系统 SHALL 保留普通拖动的既有坐标映射，并在精修控制模式下仅将拖动 delta 除以配置的 `precision_factor`；默认精修倍率 SHALL 为 4。

#### Scenario: 普通拖动保持原行为

- **GIVEN** 精修控制模式未启用
- **WHEN** 标注员在任意 zoom 下拖动 shape、顶点或矩形边
- **THEN** 图像位移 SHALL 继续按 `screen_delta / canvas.scale` 计算

#### Scenario: 精修拖动按倍率降速

- **GIVEN** `precision_factor == 4` 且精修控制已启用
- **WHEN** 标注员拖动 shape、顶点或矩形边
- **THEN** 有效图像 delta SHALL 为普通拖动 delta 的四分之一
- **AND** hit-test、epsilon 与 `transform_pos()` SHALL 保持不变

#### Scenario: 连续精修拖动不漂移

- **GIVEN** 精修拖动已经开始
- **WHEN** 收到连续鼠标移动事件
- **THEN** 系统 SHALL 使用虚拟光标累计有效 delta
- **AND** 不得因重复缩放上一原始位置产生 `prev_point` 漂移

### Requirement: 键盘提供 1px 和 5px 两档微调

编辑模式下，系统 SHALL 使用方向键移动 1 image pixel，并 SHALL 使用 `Shift + 方向键`移动 5 image pixels。

#### Scenario: 整体 1px 微调

- **GIVEN** 一个 shape 被选中且没有键盘选边
- **WHEN** 标注员按一次方向键
- **THEN** 整个 shape SHALL 沿对应方向移动 1 image pixel

#### Scenario: 整体 5px 粗调

- **GIVEN** 一个 shape 被选中且没有键盘选边
- **WHEN** 标注员按一次 `Shift + 方向键`
- **THEN** 整个 shape SHALL 沿对应方向移动 5 image pixels

### Requirement: 矩形支持显式键盘选边和单边微调

选中单个 rectangle 后，系统 SHALL 允许使用 Tab 按 `left -> top -> right -> bottom` 顺序循环键盘选边，并 SHALL 将方向键微调作用于当前边。

#### Scenario: Tab 循环选边

- **GIVEN** 当前只选中一个 rectangle
- **WHEN** 标注员连续按 Tab
- **THEN** active edge SHALL 按 left、top、right、bottom 循环
- **AND** 当前 active edge SHALL 使用明确高亮

#### Scenario: 当前边微调

- **GIVEN** rectangle 的 left 边处于键盘选边状态
- **WHEN** 标注员按方向键或 `Shift + 方向键`
- **THEN** 系统 SHALL 只移动 left 边 1px 或 5px
- **AND** 其余三条边 SHALL 保持原位

#### Scenario: 鼠标 hover 接管选边

- **GIVEN** 存在键盘 active edge
- **WHEN** 鼠标 hover 到任意矩形边
- **THEN** 系统 SHALL 退出键盘选边并把 active edge 控制权交给鼠标

### Requirement: 精修操作遵守矩形几何约束

整体移动、单边微调和直接边拖动 SHALL 遵守图像边界、最小宽高与反翻转约束，候选操作不能通过隐式 clamp 落到用户未选择的位置。

#### Scenario: 单边微调将导致翻转

- **GIVEN** 当前矩形已接近最小宽度
- **WHEN** 标注员继续向对边方向移动 active edge
- **THEN** 系统 SHALL 阻止会导致翻转或低于最小宽度的移动

#### Scenario: 直接边拖动越过图像边界

- **GIVEN** 矩形边正在被直接拖动
- **WHEN** 鼠标候选坐标超出图像范围
- **THEN** 系统 SHALL 保持矩形在图像边界内

### Requirement: 连续键盘微调合并 undo 快照

系统 SHALL 将同一对象上间隔小于 500ms 的连续键盘微调合并为一个 undo 操作，并 SHALL 在超出窗口后创建新的快照。

#### Scenario: 快速连续微调

- **GIVEN** 标注员连续按方向键且相邻输入间隔小于 500ms
- **WHEN** 系统保存 undo 状态
- **THEN** 系统 SHALL 替换本次连续操作的最后快照而不是持续追加

#### Scenario: 间隔后再次微调

- **GIVEN** 距离上一次键盘微调已经达到或超过 500ms
- **WHEN** 标注员再次按方向键
- **THEN** 系统 SHALL 创建新的 undo 快照

### Requirement: 局部边缘吸附由按键显式触发

系统 SHALL 只对当前选中的矩形边执行按键触发吸附，默认在当前边附近 `±4` image pixels 搜索，且 MUST 不启用实时自动吸附。

#### Scenario: 垂直边搜索

- **GIVEN** 当前选中 left 或 right 边
- **WHEN** 标注员触发边缘吸附
- **THEN** 系统 SHALL 沿 x 方向搜索法线梯度候选

#### Scenario: 水平边搜索

- **GIVEN** 当前选中 top 或 bottom 边
- **WHEN** 标注员触发边缘吸附
- **THEN** 系统 SHALL 沿 y 方向搜索法线梯度候选

### Requirement: 边缘吸附同时满足相对和绝对可靠性阈值

候选边 SHALL 使用边中段法线梯度的 median 评分，并 SHALL 同时满足相对于搜索窗口局部最大响应的自适应阈值和绝对响应下限。

#### Scenario: 两项阈值均满足

- **GIVEN** 最佳候选满足 `best_score >= k * local_max` 且 `best_score >= abs_floor`
- **WHEN** 候选同时满足几何约束
- **THEN** 系统 SHALL 将当前边移动到最佳候选坐标

#### Scenario: 仅满足相对阈值

- **GIVEN** 最佳候选达到相对阈值但低于绝对下限
- **WHEN** 标注员触发吸附
- **THEN** 系统 SHALL 拒绝吸附并保持当前边不动

#### Scenario: 仅满足绝对阈值

- **GIVEN** 最佳候选达到绝对下限但低于相对阈值
- **WHEN** 标注员触发吸附
- **THEN** 系统 SHALL 拒绝吸附并保持当前边不动

### Requirement: 边缘吸附先验证再应用

系统 SHALL 在修改矩形前验证候选偏移、响应、最小尺寸、反翻转和图像边界；任何需要 `apply_edge_coord` 再次 clamp 的候选 MUST 被视为失败。

#### Scenario: 候选需要 clamp

- **GIVEN** 最佳响应坐标应用后会被几何层 clamp
- **WHEN** 系统验证候选
- **THEN** 系统 SHALL 拒绝该候选并保持矩形原位

#### Scenario: 吸附成功后撤销

- **GIVEN** 当前边已成功吸附到可靠候选
- **WHEN** 标注员执行 undo
- **THEN** 当前边 SHALL 恢复到吸附前坐标

### Requirement: 冲突交互状态互斥

绑定绘制 pending 期间，系统 SHALL 禁用矩形边吸附和单边微调；矩形边拖动或键盘选边期间，系统 SHALL 不触发绑定绘制。

#### Scenario: pending bind 期间触发吸附

- **GIVEN** 数字快捷绑定绘制 pending context 正在生效
- **WHEN** 标注员触发矩形边吸附快捷键
- **THEN** 系统 SHALL 拒绝吸附且保持 pending bind 不变

#### Scenario: 键盘选边期间触发绑定

- **GIVEN** rectangle 当前处于键盘选边状态
- **WHEN** 标注员按数字快捷键
- **THEN** 系统 SHALL 保持边编辑语义且不得开始新的绑定绘制
