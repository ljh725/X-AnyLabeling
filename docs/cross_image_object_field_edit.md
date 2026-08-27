# 跨图已标记对象批量字段编辑

本功能位于 **Tool → Batch Edit Marked Objects...**。它使用当前项目内的
跨图标记快照，先预检，再一次性安全提交 JSON；标记本身不会在编辑器中
直接改盘。

## 可编辑字段

白名单字段为：`label`、`difficult`、`group_id`、`description`、`score`、
`flags.<key>` 和 `attributes.<key>`。每个字段只能设置一次。`group_id`
和 `score` 可以设置为 `null`；`flags` 子键只能是布尔值，`attributes` 子键
只能是 JSON 标量。

Shape ID、`points`、`shape_type`、`direction`、`kie_linking` 以及整个
`flags`/`attributes` 对象受保护，不允许批量覆盖。

## 缺失字段与 difficult 别名

如果所选字段不存在，设置操作会在目标 Shape 中新增它；已有相同值报告为
unchanged，已有不同值报告为 updated。未选字段不会被补齐，因此字段补全
是独立的后续功能，不属于本 change，也不是本功能的前置条件，更不会被
隐式调用。

部分旧标注把 `difficult` 放在 `flags.difficult`。预检只提示这个别名，
不会自动迁移或覆盖它；如顶层值与别名不一致，也会显示 warning。

如果嵌套父字段存在但不是对象（例如 `flags: "legacy"`），该文件整文件
标为 conflict，不进入暂存，原 JSON 保持不变。

## 安全提交与恢复

预检确认后，系统先生成并重新解析暂存 JSON，再检查源文件指纹，最后在
项目写锁下原子替换。源文件在预检后被其他操作修改、JSON 无法读取或
提交失败时，文件不会被静默覆盖；冲突/失败/取消对象的标记会保留，便于
修正后重试。成功提交会在事务目录写入 `manifest.json`，其中包含字段
计划、逐字段状态和逐对象状态，可用通用恢复入口从备份回滚。

取消只在提交开始前生效；进入原子提交阶段后取消按钮会被移除。未发生
任何 created/updated 时不会写盘。
