# 标注工作流对比与改进策略建议报告

> 生成日期：2026-08-17
> 依据：`.understand-anything/` 知识图谱（commit `92a7c15`，819 文件 / 2204 节点）+ 主代码逐项核验 + 主流标注工具调研（来源见 §8）。
> 范围：X-AnyLabeling 4.0.0-beta.4 个人定制 fork（当前分支 `feature/selection-optimization`）。

---

## 0. 结论先行（TL;DR）

**本质定位判断**：本项目的差距不在画布，而在流程层。在「单图标注效率」上，这个 fork 凭借数字键绑定绘制（bind_draw）、矩形精修三件套、视口保持、筛选导航、关键点补全、L1/L2 质检复核队列，已经达到甚至**超过** CVAT / Label Studio 的单机标注体验——这些恰恰是通用平台没有的深度垂直定制。真正的分水岭在于：它现在是一个「高效的标注编辑器」，而 CVAT / Label Studio / Roboflow 是「标注生产系统」。两者的区别不是功能数量，而是四件流程级能力：

1. **文件/任务状态机**（本项目只有 `checked` 布尔位 + unchecked 导航；CVAT 有 标注→校验→验收 三态）
2. **AI 结果的审核工作流**（本项目自动标注结果直接落地为普通 Shape；业界标配是"建议→人工确认/拒绝"队列）
3. **时序标注**（视频 track_id 不落盘、无帧间传播/插值）
4. **度量与数据集生命周期**（无标注速度/质量趋势统计，无版本化导出）

**五个最高杠杆改进**（详细论证与代码落点见 §5）：

| 优先级 | 改进 | 一句话理由 |
|---|---|---|
| P0 | A. AI 预标注建议队列（proposal 模式） | 自动标注从"覆盖式落地"改为"建议式确认"，这是业界已验证的最大提速杠杆 |
| P0 | B. 文件四态状态机（草稿/已标/已复核/已验收） | 现有 `checked` 布尔 + review.tsv 已有雏形，升级成本最低、流程收益最大 |
| P1 | C. 质检前置（标注时实时跑 L1 规则） | 把错误拦在产生时刻，比事后批量扫描便宜一个数量级 |
| P1 | D. 高价值交互迁移（F06/F08/F09/F13/F16/F15 共 6 项） | 21 项旧功能还剩 11 项未迁移，按工作流价值排序补齐 |
| P1 | E. 标注效率度量面板 | 没有度量就没有改进；SQLite 索引已在，只差统计视图 |

---

## 1. 项目现状盘点

### 1.1 架构分层（understand 图谱视角）

图谱共 16 层、2204 节点（839 函数 / 546 类 / 478 文件），核心分层：

| 层 | 规模 | 职责 |
|---|---|---|
| 应用入口 | 4 文件 | CLI、配置、QApplication 引导 |
| 标注核心 `views/labeling/` | 77 文件 | `label_widget.py`（6.6k 行）+ `canvas.py`（5.7k 行）+ Shape 模型 + 筛选导航引擎 + rect 精修 |
| 标注 UI 组件 `widgets/` | 48 文件 | 工具栏、标签对话框、数字键管理器、关键点工具、pose 视图、PPOCR/VQA 对话框 |
| 检查器外壳 + 质检 | 9 + 12 + 2 文件 | Inspector 5-Tab 面板；纯 Python L1/L2 质检核心；质检复核 PyQt 层 |
| 自动标注 | 10 + 166 + 4 + 53 文件 | Model 抽象基类 + 184 个模型配置（YOLO/SAM2/Grounding-DINO/DEIMv2/DepthAnything/PPOCR…）+ 推理引擎 |
| 配置与资源 | 199 文件 | 模型 YAML、翻译、Qt 资源 |

架构上有一个已经验证成功的模式值得后续所有功能沿用：**inspector 模式**——纯 Python 逻辑核（无 PyQt，可独立单测）+ 薄 PyQt 视图层 + 信号路由。L1/L2 质检（101 用例）和复核队列（22+11 用例）都是这么做的。

### 1.2 标注工作流五环节现状

