## Purpose

让画布透明度滑块只控制标注填充的可见程度，使底图在降低填充后仍可检查，同时保持边框、顶点、文字和本地矩形编辑提示的可读性，不改变原有颜色、几何或标注数据。

## ADDED Requirements

### Requirement: Opacity scales only annotation fills
系统 SHALL 将滑块 0～100% 作为已有填充 alpha 的乘数，默认 100% 保留已有填充透明度；不得把默认半透明填充强制变为不透明，也不得连续叠乘或修改原始颜色数据。

#### Scenario: Change and restore opacity
- **WHEN** 用户将原有半透明填充从 100% 调到 50%、0%，再调回 100%
- **THEN** 填充分别为原 alpha 的一半、不可见、原 alpha，往返调整无累积衰减，边框和标签保持清晰

### Requirement: Shape and mask fills behave consistently
系统 SHALL 对普通图形填充及既有掩码填充一致应用乘数，兼容选中和创建预览；填充透明度不得改变边框、选中顶点、旋转手柄、标签、分数、属性、群组标记、十字线以及矩形尺寸/告警提示各自的原有样式。

#### Scenario: Inspect a selected rectangle at zero fill
- **WHEN** 用户选择矩形并把填充调至 0%
- **THEN** 底图透出，框线、顶点、标签、尺寸和最小尺寸警告依然可读，拖边与单点拟合提示可用

#### Scenario: Render masks and mixed shapes
- **WHEN** 同屏存在多边形、已有掩码、旋转框以及线或点，用户调低填充
- **THEN** 可填充区域按比例变化，掩码不重复应用乘数，线与点的可见标记不因无填充而消失，图层顺序不变

### Requirement: Fill adjustment is a display-only operation
系统 MUST 保持底图像素和标注文件中的颜色、几何、对象身份与审核不变；纯显示调整不得产生标注脏状态、几何撤销项或自动保存，既有可视化导出继续沿用自身的输出规则。

#### Scenario: Save after changing display opacity
- **WHEN** 用户仅调整透明度并检查标注数据与原图
- **THEN** 不出现由透明度引发的标注文件修改或原图重写，重新设为 100% 可恢复原显示
