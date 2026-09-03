## Context

参见 [proposal.md](proposal.md) 的动机和 [dataset-label-thumbnail-browser spec](specs/dataset-label-thumbnail-browser/spec.md) 的行为契约。现有 `DatasetFilterIndex` 已使用 SQLite 保存 `files` 与轻量 `shapes` 行，并由 `DatasetIndexController` 负责缓存生命周期和单文件 `label_saved()` 刷新；当前 schema 只含 `shape_index`、`label`、`group_id` 和 `shape_type`，不足以生成或唯一定位对象缩略图。

项目也已实现 `MarkedObjectRef`、`ObjectRelabelPlan`、`ObjectRelabelEngine` 和统一 Qt 协调流程。该流程按 `(project_id, image_id, xanylabeling_shape_id)` 定位对象，并已处理当前文件 dirty 状态、预检、备份、原子提交、恢复清单、结果同步及索引单文件刷新。新窗口应成为这两套能力之间的查询与选择界面，而不是新的数据所有者或写入方。

运行约束为单用户、单应用实例操作一个标签数据集。现有同进程写入门和提交前文件指纹验证继续作为统一事务的一部分复用，但本变更不设计多人或多进程协调协议。

## Goals / Non-Goals

**Goals:**

- 让 SQLite 直接提供生成缩略图和构造永久对象引用所需的最小字段。
- 保证大数据集下每次只查询一页、只解码可见内容，且后台结果有明确代次边界。
- 将缩略图选择无损转换为现有对象改标快照，保持一个写盘实现。
- 让成功写盘、SQLite 局部刷新和当前标签重新查询形成确定闭环。

**Non-Goals:**

- 不把完整 Shape JSON、原图或缩略图二进制存入 SQLite。
- 不让缩略图窗口编辑除 `label` 以外的字段，也不复用通用字段编辑界面扩大首版范围。
- 不实现跨页选择队列、对象删除、自动标注或新的撤销/重做栈。
- 不增加文件服务器、数据库服务、文件锁、协作状态或冲突合并 UI。

## Decisions

### Decision 1: 扩展现有派生索引，而不是创建缩略图专用数据库

把 `DatasetFilterIndex` schema 升级一版，在 `shapes` 行增加：

```text
shape_id
bbox_x_min, bbox_y_min, bbox_x_max, bbox_y_max
```

轻量扫描继续只读取顶层 `shapes` 数组；对每个 Shape 提取 `xanylabeling_shape_id`，并从数值型 points 计算轴对齐包围盒。原始 points、完整 Shape、根 JSON 和 `imageData` 不进入数据库。schema 版本不匹配时沿用现有“丢弃并重建缓存”策略，不做持久数据迁移。

不对 `(file_id, shape_id)` 添加强制唯一约束。异常历史 JSON 中的重复或非法 ID 仍可被索引和展示为错误状态，最终写入资格由现有严格预检判定；让一个异常对象破坏整库重建得不偿失。

**Alternatives considered:** 新建独立缩略图数据库或在每次打开窗口时扫描全部 JSON。前者复制文件生命周期与同步逻辑，后者浪费现有持久索引并增加启动等待，因此均不采用。

### Decision 2: 增加只读对象页查询契约

索引层新增不可变结果模型，例如：

```text
DatasetThumbnailRef
├── image_path / json_path
├── file_sort_order / shape_index
├── shape_id / label
└── bbox
```

查询接口接收一个精确标签、`limit` 和 `offset`，返回总数及最多 100 行，排序固定为 `files.sort_order, files.image_path, shapes.shape_index`。`DatasetIndexController` 只在 READY 状态转发该接口，窗口不得持有或操作裸 SQLite connection。

首版选择仅属于当前查询页。切换标签或页面前如果有选择，界面清空该选择；不建立跨页待处理队列。

**Alternatives considered:** 一次查询标签的全部对象后在 Qt 内分页。16 万级结果会增加内存和状态管理，且 SQLite 已适合完成分页，因此采用数据库分页。

### Decision 3: 使用模型/委托式的独立非模态窗口

新增独立目录承载窗口、页面模型、缩略图调度和缓存，主窗口只负责创建/显示一个可复用的非模态窗口、提供当前项目上下文并接收改标请求。缩略图网格使用模型/视图与自定义 delegate，避免为每个对象创建重型 QWidget。

窗口状态由 `(dataset generation, selected label, page number, render generation)` 标识。标签、页面、数据集或窗口生命周期变化都会推进 generation；后台返回结果必须匹配当前 generation 才能进入模型。

**Alternatives considered:** 把网格直接堆入 `label_widget.py` 或 Inspector。前者扩大高成本文件职责，后者会把数据检查工作流与独立的数据集改标工作流耦合，因此采用独立窗口和薄入口。

### Decision 4: 图片按来源分组解码，缩略图采用两级可丢弃缓存

当前页查询结果只保存轻量引用。delegate 请求可见项时，调度器先查内存 LRU，再查磁盘缓存；未命中请求按 `image_path` 合并到后台任务。一项图片任务通过 `QImage` 解码原图一次，对该图当前请求的多个 bbox 分别裁剪、缩放，并把 `QImage` 结果送回 UI 线程；`QPixmap` 只在 UI 线程创建。