| 环节 | 现状 | 评价 |
|---|---|---|
| **输入** | 目录打开、视频抽帧成帧序列（`utils/video.py`）、输出目录切换、EXIF 扫描 | 强 |
| **标注** | 全 shape 类型；数字键分页/改名/bind_draw；K 键关键点补全引导；视口保持（ViewportController）；框选（rubber band）；矩形边级编辑 + 滚轮调边；精修增益；同图 copy/paste；无限 undo | 强（个人定制密集） |
| **AI 辅助** | 单图 Run(i)、SAM 式点/框交互提示、VL 文本提示、批量全图（run_all_images + 进度框）、视频模型跟踪 + Reset Tracker、Replace/Preserve 开关、Skip-Detection 复用人工框 | 较强，但缺"建议→确认"环节 |
| **质检** | Inspector 5 Tab：8 条基础规则数据检查 + L1/L2 质检（阈值 YAML 化、report.json/review.tsv）+ 质检复核队列（后台扫描 worker、按 issue 导航、复扫合并、反馈写回 TSV）+ 文件 checked 勾选 + unchecked 导航 | 强（个人项目里罕见地成型） |
| **导出** | save_visualization（图/视频）、`tools/label_converter.py` 多格式、Inspector 按规则分目录导出 | 中等（一次性转换，无版本化） |

### 1.3 个人定制能力地图（本 fork 相对上游的主线）

1. **person/head/face 三框工作流**：Auto Create Person Instance（新建 person 自动发 gid）、Digit Bind Draw（选源对象按数字键绑定绘制、继承/回填 gid、同组去重）、Precision Refinement（精修增益 + Tab 选边 + 方向键 1px/5px）、局部边缘吸附（已判定为实验性，不再强化）。
2. **筛选与导航体系**：`filter_state/filter_engine/filter_navigation_engine` + `DatasetFilterIndex`（SQLite 索引，后台 worker 建库）+ 优先级排序拾取模式。
3. **质检闭环**：L1（合法性）/L2（12 条几何关系规则，face→head→person 匹配）+ 阈值 YAML + 复核队列 + 阈值建议（恒 pending 不自动生效）。
4. **pose 体系**：关键点标签布局/防遮挡/自动聚焦、K 键补全模式、VitPose 分歧排序质检（qc-110/111）。
5. **旧版（3.3.8）功能迁移**：feature_analysis/ 下 F01–F21，已迁移 8 项（F02/F03/F19/F11/F12/F14/F20/F21），部分实现 2 项（F07/F08），**未迁移 11 项**（详见 §5-D）。
6. 进行中（openspec/当前分支）：选择优化（Ctrl 多选 + 框选）、视口状态机形式化、pose 标签可见性解耦。

---

## 2. 主流标注软件工作流对比

### 2.1 对比对象

- **CVAT**：开源平台，工作流最完整的开源标杆。
- **Label Studio**：开源 + 商业版，多模态，web 协作。
- **Labelme / LabelImg**：单机轻量工具，本项目的"血亲"（X-AnyLabeling 源自 labelme 架构）。
- **商业平台**（Roboflow / Supervisely / Encord / V7）：数据集全生命周期 + 团队 + 度量，代表"天花板"形态。

### 2.2 工作流维度对比矩阵

| 维度 | CVAT | Label Studio | Labelme/LabelImg | 商业平台 | **本项目** |
|---|---|---|---|---|---|
| 组织模型 | Project→Task→Job（按帧切块分配） | Project→Task（队列自动/手动分配） | 无（单目录） | Project→Dataset→Batch | 无（单目录；有 SQLite 筛选索引可升级） |
| 文件/任务状态 | new→annotation→**validation→acceptance**（拒绝可开 issue 打回） | draft→predicted→**reviewed（accept/reject 打回）** | 无 | 类似 + 自定义工作流 DAG | `checked` 布尔 + unchecked 导航（**两态**） |
| 质检方法 | 人工审核 + ground-truth 对比 + honeypot 蜜罐 + 共识（多人背靠背） | reviewer 角色逐题 accept/reject | 人工自查 | 以上全部 + IAA 统计 + 主动质检 | **L1/L2 规则引擎 + 复核队列**（规则质检比 CVAT 细，人工审核环缺） |
| AI 辅助 | SAM/Mask 预标注、Nuclio 模型服务、交互式分割 | ML Backend 后端预标注 | 无 | SAM/自训模型 Label Assist、批量预标注 | 184 模型、单图/交互/批量/VL/跟踪（**模型广度第一**） |
| AI 结果确认方式 | 预标注落入草稿态，人工修改后提交 | predicted 态与 annotation 态分离，审后转正 | — | 建议→接受/拒绝→模型再学习 | **直接落地为正式 Shape**（仅 Replace/Preserve 开关） |
| 时序标注 | track id、**帧间插值**、关键帧 | 视频插值（部分模板） | 无 | 全套 | 跟踪只在推理侧，**track_id 不落盘、无插值** |
| 效率交互 | 快捷键齐全、属性面板 | 中等 | 极简 | 中等 | **最深**（数字键绑定绘制、精修、视口保持、边级编辑） |
| 度量统计 | 标注用时/速度报表 | 企业版报表 | 无 | 速度/质量/IAA 看板 | `overview_dialog` 静态统计（**无过程度量**） |
| 数据集生命周期 | 导出多格式 + 云存储 | 快照 | 手动 | **版本化、血缘、回滚** | label_converter 一次性转换 |
| 协作 | 多人多角色（annotator/reviewer/acceptor） | 同左（角色为企业版） | 无 | 团队全套 | 单机单人 |
| 部署形态 | web 服务端 | web 服务端 | 桌面 | SaaS/私有云 | **桌面单机（这是定位优势，不是缺点）** |

