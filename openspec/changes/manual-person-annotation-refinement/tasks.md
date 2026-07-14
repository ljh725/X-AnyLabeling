## 1. 配置与状态模型

- [x] 1.1 在默认配置中新增 `auto_person_instance: false`
- [x] 1.2 在默认配置中新增 `digit_shortcut_mode: rename|bind_draw`，默认 `rename`
- [x] 1.3 在默认配置中新增 `canvas_precision_factor: 4`
- [x] 1.4 在默认配置中新增 `canvas_edge_snap_range: 4`
- [x] 1.5 在 settings schema allow-list 中登记以上配置 key
- [x] 1.6 定义数字快捷绑定绘制的临时 pending context，保存来源对象引用、目标 label、目标 shape_type、解析后的 group_id、是否需要回填来源
- [x] 1.7 确保 pending context 只在当前文件有效，切图、取消绘制、切模式时清理

## 2. 功能一：新建 person 自动创建人物实例

- [x] 2.1 在手动新建 shape 的 label/group_id 写入路径中识别 `label == "person"` 且 `shape_type == "rectangle"`
- [x] 2.2 当功能开关开启且没有绑定绘制上下文时，调用 `Canvas.gen_new_group_id()` 自动生成新 `group_id`
- [x] 2.3 确保功能一优先于 `auto_use_last_gid`
- [x] 2.4 当 `auto_use_last_label` 与功能一同时开启时，提示连续 `person` 将自动生成新 `group_id`
- [x] 2.5 当 `auto_use_last_gid` 与功能一同时开启时，提示功能一优先，不沿用上一组 ID
- [x] 2.6 新建成功后显示“已创建 person #n”状态提示
- [x] 2.7 明确 auto-labeling 结果落地入口不触发功能一

## 3. 功能二：数字快捷绑定绘制模式

- [x] 3.1 将数字快捷重命名和数字快捷绑定绘制建模为互斥模式
- [x] 3.2 新增 `DigitBindDrawManager`，与现有 `DigitRenameManager` 分离职责
- [x] 3.3 在数字键入口中根据当前模式分流：`bind_draw` 模式走 `DigitBindDrawManager.handle_digit()`，否则保留现有重命名/普通绘制路径
- [x] 3.4 绑定绘制模式下读取现有数字快捷键映射，得到目标 `shape_type + label`
- [x] 3.5 限制 v0 来源为单选 `person` / `head` / `face`，多选或不支持来源时提示并拒绝
- [x] 3.6 来源有 `group_id` 时，新建对象继承该 `group_id`
- [x] 3.7 来源无 `group_id` 时，生成拟分配 `group_id` 并记录到 pending context，不立即回填来源对象
- [x] 3.8 限制 v0 目标为 `rectangle + person/head/face`，其他数字快捷映射提示不支持
- [x] 3.9 进入绘制前检查同一 `group_id` 下是否已有相同目标 label
- [x] 3.10 若同组同 label 已存在，提示并拒绝进入绘制
- [x] 3.11 绘制完成消费 pending context 时再次校验目标合法性和同组同 label 唯一性
- [x] 3.12 绘制完成后将 pending context 的 label、shape_type、group_id 写入新 shape
- [x] 3.13 若来源需要回填，将来源回填和新 shape 创建放在同一次 undo 快照/事务中提交
- [x] 3.14 确保取消绘制、切换图片、退出模式时清理 pending context，且来源对象不被回填

## 4. 数字快捷操作提示

- [x] 4.1 实现统一的数字快捷操作提示生成器
- [x] 4.2 模式切换时提示当前数字快捷模式
- [x] 4.3 仅在 `bind_draw` 模式下对选中对象变化提示选中数量、来源 label、shape_type、group_id
- [x] 4.4 数字键触发时提示数字键、目标 label、目标 shape_type、来源 group_id 和将执行动作
- [x] 4.5 拒绝执行时提示明确原因，例如未配置数字键、来源不合法、多选来源、同组同 label 已存在
- [x] 4.6 在来源无 `group_id` 时提示将自动创建新 `group_id`，并在绘制完成时回填来源
- [x] 4.7 为选中变化提示增加轻量去抖，建议 200ms 合并
- [x] 4.8 统一用户可见文案翻译 context，建议 `DigitShortcutHints`

## 5. 功能三：精修控制模式

- [x] 5.1 在矩形整体拖动、顶点拖动和矩形边拖动路径中识别精修控制模式
- [x] 5.2 普通拖动保持现有 `image_delta = screen_delta / canvas.scale` 行为
- [x] 5.3 精修拖动只缩放位移 delta，不改变 `transform_pos()`、hit-test 或 epsilon
- [x] 5.4 精修拖动使用虚拟光标累计：`virtual_prev_pos += (raw_pos - virtual_prev_pos) / precision_factor`
- [x] 5.5 支持修饰键临时精修，并保留可选锁定开关用于连续精修
- [x] 5.6 默认 `precision_factor = 4`，并在状态栏提示当前精修倍率
- [x] 5.7 将方向键默认整体移动调整为 1px
- [x] 5.8 将 `Shift + 方向键` 整体移动设为 5px
- [x] 5.9 增加矩形边键盘选边状态：选中单个 rectangle 后按 Tab 进入
- [x] 5.10 Tab 按 left -> top -> right -> bottom -> left 顺序循环当前键盘选边
- [x] 5.11 高亮当前键盘选边，复用矩形边编辑 active edge 样式
- [x] 5.12 Esc、切换选中对象、切换图片、进入绘制模式、点击空白取消选择、鼠标 hover 到任意矩形边时退出键盘选边
- [x] 5.13 增加矩形边 1px 单边微调
- [x] 5.14 增加矩形边 5px 单边微调
- [x] 5.15 为连续键盘微调增加 undo 合并窗口，采用 timestamp-based 替换式合并：`store_shapes()` 前检查 `now - last_snapshot_ts < 500ms` 则替换最后快照而非 append，不引入 QTimer
- [x] 5.16 确保精修微调遵守图像边界、最小宽高和反翻转约束

