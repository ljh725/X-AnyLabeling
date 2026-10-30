# 第二次修复复核结果

日期：2026-10-29。结论：**本次修复范围复核通过**。第二轮发现的两个问题均不再复现，第一轮的回归也保持通过；本轮检查未发现需要阻止此次修复验收的新问题。该结论限于检查的实现路径和测试条件，不代表整个软件没有其他缺陷。

## 两项修复确认

1. **done 后列表缓冲未排空时拖入图片**：新增路径先进入完整图片集合，再通过 `_start_view` 发起新代次的统一筛选。旧请求及旧 UI 缓冲失效，已不依赖旧 done 事件搬运拖入队列。600 张图片、done 已到达且列表仍有缓冲的原复现通过，新图片进入列表且参与后续状态读取。
2. **拖入图片绕过有效搜索条件**：路径经同一后台匹配规则处理；原 cat 搜索下拖入 dog.png 的复现通过。名称匹配/不匹配、序号、属性筛选、阻塞属性筛选期间拖入和缓冲未排空时的不匹配拖入均通过。当前画布和未保存修改保持。

同时检查了单文件会话接纳拖入路径、空筛选结果下的等待导航、过期代次隔离、当前图状态回填和启动目录加载。旧尾批丢失问题没有回归。

## 本轮实际验证

使用项目现有隔离依赖，D:/Python311/python.exe、QT_QPA_PLATFORM=offscreen，真实 MainWindow 与临时图片/标注，运行：

```text
python -m pytest reports/staged_annotation_loading/test_review2_regressions.py reports/staged_annotation_loading/test_review_regressions.py tests/test_staged_output_window.py tests/test_staged_annotation_metadata.py tests/test_utils/test_file_search.py -q -p no:cacheprovider --basetemp=reports/staged_annotation_loading/review3-pytest
```

结果：**71 passed，28 subtests passed，83.33 秒**。日志：`review3-tests.log`。两轮原复现断言仍保留，没有通过删除断言或改变预期规避问题。

`openspec validate staged-annotation-loading --strict` 和 `git diff --check` 通过。没有修改应用源码、已有测试、真实 PRW 数据或任务勾选状态，本轮新增此报告及运行日志。

## 性能证据与范围

核对修复者的 `review2_fix_results.json`，当前 label_widget.py SHA256 与记录一致：`8a76decf358b1917278368fb7b2ae9eb8e59c6227cb79d2fdbffe6404a7c4a11`。记录中的带框首帧中位数约 0.090 秒，全状态完成约 6.522 秒，最大心跳间隔三轮均小于 0.070 秒。这是已有同机暖缓存、offscreen、只读 PRW 基准的证据核对，本轮没有另跑性能测试，不用于声称冷缓存或网络盘效果相同。

测试导入时仍打印此前已记录的 Windows 原生模块异常堆栈；本轮测试继续执行并给出上述通过结果，没有新增断言失败。完整候选审核套件和物理桌面交互未在此次复核范围内。
