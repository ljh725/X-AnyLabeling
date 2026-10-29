# beta4 原始版、xinjiegou 修改版与当前 4.2.1：标注数据加载对比

核查日期：2026-10-29。以三个指定目录当前磁盘上的代码为准。本次仅查代码、Git 历史和本地记录，没有修改应用源码，没有重新进行三个版本的性能对跑。

结论：**原始 beta4 与当前 4.2.1 的目录加载主干几乎相同；xinjiegou 已有专门的首屏加载优化，采用先显示图片、后台发现标签、缓存优先的方式。三者都保留 JSON 为真实标注数据源。**

## 1. 修改版做过什么，为什么这么改

### Git 记录

| 日期 | 提交 | 已核实的修改与目的 |
|---|---|---|
| 2026-05-22 | `476ad1fa` · `2605221500_找到卡顿原因` | 提交说明明确记录：加载图片后自动扫描 EXIF、自动构建 dataset 索引，全量处理标签造成数分钟卡顿；改成手动后，记录称约 1.1 万张图片不再出现同样卡顿。代码同时引入跳过同步 checked 扫描、初次加载跳过 Undo 深拷贝、绘图缓存/裁剪、性能日志等。原提交“4000千个标签”有数量文字歧义，不作为精确基准引用。 |
| 2026-06-10 | `3c13fbce` · `2606101610_修改图片加载方式` | 引入 `LabelCheckWorker`，把路径扫描与标签存在性检查分开；文件名用 `addItems` 批量添加，标签检查和 Inspector 文件列表同步移到后台。此时仍引入应用级模态进度框，后台检查期间会限制操作。 |
| 2026-07-17 | `951ba30a` · `feat: harden dataset index lifecycle and persistence` | 去掉模态进度框，改状态栏进度；已有索引缓存优先挂载，无缓存时只后台检查文件存在，不自动首次全量建索引；增加缓存身份/失效、延迟校验、临时库原子重建与保存解耦。 |

提交说明原文见 [commit_records.txt](D:/X-AnyLabeling-4.2.1/reports/label_loading_comparison_20261029/commit_records.txt)，逐次差异保留为本目录的 `<提交号>_label_widget.diff`。

### 功能记录与讨论记录

- [Pose 加载优化方案](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/docs/pose-100_des_pose标注数据加载优化.md:15)：拆出目录审核扫描、单图 JSON 解析、列表对象构建、Undo 深拷贝和绘制五类成本；明确数据库不是 JSON 主存储的替代品。
- [Pose 加载优化实际改造记录](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/docs/pose-120_impl_pose加载优化代码改造.md:165)：记录跳过 checked 扫描、延迟初始 Undo、关闭自动全量索引、路径/bbox 缓存与视口裁剪。部分说明属于当时版本，最终行为已与当前代码核对。
- [Dataset Filter Index 功能记录](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/docs/Document-Index/feature-records/dataset_filter_index_function_record.md:7)：修改目的是解决数千张图片上逐文件解析 JSON 做筛选的性能问题；SQLite 作为可删除、可重建的派生索引。
- [6 月 10 日讨论记录](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/conversations/20260610-10-10-37-Image-loading-process-in-annot.md:424)：记录了“3.8 万张图片，从确认到显示第一张图片超过 6 分钟”；同一记录后段出现“第一张很快，但进度条很慢”的反馈。其网络时延数字属于当时讨论的分析，不能当作本次复测值。

记录中已能确认的设计动机有两类：**避免不必要的全量任务抢占首屏加载；避免大量文件的逐次读取/存在性检查把界面锁住。** 对跨图筛选，再用索引避免每次重复全量 JSON 解析。

## 2. 原始 beta4 的加载方式

这里的“原始”指 `D:/X-AnyLabeling-4.0.0-beta.4` 这个本地快照。本次没有独立核验它与远端官方发布 tag 的一致性。