缓存键包含规范化图片路径、图片 mtime/size、Shape ID、bbox 和目标尺寸。磁盘缓存放在 X-AnyLabeling 的用户缓存目录下、按数据集哈希隔离；它不进入标签数据目录，也不参与备份和同步。键变化自然使旧项失效，缓存目录可整体删除重建。

对 bbox 使用 `floor(min)` / `ceil(max)` 后裁到图像边界；裁剪后宽或高不为正时返回错误占位。首版不增加自动 padding、智能构图或不同 Shape 类型的专用渲染规则。

**Alternatives considered:** 预生成整个标签的缩略图、每个 Shape 独立解码原图或把 PNG 存进 SQLite。三者分别造成前台等待、重复解码和数据库膨胀，因此采用可见性驱动的分组任务与外部缓存。

### Decision 5: 缩略图改标调用现有统一协调器

把 `label_widget.py` 现有“从活动标记仓库启动改标”的流程提取为可接收不可变 `MarkedObjectRef` 快照的统一协调入口。原“修改已标记对象的标签”动作仍从 `MarkedObjectStore` 取得快照；缩略图窗口则从当前页选中项构造同样的 refs。两者随后共享：

```text
处理当前 dirty 文件
→ build_object_relabel_plan
→ preflight / 用户确认
→ stage / commit
→ 结果应用与索引刷新
```

缩略图窗口不把浏览选择写入标注 JSON，也不要求把选择持久加入全局标记集合。统一协调器向来源窗口返回结构化终态，使其只清除成功、无变化或确认已删除的项，并保留失败项。

这也收敛了讨论稿中的“当前文件与其他文件双路径”：用户可见约束仍是绝不覆盖当前未保存内容，但实现直接复用已经验证过的 dirty 处理和单一事务，而不是再造一个当前文件专用写法。

**Alternatives considered:** 窗口直接调用 `LabelFile.save()` 或直接更新 SQLite。两种方式都会形成第二写入口，并绕过现有预检、备份和结果处理，因此禁止。

### Decision 6: JSON 提交成功后按文件重扫 SQLite，再重新查询页面

统一改标结果中的成功文件继续逐个调用 `DatasetIndexController.label_saved(image_path)`，由控制器从 JSON 重扫该文件；不执行推测性的 SQL `UPDATE label`。控制器增加可供窗口监听的局部刷新完成/延迟信号，窗口等受影响文件刷新完成后重新查询当前标签总数和当前页。

如果页尾对象退出后当前 offset 超过新总数，页码回退到最后一个有效页。若索引刷新失败或被正在运行的 rebuild 延迟，窗口进入 stale 状态并禁用下一次提交，直到控制器恢复 READY；不得继续显示旧结果并允许写入。

**Alternatives considered:** JSON 和 SQLite 在一个数据库事务概念中同时更新。两者不是同一种存储，无法提供真正原子性；把 JSON 作为事实并让索引可失效重建更符合现有架构。

### Decision 7: 错误项局部降级，不扩大为修复工具

缺失原图、非法 bbox 和缩略图解码失败只影响对应项，窗口显示占位和原因。缺失、非法或重复 Shape ID 不通过缩略图直接修复；若进入提交预检，继续由现有对象身份规则拒绝不可靠文件。首版不新增 ID 修复、图片恢复或格式规范化入口。

**Alternatives considered:** 打开窗口时自动修改 JSON 补 ID 或修复 bbox。索引与浏览操作必须保持只读，自动修复会违反用户确认前不修改数据的边界，因此不采用。

## Risks / Trade-offs

- **[Risk] 扩展索引字段使现有缓存失效并触发一次全量重建** → 使用 schema version 机制明确重建；JSON 和图片始终不变。
- **[Risk] 大图解码仍可能占用明显 CPU 和瞬时内存** → 每页最多 100、只调度可见项、按图片合并任务并限制线程池并发。
- **[Risk] 页面查询后对象或 bbox 已变化** → 索引只负责候选展示，实际写入始终重新读取 JSON 并按永久 ID 预检。
- **[Risk] 磁盘缓存积累** → 使用独立可删除缓存目录和确定键；后续可在不改变行为契约的情况下接入现有缓存清理策略。
- **[Risk] 写回成功而索引局部刷新失败** → 将索引置为 stale、禁用继续提交并复用刷新/重建恢复路径。
- **[Risk] 提取统一改标协调入口引入现有功能回归** → 保留原 action 行为并用现有对象改标测试加缩略图来源快照测试共同锁定。

## Migration Plan

1. 扩展 SQLite schema、轻量扫描和对象分页查询；通过现有 schema mismatch 路径重建旧缓存。
2. 实现不接写盘的窗口、模型、后台裁剪和两级缓存，验证分页、代次丢弃和资源上限。
3. 提取统一对象改标协调入口，将原跨图标记入口迁移到该入口并先通过现有回归测试。
4. 接入缩略图选择、影响范围确认、结构化结果和 SQLite 局部刷新闭环。
5. 增加菜单入口、翻译资源、状态文案和针对性测试。

回滚时移除新窗口和入口，并将索引 schema 恢复到旧版本后重建派生缓存即可；不需要迁移或恢复任何标注 JSON。已经通过统一事务提交的用户改标仍可使用现有恢复清单恢复。
