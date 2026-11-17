# 维护测试修正：拟合模式延迟应用

基线 `cdd25660` 原测试两项失败，见本目录 `priority.log`；
`test_pending_mode_finishes_real_edit[commit-fit/cancel-fit]` 仅在鼠标事件设置
Shift modifier，没有发送启动拟合轮次需要的真实 Shift key press。
首次 `interaction_in_progress()` 即失败，未到达模式延迟应用断言。

本批只给该测试补真实 Shift 按下/释放；用窗口坐标映射固定虚拟指针，
不移动用户鼠标。产品源码、拟合规则和所有原断言不变。
完整文件还覆盖拖边、模式请求合并、取消、保存/重开、分组撤销重做、锁定及
真实子进程重启，结果 **36 passed，124.78s，退出码 0**。
命令与环境见[JSON](fit-fixture.json)、[完整日志](fit-fixture.log)、
[JUnit](fit-fixture.xml)。JSON 中 HEAD 为修正前 `cdd25660`，
运行带本批随后提交的唯一测试差异；生产源码树始终为
`01efe6fe526f49a44353ffcbc5efc5e089a1e77f`。

此修正不处理停止任务的交接失败；其状态仍单列保留。
