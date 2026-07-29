# 数据集筛选索引设计

## 背景

当前筛选显示与筛选结果导航功能已经能在单张图片与当前会话层面工作，但在 5000 张图片、约 18000 个 shape 的数据规模下，若每次开启筛选或刷新都全量遍历 JSON，会产生明显的等待时间。

你的使用场景是：

1. 以浏览筛选为主。
2. 会频繁修改少量标签。
3. 数据目录是 YOLO 风格，图片与 JSON 分离，且为单层结构。
4. 外部脚本也可能批量修改 JSON，之后再重新打开软件。
5. 希望筛选像 SQL 查询一样快。

因此需要将“每次全量扫描 JSON”升级为“基于派生索引查询 + 手动刷新 + 增量更新 + 持久缓存”的架构。

本文中的 SQLite 只作为可丢弃、可重建的索引缓存，不作为主标注格式。JSON 仍然是唯一真实数据源。

## 目标

1. 首次加载后建立数据集索引。
2. 后续筛选直接查索引，不再全量扫 JSON。
3. 支持外部脚本改动后，在用户手动刷新或重新打开目录时更新索引。
4. 支持软件内部编辑后的单文件增量更新。
5. 保持原有 `FilterState`、`ShapeFilterEngine`、`FilterNavigationEngine` 的职责边界。
6. 保持 JSON 标注文件作为唯一真实数据源。

## 非目标

1. 不做实时文件系统监听。
2. 不在软件运行中主动猜测外部脚本的持续写入状态。
3. 不强制所有查询都落库到数据库服务。
4. 不先做复杂的跨进程同步。
5. 不改变现有标注文件格式。
6. 不把 SQLite 作为主标注数据库。
7. 不通过 SQLite 回写标注内容。
8. 不要求外部脚本读写 SQLite。

## 设计原则

1. **一次建索引，多次查询**。
2. **用户主动刷新才重新校验外部文件变化**。
3. **内部编辑时仅增量更新当前文件索引**。
4. **查询层不访问 Qt UI 控件**。
5. **索引层不承担 UI 状态同步职责**。
6. **SQLite 缓存可随时删除并从 JSON 重建**。

## 数据真源与缓存边界

### JSON

JSON 是唯一真实数据源：

1. 保存完整标注数据。
2. 由 `LabelFile.load()` / `LabelFile.save()` 读写。
3. 外部脚本可以直接读取和修改。
4. 训练导出、人工检查、版本管理都以 JSON 为准。
5. 打开图片时仍然从 JSON 加载完整标注。

### SQLite

SQLite 只是 JSON 派生出来的索引缓存：

1. 保存文件级元数据和轻量 shape 查询字段。
2. 用于快速筛选、导航、统计。
3. 不保存不可从 JSON 恢复的信息。
4. 不作为标注编辑入口。
5. 不直接决定标注内容。
6. 缓存丢失、损坏或 schema 版本不匹配时，直接重建。

推荐边界：

```text
JSON files
  | LabelFile.load/save
  v
Labeling UI / Canvas

JSON files
  | scan / refresh_file
  v
DatasetFilterIndex
  | writes derived cache
  v
SQLite index cache
  | fast query(FilterState)
  v
FilterNavigationEngine
```

## 架构分层

建议拆成四层：

```text
FilterState
  保存筛选条件

DatasetFilterIndex
  保存全数据集的倒排索引 / SQLite 派生缓存

ShapeFilterEngine
  当前图片内筛选与可见性同步

FilterNavigationEngine
  基于索引结果进行筛选结果导航
```

### 职责说明

| 层 | 职责 | 不应该做 |
|----|------|----------|
| FilterState | 保存筛选条件快照 | 访问 UI、访问文件系统 |
| DatasetFilterIndex | 建立与查询数据集索引、管理 SQLite 派生缓存 | 操作 QWidget、决定显示方式、回写标注内容 |
| ShapeFilterEngine | 当前图可见性同步、局部 apply | 全量扫描全数据集 |
| FilterNavigationEngine | 处理筛选结果文件集合、前后跳转 | 全量重建索引 |

## 数据规模假设

基于当前描述：

```text
图片数量：约 5000
每图 shape 数：平均约 7
shape_type：2~3 类
gid：与 shape 数量接近
数据结构：单层目录，图片与 JSON 分离
```

该规模适合做内存索引 + 持久缓存，而不是每次查询都重扫 JSON。

## 关键问题

当前慢点是：