### 2.3 关键洞察

1. **开源平台的工作流标配是"状态机 + 角色"**。CVAT 的 job 状态机（annotation→validation→acceptance）和 Label Studio 的 accept/reject 打回循环，本质上只做一件事：让"做完"和"做对"是两个被系统区分的状态。本项目已经有 70% 的原材料（checked 位、review.tsv、issue 导航），缺的只是把布尔升级为状态机。
2. **2025–26 的效率主线是"SAM/自动预标注 + 人工确认（HITL）"**，业界普遍报告预标注能省 50–90% 的标注时间——但前提是预标注结果以"待确认建议"形态存在，而不是直接覆盖。本项目模型库极强（184 个），却在最后一步"建议→确认"上缺环。
3. **单机工具与平台的分水岭不是功能数量，而是流程闭环**。Labelme 加一百个快捷键也不会变成平台；反过来，本项目不需要 web 化、不需要多人协作，但把状态机、建议队列、度量做进单机，就能获得平台级的工作流收益。
4. **本项目的护城河是垂直深度**：person/head/face 绑定绘制 + gid 语义 + L1/L2 几何关系质检 + pose 补全，这套东西在 CVAT/Label Studio 里要靠自定义 schema + 外部脚本硬拼，远不如内置流畅。**改进策略应该是"把垂直深度包进流程闭环"，而不是向通用平台看齐。**

---

## 3. 差距分析：五个本质差距

| # | 差距 | 现状证据 | 业界参照 |
|---|---|---|---|
| D1 | **文件只有两态** | `checked` 布尔（`label_file.py` save 字段）+ `open_next_unchecked_image`（`label_widget.py:8264`）；review.tsv 的 decision 只在质检 Tab 内流转，不回写文件状态 | CVAT validation/acceptance；Label Studio accept/reject |
| D2 | **AI 结果无审核工作流** | `new_shapes_from_auto_labeling`（`label_widget.py:8978`）把预测直接变成正式 Shape；只有 `AutoLabelingResult.replace`（Replace/Preserve 开关，`types.py:13`）和 Skip-Detection 两个间接手段 | 所有平台的 predicted→annotation 两态转换 |
| D3 | **时序标注断裂** | 推理侧有跟踪（`run_tracker`，`model_manager.py:2215`）但 Shape/LabelFile 无 track_id/帧号字段（`label_file.py:182-258`）；无帧间 shape 传播、无插值；跨页粘贴（F06）未迁移 | CVAT track + interpolation |
| D4 | **无过程度量** | `overview_dialog.py` 只有静态数据集统计；SQLite 筛选索引已记录每文件 shape 概况，但无时间维度：不知道 张/小时、每类耗时、修改热点（哪些图被反复打开改） | CVAT/商业平台的标注速度报表 |
| D5 | **数据集无生命周期** | 导出 = 一次性格式转换（label_converter / save_visualization / inspector export_manager）；无快照、无版本、无"这批训练集来自哪次导出、包含哪些修订"的可追溯性 | Roboflow/Supervisely 版本化 |

另有一个**工程层面的差距**（不影响用户体验但影响改进速度）：`label_widget.py` 6.6k 行 + `canvas.py` 5.7k 行的巨石文件，以及文档失真（F10/F21 迁移文档声称的 `graphics/canvas_graphics_view.py` 架构实际不存在，实际落在 `widgets/` 下）。所有新增工作流功能应沿用 inspector 模式（纯 Python 核 + 薄 PyQt 层），避免继续增肥巨石文件。

---

## 4. 容易被忽略的角度

