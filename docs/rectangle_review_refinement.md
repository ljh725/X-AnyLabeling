# 矩形审核精修工作流

## 默认行为

`rectangle_review_refinement.enabled` 默认关闭。关闭时保留原有 precision factor、滚轮矩形编辑、整框方向键和 undo 语义。

开启后，单个已选矩形的正式边拖动使用 `target_gain`（默认 0.5）。Shift 临时切换为粗调；活动边支持 1px 方向键/滚轮微调，Shift 使用 5px。

鼠标点击边、Tab/Shift+Tab 可以交接活动边。Esc 取消未提交的边拖动，切图或窗口失焦会清理活动边、反馈 HUD、virtual cursor 和滚轮累积，不撤销已经提交的标注。

## 可选辅助

`assistance.loupe_enabled` 默认关闭。开启时只显示活动边附近的只读局部放大图，不改变 Canvas 缩放、命中测试或矩形坐标。

候选边缘服务只接受显式请求，候选显示为 preview；只有调用 accept 事务并通过几何校验后才允许提交。reject/cancel 不修改 shape、dirty 或 undo。

## 指标与隐私

`telemetry.enabled` 默认关闭。开启后指标写入本地 JSONL，可通过以下命令导出：

```powershell
python scripts/export_rectangle_review_metrics.py `
  --input <metrics.jsonl> `
  --output <episodes.csv> `
  --summary-output <summary.csv>
```

记录包含单框 wall/focused/active 耗时、缩放 action/step、拖动反向修正和实际几何撤销次数。session、episode、target 使用不透明 token；不记录图片路径、label、group_id 或坐标。写盘失败只产生一次非阻塞告警，不影响保存、undo、dirty 或切图。

指标文件属于本机用户数据；如需清除，删除对应 JSONL 文件即可。
