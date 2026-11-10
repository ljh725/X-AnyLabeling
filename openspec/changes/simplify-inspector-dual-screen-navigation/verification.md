# 实施与验证记录（2026-11-06）

## 代码完成范围

- 独立非模态单实例 Inspector；记忆正常窗口几何及自动推进偏好，恢复时将窗口约束到当前可用屏幕。
- 默认纵向问题列表和简短原因、明确的单对象选择、忽略、保存并复查；阶段、历史、详细状态、批量动作和候选仍可从更多入口访问。未新增预览或标注画布。
- 点击、键盘选择、Enter、双击和前后按钮共用导航入口；以稳定问题键提交游标、跨 200 条分页，保留移出当前筛选后的前后导航锚点。
- 主窗口桥接在跨图前校验目标图片和对象身份；取消、加载失败及对象失效不提交目标游标，失败恢复原文件、选择、形状历史和编辑状态。
- F1／F2 是窗口作用域快捷键；支持设置中的冲突检测、改键、清空及运行时更新，关闭会话停用，最小化仍可在主窗口导航。
- 三种简洁状态使用统一投影；人工忽略使用原可接受判断，编辑失效优先回待处理，不改变正式审核状态。
- 显式保存成功后使用报告冻结方案复查；绑定问题、同图上下文、编辑代次与导航代次。报告和反馈均保存成功、所有相关来源完整未再检出时才自动推进；失败可重试保存记录。普通保存未增加隐式检查。
- 中文操作说明、四语言新增文案、QM 和内嵌 Qt 资源已更新。

## 自动回归与环境

使用既有 `C:/Users/20441/.conda/envs/x-anylabeling-cu12/python.exe`（Python 3.12 / PyQt6），`QT_QPA_PLATFORM=offscreen`。配置、INI、图片和标注均由项目测试夹具隔离至 `.tmp/`；未使用用户真实数据。

| 范围 | 实际结果 | 证据 |
| --- | --- | --- |
| 完整 Inspector 与设置首轮 | 300 passed、1 skipped、4 failed；三项为新增快捷键后的字段计数预期，一项为高级按钮不再常驻的预期，均已更新 | [原始 JUnit](automated-tests.xml) |
| 完整 Inspector 与设置第二轮 | 307 passed、1 failed、9 subtests passed；规则入口测试仍使用运行开始时的旧常驻预期，随后已改为验证更多入口展开 | [原始 JUnit](automated-tests-final.xml) |
| 图片切换、编辑命令范围、锁定、拖动、稳定对象身份及相关 UI/schema | 68 passed、16 subtests passed | [JUnit](related-tests.xml) |
| 最终导航、规则入口与翻译 UI 回归 | 27 passed | [JUnit](final-ui-tests.xml) |
| 最终完整 Inspector 与设置 | 308 passed、9 subtests passed | [JUnit](delivery-tests.xml) |
| 最后增加活动窗口守卫后的定向导航回归 | 19 passed | [JUnit](session-guard-tests.xml) |

新增回归覆盖单击、程序刷新不导航、单对象明确选择、205 项跨页和原位置锚点、取消/失败游标恢复、状态优先级、保存失败停止、删除对象后复查、自动继续开/关、报告写失败不推进、迟到编辑结果、两窗口真实按键、最小化/关闭/重开、改键/清空/冲突、模态和无关工具窗口、跨图焦点及几何恢复。既有逐来源复查回归继续覆盖取消、截断、停用规则、版本变化、多来源未全解决和保留其他图/新问题。

## 静态检查与资源

- `openspec validate simplify-inspector-dual-screen-navigation --strict`：通过。
- `git diff --check`：通过；Git 的 CRLF/LF 提示不属于空白错误。
- Python 编译检查：通过。修改方法经过 Black 格式化，主窗口文件保留其他方法原格式。
- Flake8 发现两项既有 C901：`InspectorDialog._reconcile_candidate_intents`（25）及 `SettingsRuntimeApplier.apply_change`（23）。已用 AST 与 HEAD 比对确认两个方法未改变；未把全量静态检查记为无告警。
- 显式排除 C901 后，对修改的 Inspector、schema 和 runtime applier 静态检查通过。
- 四语言编译完成。编译器报告英语目录既有重复消息，以及日/韩目录各 28 条 unfinished 和 256 条未翻译旧消息；本次新增消息已提供翻译，未将旧目录整体完备性记为通过。

## 布局证据与真实双屏验收

[实现后截图](assets/inspector-implemented-offscreen.png) 由真实 Qt 控件、合成重复框样本及显式加载的 Microsoft YaHei 字体离屏渲染。不是实际双屏截图。离屏平台仅提供一个 800×800 虚拟屏幕，见 [环境记录](assets/offscreen-screens.json)。

任务 6.3 **未完成、保持未勾选**：自动化窗口按键与几何模拟不能替代物理双屏连续操作，也未修改任何旧变更的验收状态。本变更未归档。

### 2026-11-07 原生双屏验收尝试

- 原生 Windows Qt 检测到真实双屏：Q27G2S，2560×1440，可用区域 2560×1400；2490W1，1920×1080，可用区域 1920×1040，起点 x=2560。两屏均为 100% 缩放。
- 创建独立验收实例，全部配置、INI、图片和标注放在 `.tmp/inspector-native-20261107/`；两张合成图片各含两个稳定 ID 的重复框。未操作原先打开的用户数据集。
- 新实例成功启动，主窗口为 1400×1000，初始标注未修改、对象未选中。只读状态及屏幕信息见 [启动记录](assets/native-startup-state-20261107.json)。
- Computer Use 可读取新实例的辅助功能树，但首次截图失败：`FrameArrived timed out: timed out waiting on channel`。元素点击失败：`coordinate input geometry is unavailable`。重新枚举、唯一选择并激活同一验收窗口后，截图仍失败：`window capture timed out: timed out waiting on channel`。
- 按 Computer Use 恢复指引停止桌面输入，没有将这些启动检查记为双屏交互验收通过。验收实例的启动进程已终止，合成数据保留在项目临时目录；用户原标注会话未关闭。
- 待桌面捕获恢复后继续：Inspector 移到第二屏并缩放、两边 F1/F2 的同步与焦点、明确选中单框删除/撤销、保存复查、跨图取消、最小化、第二屏断开后的恢复以及不同缩放下核心按钮可用性，并附实际截图。