从"标注是一个生产流程"的本质出发，有几个角度通常在纯工具视角下看不到：

1. **度量先行**。没有基线数据，任何改进都无法证明有效。SQLite 索引已经在每次扫描时路过全部文件，加时间戳的成本极低，而它是一切效率优化的前提。
2. **建议式（proposal）集成优于覆盖式集成**。自动标注的正确用法不是"跑完就落盘"，而是"跑完标记为待确认，人工一键批量接受/逐个修正"。这同时解决了质检问题：AI 建议本身带置信度，低置信度框优先复核。
3. **质检前置比质检后置便宜**。现在 L1/L2 是事后批量扫描（虽然是后台 worker）。L1 级规则（label 合法性、person 必须有 gid、点数合法）完全可以在绘制完成的瞬间增量校验单文件，错误在产生时刻被拦截。L2 几何关系规则保留批量模式。
4. **质检副产品是训练金矿**。qc-110/111 的 VitPose 分歧排序已经在暗示这个方向：模型分歧大的样本 = 最值得人工标注的样本 = 下一轮训练集的最高价值子集。把这个变成常规机制就是单机版主动学习闭环。
5. **单机 ≠ 不需要状态机**。状态机的价值不是多人协作，而是"工作记忆外置"：标注员第二天打开软件，系统知道每张图处在哪个环节、下一步该做什么。一个人的流水线仍然是流水线。
6. **不要做的事**：web 化、多人协作引擎、通用平台化。这些与桌面单机定位冲突，且工程成本远超收益。参照系应该是"CVAT 的单人模式 + Roboflow 的自动预标注体验"，而不是完整平台。

---

## 5. 改进策略建议

### A.（P0）AI 预标注建议队列：从"覆盖落地"到"建议确认"

**目标**：自动标注结果不再直接成为正式 Shape，而是进入"待确认"层，人工以最低成本确认/修正/拒绝。

**做法**（复用质检复核队列已验证的架构）：
1. Shape 增加运行时属性 `source = manual | ai_pending`（不写入正式 JSON 字段，或写入后由导出过滤）。
2. 新增纯 Python `AiSuggestionQueue`（对标 `quality_review_queue.py`）：批量跑完后按文件+置信度列出全部待确认项。
3. 画布层：`ai_pending` 的 Shape 用虚线/降透明度渲染（Canvas 已有 per-shape 渲染分支可挂）。
4. 确认动作：单选 Tab/Enter 确认；批量"本图全部接受"（当高置信占比高时，这一下就是最大的时间节省点）；拒绝即删。确认后转正式 Shape。
5. 与 D2 打通：确认动作本身记录进 review 流（复用 review_feedback.tsv 的 upsert 模式）。

**代码落点**：`auto_labeling.py` 结果回调 → `new_shapes_from_auto_labeling`（`label_widget.py:8978`）插入 pending 状态；渲染在 `canvas.py` drawShape 分支；队列为新增 `inspector/` 平级纯 Python 模块。

**参照**：CVAT/Label Studio 的 predicted 态；Roboflow Label Assist 的 accept/reject 交互。

### B.（P0）文件四态状态机：草稿 → 已标注 → 已复核 → 已验收

**目标**：让"做完"和"做对"被系统区分，形成单人流水线。

**做法**：
1. `checked: bool` 升级为 `stage: str`（向后兼容：旧 JSON 的 `checked: true` 读入时映射为"已复核"）。
2. 四态语义：`draft`（有过修改未提交复核）→ `labeled`（标注员自检完成）→ `reviewed`（质检复核通过，对应现有 review.tsv decision=approve）→ `accepted`（终态，不再进入任何待办导航）。
3. 状态迁移点：`set_dirty()` → 自动回退 draft；质检复核动作 → reviewed；手动/全部通过 → accepted。
4. 导航升级：现有 `open_next_unchecked_image` 泛化为"跳到下一个 stage < X 的文件"，配合筛选导航引擎（`filter_navigation_engine.py`）按 stage 过滤。
5. 状态栏显示当前文件 stage + 各 stage 计数（进度条效果）。

**代码落点**：`label_file.py` save/load 字段；`flat_index.py` 的 FlattenedRecord 加 stage 列；`quality_review_queue.py` 的 decision 写回点同步迁移。

**参照**：CVAT annotation→validation→acceptance 状态机（单人版裁剪）。

### C.（P1）质检前置：L1 规则实时化

**目标**：错误在产生时刻被拦截，而不是批量扫描后回头改。

