# Windows 训练停止对照 · 2026-11-18

**结论为产品停止延迟缺陷。** 两个快照各跑 4 次，均在原 `join(3)` 断言失败，pytest 退出码均为 1。带观测的 6 次中，Windows 普通 `taskkill /T /PID` 均返回 128，进程继续运行。终止线程执行 `wait(timeout=5)` 后才强制回退，训练线程在这段时间阻塞于 `stdout.readline()`。强制终止后读管道返回，线程随后完成清理。两边复现表明该路径在两份基线均存在，归因依据是实测返回码和堆栈。

## 环境与复现

- Windows，`x-anylabeling-cu12` 的 Python 3.12.12，pytest 9.0.3，`QT_QPA_PLATFORM=offscreen`。逐轮环境与完整命令见 [runs.json](evidence/runs.json)。
- 维护候选 `0e4a223e2b8f74f9c8a9e093643b3fa581d8c293` 和本地集成 `a7a9a1048f2eab1e3a0272cd57b5c400becca970`，分别在 `.tmp/stabilize-maintenance-20261118/candidate` 与 `integration` 脱离分支检出。训练服务、指定测试和 `tests/conftest.py` 在两提交间无差异。
- 从仓库根目录使用以下 PowerShell 命令创建复现工作树。在现有检查目录运行时可直接重用其固定提交，输出目录建议另选。

```powershell
git worktree add --detach .tmp/stabilize-maintenance-20261118/candidate 0e4a223e2b8f74f9c8a9e093643b3fa581d8c293
git worktree add --detach .tmp/stabilize-maintenance-20261118/integration a7a9a1048f2eab1e3a0272cd57b5c400becca970
& 'C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe' reports/stabilize_maintenance_baseline_20261118/observe_stop.py .tmp/stabilize-maintenance-20261118 .tmp/stabilize-stop-rerun
```

运行器串行交替执行 `tests/test_auto_training/test_trainer.py::test_stop_training_terminates_silent_process_immediately`。第 0 轮直接使用 `python -m pytest`。第 1–3 轮由 [观察器](observe_stop.py) 转调原节点，记录真实调用和状态快照。原断言、终止命令、3 秒 join 和 5 秒产品等待都照常执行。每次使用单独 `--basetemp`、12 秒堆栈诊断及外层 45 秒硬超时，8 次均未触发硬超时。带观测运行额外等待真实训练线程退出，以保留清理证据。

## 逐轮结果

停止耗时从进入 `stop_training()` 开始计，join 耗时从进入测试的 `join(3)` 计。「首次观察退出」取强制终止返回后的 poll，精确退出瞬间位于两次观测之间。各轮通过退出后存活状态及线程栈确认清理已完成。

| 运行 | 停止调用返回 (s) | join (s) | join 返回时 | 首次观察进程退出 (s / 子进程码) | 工作线程结束 (s) | pytest 码 |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| [candidate-0](evidence/candidate-0.txt) | 未采 | 3 秒阈值 | 线程仍活着，断言短路未检查进程 | 未采 | 未采 | 1 |
| [integration-0](evidence/integration-0.txt) | 未采 | 3 秒阈值 | 线程仍活着，断言短路未检查进程 | 未采 | 未采 | 1 |
| [candidate-1](evidence/candidate-1.txt) | 0.000 | 3.016 | 子进程和训练线程均仍存活 | 5.531 / 1 | 5.781 | 1 |
| [candidate-2](evidence/candidate-2.txt) | 0.016 | 3.000 | 子进程和训练线程均仍存活 | 5.547 / 1 | 5.781 | 1 |
| [candidate-3](evidence/candidate-3.txt) | 0.000 | 3.016 | 子进程和训练线程均仍存活 | 5.516 / 1 | 5.750 | 1 |
| [integration-1](evidence/integration-1.txt) | 0.000 | 3.015 | 子进程和训练线程均仍存活 | 5.515 / 1 | 5.750 | 1 |
| [integration-2](evidence/integration-2.txt) | 0.000 | 3.016 | 子进程和训练线程均仍存活 | 5.516 / 1 | 5.766 | 1 |
| [integration-3](evidence/integration-3.txt) | 0.000 | 3.000 | 子进程和训练线程均仍存活 | 5.500 / 1 | 5.750 | 1 |

时间线的时钟分辨率有限。显示 0.000 表示落在同一采样刻度。六次观测均看到停止调用返回 True、非强制命令首次返回 128、强制命令返回 0，以及工作线程结束时临时载荷已经删除。

## 退出路径和后续范围

1. `TrainingManager.stop_training()` 设置停止事件并启动终止线程。训练线程在看到下一次事件检查前仍等待子进程输出。
2. `terminate_process_tree()` 忽略非强制 taskkill 的失败返回，继续等待 5 秒。3 秒时的两个线程栈分别停在 `trainer.py:147` 的管道读取和 `environment.py:187` 的进程等待。
3. `taskkill /F /T` 结束此测试的子进程。读线程随后经过停止事件路径，观测到一次与异步终止重叠的第二次普通 taskkill，继而清理临时载荷并退出。

这次保留了命令的原始 stdout/stderr 重定向，因此能够确认返回码、等待和回退顺序，具体 Windows 错误文字未采集。样本是原测试的静默 Python 子进程，未实测可见训练窗口、真实训练、子代进程树或其他 Windows 环境。退出后的通知次数仍是后续验收项，当前用例提前失败，未执行通知断言。

最小修复应聚焦普通终止明确失败且进程仍存活时尽快强制终止并验证退出。保留异步 UI 入口，验证正常退出、停止竞态和共用终止函数调用方。后续变更已建立，生产修复待实施。完整 Windows 回归留待修复落定后，既有其他失败见上轮报告。 [修复方案](../../openspec/changes/fix-windows-training-stop/proposal.md) · [历史回归](../maintenance_baseline_20261117/REPORT.md)

入库日志只去掉 pytest 生成的空白行缩进。原始字节另存于本地 `.tmp/stabilize-maintenance-20261118/raw-evidence/`。