```text
开启筛选显示 / 筛选结果导航
  -> 遍历全量 JSON
  -> 找到命中的 shape / 文件
  -> 才能更新 UI
```

这导致每次开关功能都要做一次全量重计算。

正确方向是：

```text
首次扫描建立索引
之后查询索引
变化文件单独重建
```

## 索引内容

建议为每个 JSON 记录两类信息：

### 1. 文件级元数据

```text
path
mtime
size
shape_count
label_count
gid_count
shape_type_count
```

### 2. 倒排索引

至少维护以下集合：

```python
label_index: Dict[str, Set[str]]
gid_index: Dict[str, Set[str]]
shape_type_index: Dict[str, Set[str]]
```

如果未来需要 shape 级聚合，可升级为：

```python
label_index: Dict[str, Dict[str, Set[int]]]
gid_index: Dict[str, Dict[str, Set[int]]]
shape_type_index: Dict[str, Dict[str, Set[int]]]
```

其中：

```text
外层 key = label/gid/type
内层 key = 文件路径
value = 该文件命中的 shape id 集合
```

## 查询语义

保持当前 `FilterState` 语义：

```text
label 集合内部 OR
label / gid / shape_type 之间 AND
一个文件任意 shape 命中即文件命中
```

索引查询示例：

```text
label=person,car
  -> label_index[person] ∪ label_index[car]

label=person AND gid=1 AND type=rectangle
  -> label_set ∩ gid_set ∩ type_set
```

## 缓存策略

### 派生索引缓存目标

避免每次打开目录都全量重建。

### 派生索引缓存内容

建议只持久化可从 JSON 恢复的信息：

```text
dataset_root
file manifest
每个文件的 mtime / size / shape_count
label/gid/shape_type 索引
```

### 派生索引缓存格式建议

优先：

```text
SQLite
```

备选：

```text
JSON cache
```

### SQLite 表建议

只缓存筛选查询必要字段。

```text
files:
- id
- image_path
- json_path
- json_mtime
- json_size
- shape_count
- indexed_at

shapes:
- id
- file_id
- shape_index
- label
- group_id
- shape_type
```

第一版不缓存：

```text
points
imageData
flags 全量
attributes 全量
description 全量
完整 JSON
图片像素
```

除非后续确实需要对应查询，否则不扩大缓存字段。

### 缓存失效判定

采用轻量方案：

```text
path 新增 -> 重建
path 删除 -> 移除缓存
mtime 变了 -> 重建
size 变了 -> 重建
mtime / size 都没变 -> 复用缓存
```

## 刷新策略

你已确认选择的是：

```text
不主动监听外部变化
只在手动刷新或重新打开目录时刷新索引
```

因此提供两个动作：

```text
刷新索引
重建索引
```

### 刷新索引

```text
读取缓存
检查文件清单与 mtime / size
仅重建变化文件
保留未变文件的索引
```

### 重建索引

```text
忽略或删除现有 SQLite 缓存
全量扫描所有 JSON
重新生成索引与 SQLite 派生缓存
```

### 打开目录

```text
1. 找到 JSON 文件清单。
2. 对比 SQLite 中的 json_path + json_mtime + json_size。
3. 未变化文件复用缓存。
4. 新增/变化文件重新解析 JSON 并更新索引。
5. 删除文件移除缓存记录。
```

### 保存当前标注

```text
1. `LabelFile.save()` 正常写 JSON。
2. 保存成功后调用 `refresh_file(json_path)`。
3. 只重建当前 JSON 的索引记录。
```

## 增量更新

当用户在软件内部修改少量标签时，不应全量重扫。

建议接口：

```python
def refresh_file(self, image_path, output_dir=None):
    """Rebuild derived index for a single JSON file."""
```

流程：

```text
1. 读取该文件对应 JSON
2. 移除旧索引记录
3. 写入新索引记录
4. 更新 mtime / size / shape_count
```

这适合你的工作流：

```text
筛选 -> 进入命中文件 -> 改 1~2 个标签 -> 保存 -> 只更新当前文件索引
```

## 与现有功能的关系

### 与 `FilterState`

`FilterState` 不变，仍然是权威筛选条件快照。

### 与 `ShapeFilterEngine`

当前图对象可见性同步仍由它负责。

但它不应再承担全数据集扫描职责。

### 与 `FilterNavigationEngine`

筛选结果导航不应自己重扫整个目录，而应消费 `DatasetFilterIndex` 的查询结果。