1. [更改输出目录](D:/X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_widget.py:5769)重新调用 `import_image_folder(..., load=False)`，随后恢复当前图片选择，触发该图加载。
2. [import_image_folder](D:/X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_widget.py:6207)同步扫描、排序全部图片；`for` 循环为每张图片创建条目，逐条 `addItem`。
3. [_create_file_list_item](D:/X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_widget.py:3502)检查 JSON 是否存在，然后调用 `_label_file_checked`。后者逐个打开 JSON，每次读 8192 字符，正则找到 checked 就停止，没有该字段则读到末尾。
4. 当前图片被打开时，[LabelFile.load](D:/X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_file.py:65)才完整 `json.load` 该图的 JSON，逐个构建 Shape。普通打开目录不是把所有 JSON 的 Shape 全部加载进画布。
5. [load_shapes](D:/X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_widget.py:4484)逐个添加 Shape 条目，期间暂停列表更新、设置 `refresh_filters=False`，最后统一刷新。**这些批量刷新措施原始 beta4 已有。**
6. Canvas 初始化会为当前图片全部 Shape 立即保存 Undo 深拷贝；绘制遍历当前图片的对象。这个快照没有修改版的目录后台标签检查器，也没有 SQLite 数据集索引。

## 3. 原始 beta4 与当前 4.2.1

直接提取对应函数比较，见 [原始 beta4 对 4.2.1 的函数差异](D:/X-AnyLabeling-4.2.1/reports/label_loading_comparison_20261029/original_beta4_vs_current_421.diff)。

| 维度 | 原始 beta4 | 当前工作区 4.2.1 |
|---|---|---|
| 更改输出目录 | 重建文件列表，再恢复当前图片 | 相同主干 |
| 目录扫描、条目插入 | 同步扫描，循环中逐条添加 | 相同主干；新增共享视图状态清理、导航状态更新 |
| 全目录审核状态 | 同步逐个打开 JSON，分块正则读取 | 相同方式；审核值扩展为未审核、通过、不通过 |
| 全目录 SQLite 缓存 | 没有 | 当前工作区没有 |
| 单张标注加载 | 完整解析当前图 JSON，构建全部 Shape | 相同主干，增加持久对象 ID 规范化等兼容处理 |
| 单图 Shape 列表 | 暂停列表更新，循环创建条目，最后统一筛选 | 同样已有这些措施；并非 4.2.1 才从逐次刷新改成批量 |
| 初始 Undo | 立即深拷贝当前图的全部 Shape | 仍然立即深拷贝 |
| 图片尺寸检查 | 图片字节再编码 Base64，解码成像素数组取宽高 | 直接从图片字节读取 PIL 尺寸，避免该次全像素数组转换 |
| 几何路径、边界缓存 | 每次构建路径/边界 | `make_path`/`bounding_rect` 仍是即时构建，没有修改版的通用几何缓存 |
| 按文件类别等属性搜索 | 逐文件完整解析 JSON 再匹配 | 仍是该方式，扩展了筛选条件 |

`import_image_folder` 的函数差异仅是共享视图清理注释/调用和导航状态更新；`_create_file_list_item` 的函数差异仅新增 tooltip。其调用的审核读取函数在 4.2.1 增加了 failed 状态，但未变成后台读取。

这说明“版本号从 beta4 升到 4.2.1”不代表目录加载已切换成修改版那套架构。4.2.1 还有其他画布、状态和兼容改进，不能把此处目录主干相近外推成两个版本整体相同。

## 4. xinjiegou 与当前 4.2.1