**做法**：
1. 把 `l1_rules.py` 的 5 条 L1 规则（label 合法、shape_type 匹配、points 非空、person 矩形 gid 必填、bbox 合法）包装为增量校验器：shape 创建/编辑/标签修改的提交点（`canvas.py` 的 commit 路径与 `label_widget.py` 的 label 变更路径）调用，单 shape 校验 < 1ms。
2. 违规呈现：不阻塞输入，用状态栏 + shape 渲染标记（红角标）；违规文件在文件列表加图标。
3. L2 几何规则保持现状（需要跨 shape 上下文，批量后台扫合适），但 B 的 stage 机制保证 L2 未通过的文件不能进入 accepted。

**代码落点**：`l1_rules.py` 已是纯函数（`run_l1` 按文件），抽出 per-shape 变体即可；UI 挂 `set_dirty()` 附近的轻量 hook。

**参照**：表单实时校验模式；CVAT 的 issue 即时标注。

### D.（P1）交互功能迁移优先级排序（剩余 11 项）

按「工作流价值 ÷ 实现成本」排序建议：

| 顺位 | 功能 | 理由 |
|---|---|---|
| 1 | **F08 循环选择重叠 Shapes**（部分实现） | 重叠 person 密集场景是本项目核心场景，点击轮换是高频操作；已有 `_shape_hit_candidates` 基础（`canvas.py:2339`），补连续点击循环状态即可 |
| 2 | **F06 跨页复制粘贴** | 重复场景（多张相似图）效率倍增器；且是 D3 帧间传播的前置能力 |
| 3 | **F09 反选** | 框选（已实现）+ 反选 = 批量操作完备；几行代码的收益 |
| 4 | **F13 点拟合矩形框** | 小目标 person 框直接点两角，比拖拽稳；与精修工作流互补 |
| 5 | **F16 智能标签显示**（标签避让/引导线） | 密集场景可读性；但注意与已有 pose_label 布局系统、`label_display_mode` 的关系，先做统一设计再动手 |
| 6 | **F15 数据管理中心** | 与建议 E 合并实施（本质都是数据集视图） |
| 低 | F01 Ctrl 双击放大 / F04 多标签循环 / F10 ShowSelectedLabelOnly / F17 分组列表视图 / F18 形状约束 | 与现有能力重叠度高（现有缩放/改键/label_display_mode/筛选已覆盖大部分场景），缓做 |

**注意**：迁移文档存在架构失真（F10/F21 引用的 `graphics/` 路径不存在），每项动手前先用 feature_analysis 文档 + 代码核验双确认。

### E.（P1）效率度量面板：让改进可证明

**做法**：
1. `DatasetFilterIndex` 建库时记录每次扫描时间戳，shape 计数变化即工作事件；再加一个轻量 `session_log`（文件打开/关闭/保存时间戳，纯追加 CSV 即可，不引 PyQt）。
2. 日报视图（挂 Inspector 或独立 Tab）：今日完成 X 张（按 stage 迁移计）、张/小时趋势、每 label 新增数、修改热点 Top N 文件（反复保存的图 = 规则不清晰或难度异常，值得人工审视）。
3. 这是 D4 的直接解，也是 A–D 所有改进的效果验收仪表。

**代码落点**：`dataset_filter_index.py` 加列；统计纯 Python 模块 + 一个表格视图。

**参照**：CVAT 标注报表；商业平台速度看板。

### F.（P2）视频时序标注补课

**做法**：
1. Shape/LabelFile 增加 `track_id` 与帧序字段（向后兼容可选字段）；跟踪模型结果落地时携带。
2. 帧间传播：选中 shape → 下一帧粘贴（F06 的帧间版）；关键帧 + 线性插值（先支持 rectangle，CVAT 验证过这是视频 bbox 标注的最大效率来源）。
3. 视频文件组识别：抽帧目录命名已含序号，可自动识别为序列。

**前提**：仅当工作内容转向视频标注时才投入；纯图片工作流下优先级最低。

### G.（P2）数据集版本化导出

**做法**：导出时生成 manifest（文件清单 + 各文件 stage + 规则版本 + 阈值 profile id + 日期），每次导出原子落盘为 `export_YYYYMMDD/`；训练时能回答"这批数据是哪个版本、哪些文件已验收"。纯 Python，成本低于以上各项。

### 实施路线图

