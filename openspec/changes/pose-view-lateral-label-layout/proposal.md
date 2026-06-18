## Why

Pose View 中人体关键点标签（如 `l_sho`、`r_sho`）目前主要依靠标签名的 `l_`/`r_` 前缀区分左右。实际标注时发现，默认布局常把左侧标签挤到身体右侧，或让相邻部位标签交叉重叠，标注人员必须凑近读取文本才能判断左右，认知负担高。通过把左前缀标签统一放在身体轮廓左侧、右前缀标签放在右侧，并按躯干/下肢分层、Y 轴从上至下排列，用户仅靠位置就能本能识别左右，大幅提升可读性。

## What Changes

- 在 Pose View 标签布局中新增**左右侧分层排列规则**：
  - 躯干标签（`l_sho`/`l_elb`/`l_wri`、`r_sho`/`r_elb`/`r_wri`）按左右侧分开，每侧按 Y 轴从上至下排列。
  - 下肢标签（`l_hip`/`l_kne`/`l_ank`、`r_hip`/`r_kne`/`r_ank`）同样左右分开、Y 轴从上至下排列，位于躯干标签下方。
  - 头部关键点（`nose`、`l_eye`、`r_eye`、`l_ear`、`r_ear`）在躯干 bbox 上沿横向排列，`nose` 居中，左右眼/耳按前缀分居两侧，偏移量小于躯干。
- 支持前缀 `l_` / `r_` / `left_` / `right_`（大小写不敏感）；无前缀标签回退到现有默认方向。
- 三种布局模式（`direct` / `anti` / `column`）全部生效。
- 标签矩形不得越过身体中线到对侧；空间不足时允许向同侧外推。

## Capabilities

### New Capabilities
- `pose-view-label-layout`: Pose View 模式下关键点标签的左右侧分层排列与防交叉规则。

### Modified Capabilities
- *(none - this is a layout behavior addition, not a change to existing capability requirements)*

## Impact

- **Files Affected**:
  - `anylabeling/views/labeling/widgets/pose_label/pose_layout.py`
  - `anylabeling/views/labeling/widgets/pose_label/pose_renderer.py`（调用顺序可能微调）
  - `tests/test_pose_layout.py`
- **Risk**: 低，仅影响 Pose View 开启且标签显示打开时的布局。
- **Testing**: 新增单元测试覆盖躯干/下肢/头部分层、前缀规则、中线约束、空间不足外推。
- **User Impact**: Pose View 标签左右关系更直观，减少误读。