| 维度 | xinjiegou 当前代码 | 当前工作区 4.2.1 |
|---|---|---|
| 首屏原则 | 先路径列表和当前图；标签信息随后补齐 | 目录审核扫描完成后，继续当前图加载 |
| 文件列表插入 | 一次 `addItems(image_files)`；仍循环初始化默认状态 | 循环 `_create_file_list_item`、`addItem` |
| 没有索引缓存 | 非模态 QThread 检查 JSON 存在性，500 条一批回传 | 在界面线程逐个检查并读取审核字段 |
| 有兼容缓存 | 从 SQLite 恢复标签存在性；默认约 1.5 秒后后台刷新验证 | 无该缓存路径 |
| 首次索引 | 没缓存时不自动首次全量建索引，按需刷新/重建 | 无全局索引 |
| EXIF | 提供手动扫描入口，不在导入目录末尾自动启动 | 配置开启时自动后台扫描 |
| 当前图片真实标注 | 仍完整读该图 JSON，JSON 保持权威 | 同样完整读该图 JSON |
| 单图初始 Undo | `store_backup=False`，首次编辑前补快照 | 初始加载立即深拷贝 |
| 绘制 | 有视口相交判断、Shape 路径和 bbox 缓存 | 没有同一套通用路径/bbox 缓存及绘制前视口裁剪 |
| 跨图筛选导航 | 使用派生索引；索引未就绪时提示，避免悄悄全量扫 JSON | 原生文件属性搜索仍逐文件解析 |

关键代码：[修改版目录入口](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_widget.py:11344)、[后台标签检查器](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_widget.py:268)、[缓存状态回填](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_widget.py:6231)、[初始加载不存 Undo](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/label_widget.py:9754)、[Shape 几何缓存](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/anylabeling/views/labeling/shape.py:828)。

**语义差别不能忽略**：修改版后台 `LabelCheckWorker` 只检查 JSON 是否存在，不完整读取所有文件的审核值。索引 `files` 表也没有 checked 字段，缓存回填主要恢复“有无标注”，不是所有文件的审核状态；当前图片加载后才校正该图的审核状态。原始/4.2.1 的同步读取则会初始化全列表审核状态，且 4.2.1 支持 failed 三态。因此迁移首屏优化时，要设计待加载状态与后台审核补齐，不能简单把全部条目标成未审核。

三者都仍有 `for`。差别是 **循环里做不做逐文件 IO、IO 在哪个线程、首图要不要等全目录完成**，而不是“是否使用循环”。修改版也并非把当前图的全部 Shape 从 SQLite 加载出来。

## 5. 迁移到 4.2.1 时为什么没保留索引

[索引迁移说明](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/migration/dataset-index-4.2.1_README.md:3)明确记载：曾迁移 SQLite 索引和后台生命周期，但用户决定不迁移目标缩略图与跨图复查；没有保留功能查询该索引，因此撤回索引切片。[迁移任务清单](D:/xinjiegou-X-AnyLabeling-4.0.0-beta.4/migration/4.2.1迁移任务清单.md:86)有同样说明。

这是文档记录的功能范围决策。它不意味着目录同步扫描已经完成性能优化。**目录首屏优化和全功能 SQLite 索引是可以分开处理的两件事。** 当前性能需求可以先只评估“首屏不读全目录审核 + 后台补齐 + 列表批量构建”，再决定是否需要完整索引，尊重既有迁移范围。

## 6. 证据边界与补充发现

- 修改版 `label_widget.py` 与 `canvas.py` 当前有未提交变更，故本次以磁盘文件说明现状，用 Git 提交追溯来源，未把 HEAD 当作全部当前代码。
- 部分作品集文字把模态 Loading Labels 称作 upstream 行为；但本次指定的原始 beta4 目录没有 LabelCheckWorker，Git diff 显示该类及模态对话框在个人分支 3c13fbce 中加入，随后在 951ba30a 移除模态。因此本文没有沿用该模糊归因。
- 索引早期文档写 schema 2，当前代码为 schema 4；关于完整审核状态缓存的 Phase 2 设想不能当作已落地代码。
- 之前真实 PRW 数据实测的 **4.97 秒首图显示、7.4 毫秒重绘**仅属于当前 4.2.1，不用于证明原始 beta4 或修改版各自的实际耗时。此前提出的后台/缓存方向在修改版中已有实现基础，后续应优先评估已有实现的复用与兼容，而不是把它当成全新设计。
- 本目录 `source_evidence.json` 保留三份源码 SHA256、关键函数原文/行号和 Git 记录；本次只在 4.2.1 的 reports 目录写入分析产物，未改三个版本源码或用户数据。