`DatasetFilterIndex.query()` 只返回命中的 `image_path` / `json_path` 集合。真正打开图片时仍通过 `LabelFile` 从 JSON 加载完整标注。

### 与文件列表 / UI

UI 只负责：

```text
显示结果
触发启用 / 刷新 / 关闭
响应导航
```

不负责全量扫描。

## 推荐模块拆分

建议新增：

```text
anylabeling/views/labeling/dataset_filter_index.py
```

职责：

1. 扫描 JSON。
2. 建索引。
3. 从 SQLite 派生缓存加载索引。
4. 刷新单文件。
5. 执行筛选查询。

### 可能的类接口

```python
class DatasetFilterIndex:
    def load_or_build(self, root_dir, output_dir=None): ...
    def rebuild(self, root_dir, output_dir=None): ...
    def refresh_file(self, image_path, output_dir=None): ...
    def query(self, filter_state): ...
```

`DatasetFilterIndex` 不接管 `LabelFile.load()` / `LabelFile.save()`，也不把 SQLite 作为标注编辑入口。

### 返回值建议

```python
class DatasetFilterQueryResult:
    matched_files: list[str]
    matched_count: int
    total_files: int
```

## 后台构建

首次加载允许耗时，但应尽量做到“无感”。

建议：

```text
打开目录
  -> UI 立即可用
  -> 后台线程构建索引
  -> 状态栏提示索引构建中
  -> 构建完成后启用高频查询
```

如果你不希望初版异步，可先同步实现，但最终目标应是后台化。

## UI 入口建议

建议在 `View` 菜单与工具栏提供：

```text
Refresh Dataset Index
Rebuild Dataset Index
Filter Result Navigation
```

其中：

```text
Filter Result Navigation = 可勾选开关
Refresh Dataset Index = 普通动作
Rebuild Dataset Index = 普通动作
```

避免使用容易误导的文案：

```text
Refresh Database
Save to Database
Use SQLite Annotation
```

## 性能目标

你希望达到类似 SQL 查询的体验。

目标定义为：

1. 普通筛选查询只做索引集合运算。
2. 当前文件修改只更新当前文件索引。
3. 外部脚本修改后，在手动刷新时只处理变化文件。

理想情况下：

```text
查询速度 ≈ O(命中集合运算)
而不是 O(全部 JSON 扫描)
```

## 风险点

1. 如果继续全量扫描，5000 张图仍会明显慢。
2. 如果 UI 线程直接建索引，会卡顿。
3. 如果缓存失效判断只看 path，不看 mtime / size，会出现脏索引。
4. 如果软件内部保存后不刷新当前文件索引，会导致结果不一致。
5. 如果把 SQLite 当成主标注库，会破坏现有 JSON 工作流和外部脚本兼容性。

## 错误处理

### SQLite 打不开

```text
1. 记录 warning。
2. 忽略或删除旧缓存。
3. 从 JSON 重建索引。
```

### SQLite schema 版本不匹配

```text
1. 忽略旧缓存。
2. 删除并重建 SQLite 索引缓存。
```

### 单个 JSON 损坏

```text
1. 跳过该文件。
2. 记录失败列表。
3. UI 可提示部分文件索引失败。
4. 不影响其他文件查询。
```

## 代码落地顺序

### Phase 1

1. 新增 `DatasetFilterIndex`。
2. 实现 SQLite 派生缓存 schema。
3. 实现 JSON 到 SQLite 索引构建。
4. 实现 `mtime + size` 增量校验。
5. 实现 `query(FilterState)` 返回命中文件集合。
6. 支持单文件 `refresh_file()`。
7. 不接管 `LabelFile.load()` / `LabelFile.save()`。

### Phase 2

1. `LabelingWidget` 接入索引查询。
2. 筛选结果导航消费索引结果。
3. 保存当前文件后刷新当前 JSON 的索引。

### Phase 3

1. 后台线程索引构建。
2. 状态栏显示索引状态。
3. UI 添加 `Refresh Dataset Index` / `Rebuild Dataset Index`。
4. 进度与取消。
5. 更细粒度 shape 级缓存。

## 验收标准

1. 打开目录后不再每次开关筛选都全量重扫。
2. 首次加载后再次查询明显更快。
3. 当前文件修改后，索引可局部更新。
4. 外部脚本改动后，手动刷新/重新打开目录可识别变化。
5. 筛选结果导航仍保持原有交互。
6. 原始文件列表操作不受影响。
7. 删除 SQLite 缓存后，可以从 JSON 完整重建索引。
8. 标注读写仍以 JSON 为准。