## 6. 功能四：局部边缘吸附

- [x] 6.1 新增当前文件灰度图与梯度图缓存，切图时失效
- [x] 6.2 新增图像局部边缘评分 helper，输入当前图像缓存、矩形边、搜索范围
- [x] 6.3 对 left/right 边沿 x 方向搜索，对 top/bottom 边沿 y 方向搜索
- [x] 6.4 对 left/right 边使用 x 法线方向梯度，对 top/bottom 边使用 y 法线方向梯度
- [x] 6.5 沿边中段采样梯度响应，避免角点噪声
- [x] 6.6 使用 median 聚合候选边的中段梯度响应
- [x] 6.7 默认搜索当前边附近 `±4` image pixels
- [x] 6.8 v0 使用自适应阈值 + 绝对下限双判据：`best_score >= k * local_max and best_score >= abs_floor`，`local_max` 取当前边搜索窗口内最大梯度响应；`k` 与 `abs_floor` 硬编码并保留配置 hook
- [x] 6.9 响应不足、偏移过大、会导致矩形翻转或小于最小尺寸时不吸附
- [x] 6.10 吸附前先 validate 候选；若候选会触发 `apply_edge_coord` clamp，则视为失败并保持原位
- [x] 6.11 按键触发当前选中矩形边吸附，不做实时吸附
- [x] 6.12 吸附成功时提示边名、旧坐标、新坐标和移动像素数
- [x] 6.13 吸附失败时提示“未找到可靠边缘，保持当前位置”
- [x] 6.14 吸附操作写入 undo/dirty 流程，支持撤销

## 7. 单元测试与交互测试

- [x] 7.1 测试 `person rectangle` 在功能一开启时自动生成新 `group_id`
- [x] 7.2 测试功能一不与 `auto_use_last_label` 互斥，连续 person 生成连续 `group_id`
- [x] 7.3 测试功能一优先于 `auto_use_last_gid`
- [x] 7.4 测试绑定绘制模式从已有 `group_id` 来源继承 ID
- [x] 7.5 测试绑定绘制模式在来源无 ID 时先延迟记录拟分配 ID，并在绘制完成后回填
- [x] 7.6 测试同组同 label 已存在时拒绝创建
- [x] 7.7 测试多选来源时绑定绘制拒绝
- [x] 7.8 测试数字快捷操作提示内容包含模式、来源、数字键、目标和动作结果
- [x] 7.9 测试精修拖动按 `precision_factor = 4` 降低图像坐标移动量
- [x] 7.10 测试键盘 1px/5px 整体和单边微调
- [x] 7.11 测试边缘吸附在合成强边缘图像上移动到正确坐标
- [x] 7.12 测试边缘吸附在低响应区域不移动
- [x] 7.13 测试边缘吸附不允许矩形翻转或低于最小尺寸
- [x] 7.14 测试绑定绘制来源回填与新建 shape 的 undo 原子性
- [x] 7.15 测试 Esc 取消绑定绘制后，来源对象 `group_id` 不变
- [x] 7.16 测试功能一不作用于 auto-labeling 结果落地入口
- [x] 7.17 测试精修连续拖动按 `precision_factor = 4` 稳定累计，不出现 `prev_point` 漂移
- [x] 7.18 测试绑定绘制 pending 期间禁用边吸附/单边微调等冲突操作
- [x] 7.19 测试吸附候选会触发 clamp 时保持原位
- [x] 7.20 测试键盘选边后，鼠标 hover 到任意矩形边即退出键盘选边状态
- [x] 7.21 测试连续键盘微调在 500ms 窗口内合并为一次 undo 快照（timestamp-based 替换式）
- [x] 7.22 测试边缘吸附在仅满足自适应阈值但低于绝对下限时不吸附（低响应纹理稀疏图）
- [x] 7.23 测试边缘吸附在仅满足绝对下限但低于自适应阈值时不吸附（弱相对响应）

## 8. 验证与文档

- [x] 8.1 运行相关 PyQt offscreen 测试
- [x] 8.2 运行受影响模块的 py_compile
- [ ] 8.3 手工验证数字快捷重命名模式旧行为不变
- [ ] 8.4 手工验证数字快捷绑定绘制模式的 person/head/face 补框流程
- [ ] 8.5 手工验证 100%、200%、400% zoom 下普通拖动与精修拖动的手感差异
- [ ] 8.6 手工验证稳定预览与矩形边编辑仍可正常使用
- [ ] 8.7 更新相关用户可见文案和必要的翻译资源
