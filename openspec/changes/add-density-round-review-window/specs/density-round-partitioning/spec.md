## Purpose

为高密度普通矩形标注提供稳定、可预测且可配置的空间分轮，使用户能按空间顺序一次覆盖全部类别，同时降低单个编辑视图中的矩形数量。

## ADDED Requirements

### Requirement: Eligible rectangles are partitioned independently of visibility filters
系统 SHALL 仅将当前图片中的普通 `rectangle` 实例纳入巡检分轮，并 SHALL 在分轮期间临时忽略类别筛选和单对象隐藏状态。非矩形形状 SHALL 不参与计数、排序或第二窗口交互。

#### Scenario: Hidden rectangles still participate
- **WHEN** 用户在进入巡检前通过类别筛选或对象可见性隐藏了部分矩形
- **THEN** 系统 SHALL 使用当前图片的全部普通矩形计算轮次，并在退出巡检后恢复原筛选与可见性状态

#### Scenario: Non-rectangle shapes are excluded
- **WHEN** 当前图片同时包含矩形和其他形状类型
- **THEN** 系统 SHALL 只对矩形分轮，且第二窗口 SHALL 隐藏并禁止交互其他形状

### Requirement: Spatial order follows image orientation
系统 SHALL 以矩形中心点生成稳定空间顺序。横图和方图 SHALL 以中心点 X 升序为主、Y 升序为次；竖图 SHALL 以中心点 Y 升序为主、X 升序为次。完全相同的中心点 SHALL 使用稳定身份或原始顺序作为最终决胜条件。

#### Scenario: Landscape image ordering
- **WHEN** 图片宽度大于或等于高度
- **THEN** 系统 SHALL 按从左到右的主顺序组织矩形，并在主坐标相同时按从上到下排序

#### Scenario: Portrait image ordering
- **WHEN** 图片高度大于宽度
- **THEN** 系统 SHALL 按从上到下的主顺序组织矩形，并在主坐标相同时按从左到右排序

### Requirement: Rounds are balanced under a configurable upper limit
系统 SHALL 使用正整数的每轮实例上限计算 `ceil(N / limit)` 个轮次，并 SHALL 在保持空间顺序的前提下将实例数尽量均衡分配，各轮数量差不得大于 1 且不得超过上限。默认上限 SHALL 为 10。

#### Scenario: Exactly divisible instance count
- **WHEN** 图片包含 40 个矩形且每轮上限为 10
- **THEN** 系统 SHALL 生成 4 个轮次，每轮包含 10 个矩形

#### Scenario: Non-divisible instance count
- **WHEN** 图片包含 34 个矩形且每轮上限为 10
- **THEN** 系统 SHALL 生成 4 个轮次，并均衡为 9、9、8、8 个实例或等价的稳定均衡分配

#### Scenario: No eligible rectangles
- **WHEN** 当前图片没有普通矩形
- **THEN** 系统 SHALL 保留该图片并显示零实例状态，不得自动跳过该图片

### Requirement: Limit changes apply on the next image load
系统 SHALL 在第二窗口提供每轮实例上限设置，并 SHALL 同时显示当前图片已应用值和待生效值。当前图片内修改设置不得重新分区；第一次加载不同图片时 SHALL 应用并持久化待生效值。

#### Scenario: Change limit during an image
- **WHEN** 当前图片使用上限 10，用户将待生效值改为 8
- **THEN** 当前图片 SHALL 继续使用原分区，第二窗口 SHALL 标示“当前 10、下一张 8”，且下一次加载不同图片 SHALL 使用 8

### Requirement: Membership and boundaries freeze for the current image
系统 SHALL 在图片首次进入巡检时冻结轮次成员和显示边界。移动、缩放、改类别或删除矩形不得触发重排、补位、轮次数压缩或边界移动。

#### Scenario: Existing rectangle crosses a boundary
- **WHEN** 用户把当前轮次的矩形移动到冻结边界之外
- **THEN** 该矩形 SHALL 继续属于当前轮次并保持可见，虚线边界 SHALL 保持不变

#### Scenario: Deletion empties a round
- **WHEN** 用户删除当前轮次中的矩形并使该轮次变空
- **THEN** 系统 SHALL 保留该空轮次直到离开当前图片，不得从其他轮次补入实例

### Requirement: New rectangles receive deterministic current-session membership
第二窗口创建的矩形 SHALL 归入创建时的当前轮次。主窗口创建的矩形 SHALL 按其中心点归入现有冻结空间轮次。零实例图片中新建的第一个矩形 SHALL 建立第 1 轮。新建操作不得重新分配已有矩形。

#### Scenario: Create in the review window
- **WHEN** 用户在第二窗口第 3 轮创建矩形
- **THEN** 新矩形 SHALL 保留在第 3 轮，即使该轮实例数超过已应用上限

#### Scenario: Create in the main window
- **WHEN** 用户在主窗口创建矩形
- **THEN** 系统 SHALL 根据新矩形中心位置把它加入相应冻结轮次，且第二窗口不得自动跳转

### Requirement: Round navigation is ordered and bounded
系统 SHALL 支持上一轮、下一轮和指定轮次跳转。轮次切换 SHALL 清除离开轮次的选择，且不得自动选择新轮次对象。最后一轮的下一步 SHALL 按既有保存策略进入下一张图片第 1 轮；第 1 轮的上一步 SHALL 进入上一张图片最后一轮。数据集首尾 SHALL 停止而不得循环。

#### Scenario: Advance after final round
- **WHEN** 用户在非末尾图片的最后一轮执行下一轮且保存成功或无需保存
- **THEN** 主窗口 SHALL 加载下一张图片，第二窗口 SHALL 显示该图片第 1 轮

#### Scenario: Save blocks cross-image navigation
- **WHEN** 当前图片存在修改且保存失败或用户取消保存
- **THEN** 系统 SHALL 停留在当前图片最后一轮并报告保存未完成

#### Scenario: Direct round jump
- **WHEN** 用户从轮次选择器选择任意有效轮次
- **THEN** 系统 SHALL 清除旧选择并显示目标轮次，但不得改变缩放和平移或标记跳过轮次为已完成

### Requirement: Round boundary is informational and secondary-window-only
系统 SHALL 在第二窗口以细虚线显示当前冻结轮次的大致空间边界，并显示轮次、总轮次和实例数。主窗口 SHALL 不显示该边界或进度，边界 SHALL 不参与命中、编辑或标注保存。

#### Scenario: Render current round indicator
- **WHEN** 第二窗口显示 4 个轮次中的第 2 轮且该轮有 10 个实例
- **THEN** 第二窗口 SHALL 显示等价于“轮次 2/4 · 10 个实例”的状态和冻结虚线边界，主窗口 SHALL 保持无巡检覆盖层