| 阶段 | 内容 | 里程碑 |
|---|---|---|
| 一（当前～1 个月） | B 状态机 + C L1 实时化 + E 度量日志先行（E1 最小版） | 单人流水线闭环：draft→accepted 可导航、可计数 |
| 二（1–2 个月） | A 建议队列 + D 顺位 1–4 迁移（F08/F06/F09/F13） | 自动标注确认式落地；交互补齐 |
| 三（按需） | D 顺位 5–6、F 视频、G 版本化 | 按业务方向取舍 |

### 风险与注意事项

1. **巨石文件约束**：A–G 所有新逻辑放独立模块（inspector 模式），`label_widget.py`/`canvas.py` 只加挂载点，遵守 AGENTS.md 的上下文预算规则。
2. **向后兼容**：`checked` → `stage`、Shape 新字段都要走"缺省即旧行为"的迁移路径（`config.py` 已有 legacy 迁移先例可参照）。
3. **不盲目对标平台**：协作、云存储、多人队列明确不做；每个建议都应能回答"单人单机下这解决了什么"。
4. **文档先行核验**：迁移类工作（D）先核验 feature_analysis 与现状的差异，避免按失真文档施工。

---

## 6. 一页总结

```
现状：标注效率（画布层）业界第一梯队 ⊃ CVAT 单机体验
      流程能力（状态/AI审核/时序/度量）落后于平台级工具
战略：不做平台，做「单人标注流水线」——
      把已有的垂直深度（三框绑定、L1/L2 质检、筛选导航）
      包进 状态机 + 建议队列 + 度量 三件流程级基础设施。
P0    文件四态状态机（复用 checked + review.tsv）
P0    AI 建议队列（复用质检复核队列架构 + Replace 开关语义）
P1    L1 实时校验 / 交互迁移 F08·F06·F09·F13 / 效率度量
P2    视频时序（track_id + 插值）/ 版本化导出
不做  Web 化、多人协作、通用平台化
```

---

## 7. 附：本项目 vs 对比工具的工作流覆盖度速览

| 工作流环节 | CVAT | Label Studio | Labelme | 本项目 | 备注 |
|---|---|---|---|---|---|
| 输入管理 | ●●● | ●●● | ● | ●●○ | 缺批次/任务概念 |
| 绘制效率 | ●● | ●● | ●● | ●●● | 数字键体系独有 |
| AI 预标注 | ●●● | ●●● | ○ | ●●● | 184 模型，广度第一 |
| AI 结果审核 | ●●● | ●●● | — | ● | 本报告建议 A |
| 规则质检 | ● | ● | ○ | ●●● | L1/L2 引擎超越两者 |
| 人工复核流程 | ●●● | ●●● | ○ | ●○ | 本报告建议 B |
| 时序标注 | ●●● | ●● | ○ | ○ | 本报告建议 F |
| 度量 | ●● | ●● | ○ | ○ | 本报告建议 E |
| 数据集版本 | ●● | ●● | ○ | ○ | 本报告建议 G |

（●●● 完整 / ●● 可用 / ● 有雏形 / ○ 缺失）

---

## 8. 参考来源

- [CVAT Quality Control in Data Annotation](https://www.cvat.ai/academy/labeling-quality-control) — 全量审核、ground truth、蜜罐、共识
- [CVAT Complete Workflow Guide for Organizations](https://docs.cvat.ai/docs/guides/workflow-org/) — job 状态机（annotation→validation→acceptance）与角色流水线
- [CVAT UI Overview: Projects, Tasks, Jobs & Roles](https://www.cvat.ai/academy/cvat-overview)
- [Label Studio: How to Review Tasks](https://docs.humansignal.com/guide/onboarding_reviewer)
- [Label Studio Enterprise Features（角色权限/队列）](https://labelstud.io/guide/enterprise_features)
- [Lightly: 12 Best Data Annotation Tools](https://www.lightly.ai/blog/data-annotation-tools) — SAM 系工具显著降低标注时间的行业结论
- [Roboflow: 5 Best Image Annotation Tools](https://blog.roboflow.com/best-image-annotation-tools/)
- [Encord: 18 Best Image Annotation Tools](https://encord.com/blog/best-image-annotation-tools/)
- [Auto Annotation Tool: Best Options](https://labelyourdata.com/articles/data-annotation/auto-annotation-tool) — HITL 半自动路径
- 仓库内部：`.understand-anything/knowledge-graph.json`、`docs/feature_summary.md`、`docs/qc-*` 系列、`feature_analysis/F01–F21`、`openspec/changes/`
