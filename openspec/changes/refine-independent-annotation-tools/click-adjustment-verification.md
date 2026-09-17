# 矩形点击调整反馈复查

日期：2026-09-15。范围：设计 D4–D6，任务 4.1–4.8、5.1–5.5。

## 根因及修复

- X/Y 动作没有关联实际获得焦点的 Canvas；已关联画布，并接入设置即时更新。用完整 LabelingWidget 的 Qt 键盘事件验证触发、旧键失效、清空和文本输入。
- 边参考线绘制错误地位于角预览条件内；已独立绘制。参考线使用可见画布区域，显示蓝色参考线及目标高亮、橙色新框轮廓；通过实际像素验证缩放和平移。
- 一次提交会清空轴向状态；已分离临时事务与编辑模式，保留当前轴/角和选择，每次有效修改仅产生一个撤销项。
- Esc、失焦和方式切换未完整清理角/轴状态；已统一取消并同步菜单，隐藏目标也立即取消。旧 Shift/分区入口不能在退出后重新启用点击改框。
- 角调整存在翻转归一化、连续操作和旧工具状态干扰；改为固定指定角、校验相反边界，拒绝无效矩形。
- 旧工具原先只隐藏部分入口，仍注册快捷键和事件过滤器；现由独立 RectangleCreation 负责四极值创建，删除旧流程、键盘拟合与 HUD 组件，移除旧设置项并忽略旧启用值。数字绑定改接独立创建，旧配置保留供回滚使用。
- 新增文案已更新中英文翻译，并通过项目脚本重新生成翻译资源。

## 验证结果

使用 `C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe`，Qt 平台为 `offscreen`，配置写入使用隔离路径。

```powershell
python -m pytest tests/test_rectangle_click_adjustment.py tests/test_rect_edge_click_canvas.py tests/test_rect_edge_alignment.py tests/test_rect_edge_click.py tests/test_rectangle_workflow.py tests/test_precision_mode.py tests/test_review_refinement_telemetry_qt.py tests/test_settings/test_schema.py tests/test_settings/test_controller.py -q --tb=short
# 147 passed；8 条现有 NumPy 二维向量弃用提示。

openspec validate refine-independent-annotation-tools --strict
# valid
```

- 删除旧组件后再次验证主窗口启动、旧配置不恢复流程、四极值创建：3 passed，进程正常退出；这些用例不重复计入 147 项。
- Black：点击调整、独立创建、设置及相关测试共 14 个文件检查通过。
- Flake8：点击控制器、独立创建、数字绑定、坐标算法、设置 schema 及相关测试通过；Canvas 通过。LabelingWidget 和 RuntimeApplier 的检查仍报告 7 处 F841、2 处复杂度问题，未宣称全库静态检查通过。
- 涉及文件 `git diff --check` 通过。
- 实际渲染证据：仓库 `artifacts/rectangle-click-adjustment/axis-preview.png` 和 `corner-preview.png`。

## 使用方法及验收边界

选中单个有效矩形，画布获得焦点后按 X 调整左右边、按 Y 调整上下边；移动鼠标预览，单击提交，Esc 退出并保留选择。角操作通过“视图 → 矩形点击调整 → 角点击调整”开启，再选角和点击新位置。X/Y 可以在现有快捷键设置中改绑。

本次完成点击调整、独立创建及旧流程退役的代码修复与自动验证。创建用临时真实图片验证了保存/重新加载、取消、连续创建、数字绑定与撤销；旧配置值启动不能恢复修正功能。原流程交互测试已改为保留能力测试与退役入口的反向验证。

未进行物理双屏人工验收或完整用户数据集重启验收，不能把本记录当作整体实机验收或归档结论；任务表已恢复真实状态。
