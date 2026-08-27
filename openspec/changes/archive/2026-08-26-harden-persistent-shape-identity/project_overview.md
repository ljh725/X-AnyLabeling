# Persistent Shape Identity — 最终项目说明索引

本目录是 OpenSpec 变更 `harden-persistent-shape-identity` 的正式归档，使用
`spec-driven` schema，原始 22 项任务全部完成。

完整的最终设计、JSON 结构、生命周期、批量迁移、碰撞概率、下游对象管理契约、
外部格式边界和验收标准见：

[X-AnyLabeling Shape 持久唯一身份项目说明](../../../../docs/persistent_shape_identity_project_design.md)

## 归档后实现补充

原始 OpenSpec 完成后，围绕同一身份契约补充了以下操作能力，但没有改变原规格的
核心不变量：

1. 工具菜单增加 `Assign Shape IDs to Project`，可递归治理旧项目 JSON。
2. 项目扫描和写入迁移到后台线程，进度信号节流，避免阻塞界面。
3. 增加 `scripts/ensure_shape_identity_order.py` 命令行迁移入口。
4. `xanylabeling_shape_id` 固定写为每个 Shape 的第一个键。
5. 身份迁移只处理 ID，不补齐其他 Shape 字段，不修改标签、坐标或几何表达。

这些补充遵循原设计中的“身份字段与业务字段分离”“旧文件兼容”“原子写入”和
“下游持久引用使用稳定身份”原则。
