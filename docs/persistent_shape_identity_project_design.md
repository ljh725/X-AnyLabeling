# X-AnyLabeling Shape 持久唯一身份项目说明

## 1. 文档信息

| 项目 | 内容 |
|---|---|
| 能力名称 | Persistent Shape Identity |
| JSON 字段 | `xanylabeling_shape_id` |
| OpenSpec 变更 | `harden-persistent-shape-identity` |
| OpenSpec schema | `spec-driven` |
| 状态 | 已实现、已验证、已归档 |
| 归档目录 | `openspec/changes/archive/2026-08-26-harden-persistent-shape-identity/` |
| 主要作用 | 为每个正式 Shape 提供跨编辑、保存、重载和下游流程稳定的对象身份 |

本文描述最终落地状态。它不仅解释字段如何生成和写入，还规定下游模块应如何
使用该身份管理对象，以及哪些临时编号不得被当成持久主键。

## 2. 为什么必须给 Shape 增加唯一身份

过去，一个 Shape 通常只能通过以下信息被间接识别：

- 它在 JSON `shapes` 数组中的下标；
- 当前 Python `Shape` 对象的内存地址；
- `group_id`；
- 标签、几何坐标或这些字段计算出的指纹；
- 质检阶段临时生成的 QA 编号。

这些信息都不能承担稳定对象身份：

1. 数组下标会因为插入、删除、排序和合并发生变化。
2. Python 对象地址只在单次进程内有效，重新加载后必然变化。
3. `group_id` 表达业务分组，一个组可以包含 person、head、face 和关键点，不能
   唯一标识其中某一个 Shape。
4. 标签和几何是可编辑数据，修改标签、移动顶点后不应被识别成另一个对象。
5. QA 编号只服务一次扫描或匹配过程，不属于正式标注数据。

因此系统需要一个与业务字段和几何字段分离、写入正式 JSON、在对象生命周期内
保持稳定的专用身份字段。这就是 `xanylabeling_shape_id`。

## 3. JSON 结构变更

### 3.1 字段位置与示例

`xanylabeling_shape_id` 是每个 Shape 对象的顶层字段，并固定序列化为 Shape 的
第一个键：

```json
{
  "shapes": [
    {
      "xanylabeling_shape_id": "f75397a98f734b4396454deacafbc05f",
      "label": "listening",
      "score": null,
      "points": [
        [631.95168, 335.7315],
        [811.22016, 335.7315],
        [811.22016, 597.92634],
        [631.95168, 597.92634]
      ],
      "group_id": null,
      "description": "",
      "difficult": false,
      "shape_type": "rectangle",
      "flags": {},
      "attributes": {},
      "kie_linking": []
    }
  ]
}
```

JSON 对象在标准语义上不依赖键顺序，但固定把身份放在第一个位置有三项工程价值：

- 人工检查文件时可以第一眼看到对象身份；
- 手工编辑保存与项目批量迁移产生一致的结构；
- 版本 diff 更稳定，避免同一字段在不同写入入口中一会在开头、一会在末尾。

### 3.2 身份迁移不负责补齐其他字段

项目批量身份工具只处理 `xanylabeling_shape_id`。对于下面这种历史稀疏 Shape：

```json
{
  "label": "reading",
  "points": [[196.8659, 267.1839], [359.1245, 428.4696]],
  "shape_type": "rectangle",
  "flags": {}
}
```

迁移后的结果是：

```json
{
  "xanylabeling_shape_id": "10c0ddb29b25457dbe64c3271a4828c6",
  "label": "reading",
  "points": [[196.8659, 267.1839], [359.1245, 428.4696]],
  "shape_type": "rectangle",
  "flags": {}
}
```

迁移不会顺便增加 `score`、`group_id`、`description`、`difficult`、`attributes`
或 `kie_linking`，也不会改变两点矩形、四点矩形或其他几何表达。字段补全属于独立
的数据结构标准化任务，不能与身份迁移混在一起。

### 3.3 支持的 Shape 类型

身份属于通用 Shape，不是矩形专用能力。以下正式标注对象统一使用同一字段：

- point / 关键点；
- line 和 linestrip；
- polygon；
- rectangle；
- rotation；
- circle；
- quadrilateral；
- cuboid；
- 手工标注、AI 生成和插件导入后进入正式 Canvas 的其他 Shape。

## 4. 身份格式、作用域和完整对象键

### 4.1 新身份格式

系统新生成的 ID 使用：

```python
uuid.uuid4().hex
```

输出是 32 个小写十六进制字符，不包含连字符。例如：

```text
f75397a98f734b4396454deacafbc05f
```

32 个十六进制字符不等于 32 bit。UUID4 名义长度为 128 bit，其中版本和变体占用
固定比特，实际随机空间约为 `2^122`。

对于 100,000 个 Shape，至少出现一次随机碰撞的近似概率为：

```text
p ≈ n(n-1) / (2 × 2^122) ≈ 9.4 × 10^-28
```

生成器仍会检查候选值是否已被占用；发生碰撞时重新生成，最多尝试 1024 次。
这个上限主要防御损坏或被测试替换的生成器，而不是因为正常 UUID4 容易碰撞。

### 4.2 可验证作用域

系统直接保证的是：

> 同一个 X-AnyLabeling JSON 文件内，每个正式 Shape 的 ID 非空且唯一。

UUID4 在实践中接近全局唯一，但本地桌面应用无法枚举和验证世界上所有离线项目，
因此下游跨文件管理对象时使用完整对象键：

```text
(project_id, image_id, xanylabeling_shape_id)
```

其中：

- `project_id` 区分项目或数据集；
- `image_id` 区分图片/标注文件；
- `xanylabeling_shape_id` 区分该图片中的具体 Shape。

任何跨文件数据库、行为日志、复核 sidecar 或缓存都不应只依赖数组下标。

### 4.3 历史 ID 兼容

加载历史数据时，任意非空字符串都视为可保留身份，不强制历史值必须符合 UUID
格式。这样可以兼容旧脚本、实验版本或外部工具已经写入的字符串 ID。

只有以下情况会生成替代 ID：

- 字段缺失；
- 值不是字符串；
- 值为空字符串；
- 同一文件内后续 Shape 重复使用前面已经声明的 ID。

## 5. 身份不变量与集合规范化算法

单个 `Shape` 构造器只能保证自己有 ID，无法判断同文件中是否存在重复。因此唯一性
治理必须在集合边界完成。

规范化算法按 Shape 数组顺序运行，时间复杂度和空间复杂度均为 O(n)：

1. 收集当前集合及保留集合中所有已声明的非空字符串 ID。
2. 顺序遍历每个 Shape。
3. 首次出现的合法非空字符串原样保留。
4. 对缺失、非法或后续重复项生成 UUID4 hex。
5. 生成候选必须不在不可用集合中；碰撞则重试。
6. 返回规范化后的有序 ID 列表和结构化诊断。

结构化诊断区分：

| reason | 含义 | 处理 |
|---|---|---|
| `missing` | Shape 没有身份字段 | 生成新 ID |
| `invalid` | 值为空或不是字符串 | 生成新 ID |
| `duplicate` | ID 已被前面的 Shape 占用 | 保留首次出现者，后续项生成新 ID |

生成新 ID 时会预先保护所有历史有效 ID，避免为前面的缺失项随机生成一个与后面
历史 Shape 相同的 ID，从而错误夺走后面对象原有身份。

## 6. Shape 生命周期规则

核心原则是：

> 恢复同一个对象时保留 ID；产生独立新对象时生成新 ID。

| 生命周期入口 | 对象语义 | ID 行为 |
|---|---|---|
| 手工绘制 | 新对象 | 生成新 ID |
| AI 模型生成正式标注 | 新对象 | 生成新 ID |
| 修改标签、描述、属性或几何 | 同一对象编辑 | 保留 ID |
| 保存并重新加载 | 同一持久对象 | 保留 ID |
| 撤销/重做编辑 | 状态快照恢复 | 保留 ID |
| 删除后撤销 | 恢复被删除对象 | 保留 ID |
| Duplicate | 新对象 | 生成新 ID |
| 内部剪贴板粘贴 | 新对象 | 生成新 ID |
| 系统剪贴板粘贴 | 新对象 | 生成新 ID |
| Union/合并产生结果 | 新对象 | 生成新 ID |
| 跨图片批量复制 | 目标文件中的新对象 | 生成新 ID并避开目标文件现有 ID |
| 导入为新对象 | 新对象 | 不直接信任来源对象身份 |
| Canvas 撤销备份 | 临时状态副本 | 保留 ID |
| 绘制预览、几何比较副本 | 瞬时对象 | 可以临时保留，但不得作为新对象持久化 |

代码通过两个显式复制接口表达语义：

- `Shape.copy()`：状态快照，保留身份；
- `Shape.copy_for_new_object()`：独立新对象，生成身份。

不能把所有 `deepcopy` 都自动改成新 ID，否则撤销、重做和删除恢复会错误地把同一个
对象变成新对象。

## 7. 加载、保存和惰性迁移

### 7.1 加载旧 JSON

`LabelFile.load()` 在 Shape 对 UI 和下游模块可见之前执行集合规范化。加载时可能
出现如下日志：

```text
Repaired 20 Shape identities while loading ...:
shape[0] missing id -> ...;
shape[1] missing id -> ...
```

这不是加载失败，而是迁移诊断，表示旧 JSON 中有 Shape 缺少或冲突的身份。此时：

- 内存中的 Shape 已经获得非空、唯一 ID；
- 原 JSON 不会因为“仅打开文件”而被立即写回；
- 文件不会仅因惰性补 ID 被标记为用户已修改；
- 如果退出且没有保存，下次加载可能再次生成不同 ID；
- 用户正常保存或执行项目批量迁移后，身份才会稳定写入磁盘。

### 7.2 正常保存

手工编辑保存时，`Shape.to_dict()` 将 ID 作为第一个字段输出。`LabelFile.save()`
在创建临时文件前执行只读身份预检：

- 所有 ID 必须是非空字符串；
- 同一文件内不能重复；
- 失败信息包含 Shape 数组位置和冲突 ID；
- 保存阶段不静默换 ID，因为下游可能已经引用当前内存身份。

写盘采用同目录临时文件、flush、`fsync` 和 `os.replace`。验证或写入失败不会覆盖
已有目标文件，也会清理遗留临时文件。

## 8. 项目级手动迁移

### 8.1 UI 功能

菜单入口：

```text
Tool → Assign Shape IDs to Project
```

该功能用于一次性治理旧项目：

1. 递归扫描当前项目目录和单独配置的标注输出目录。
2. 跳过没有 `shapes` 数组的非标注 JSON。
3. 保留合法历史 ID。
4. 补充缺失/非法 ID并修复同文件重复。
5. 把 `xanylabeling_shape_id` 移动到每个 Shape 的第一个键。
6. 只有确实发生身份或顺序变化的文件才会写入。
7. 每个文件独立原子替换，一个损坏文件不会回滚其他成功文件。
8. 最终报告扫描文件数、修改文件数、分配 ID 数和失败文件数。

目录扫描、JSON 读取和写入在 `QThread` 中完成，不阻塞主界面。进度信号按约 1%
节流，避免超大项目产生数万条 UI 更新。切换项目或关闭窗口时会请求取消，并在当前
文件操作完成后安全回收线程。

### 8.2 命令行脚本

现有项目也可以使用：

```powershell
& 'C:\Users\20441\.conda\envs\x-anylabeling-cu12\python.exe' `
  scripts\ensure_shape_identity_order.py `
  --input 'D:\dataset\project-or-json'
```

脚本复用与 UI 相同的身份逻辑。它不会补齐其他 Shape 字段，不会更改标签、坐标、
属性值或几何表达。

### 8.3 操作建议

- 大批量迁移前保留数据集快照或版本控制记录。
- 网络共享目录允许操作较慢，但界面应保持响应。
- 不要同时用两个进程迁移同一批 JSON。
- 迁移完成后抽查 ID 位于第一个键、文件内无重复、下游报告可正确关联对象。
- 对失败文件单独检查权限、JSON 语法和 `shapes` 字段类型。

## 9. 下游对象管理契约

唯一 ID 的价值不止是 JSON 多了一个字段。它建立了正式对象管理边界。

### 9.1 身份层级

| 身份 | 生命周期 | 能否写入持久下游数据 | 用途 |
|---|---|---|---|
| `xanylabeling_shape_id` | Shape 持久生命周期 | 可以 | 同一图片中的正式对象身份 |
| `(project_id, image_id, shape_id)` | 跨文件/跨会话 | 应当 | 完整对象键 |
| `group_id` | 业务分组 | 可以，但不是对象主键 | person/head/face/关键点分组 |
| `shape_index` | 当前数组/当前扫描 | 仅作导航提示 | 当前文件定位 |
| Python 对象地址 | 单次进程 | 不可以 | 运行时缓存、命中测试 |
| QA entity ID | 一次质检扫描 | 仅写 QA 输出 | 临时匹配和证据 |
| object episode ID | 一段行为过程 | 可以写行为日志 | 一次选中/操作片段，不替代 Shape ID |

### 9.2 行为分析

用户选择、修改、保存或复核某个 Shape 时，行为事件使用持久 Shape ID，并与项目和
图片身份共同构成对象上下文。数组重排或应用重启后，针对同一 Shape 的事件仍可以
聚合。`object_episode_id` 继续表达一次操作片段，两者不能混用。

### 9.3 L1/L2 质检和人工复核

质检加载器把 `xanylabeling_shape_id` 读入 `QcShape.shape_id`，问题记录写入：

- `report.json`；
- `review.tsv`；
- `review_feedback.tsv`；
- Inspector 质检复核队列。

问题身份优先使用持久 Shape ID，而不是数组位置。因此在 JSON 中插入另一个 Shape
导致目标 Shape 从 `shape[0]` 移到 `shape[1]` 时，复核问题仍能关联原对象。
`shape_index` 保留用于当前文件导航，但不能作为跨复扫主键。

### 9.4 虚拟复核

虚拟复核运行时 Shape map 优先使用持久 ID。对于测试对象或确实没有正式身份的瞬时
对象，允许使用明确命名的 runtime fallback，但 fallback 不得被写成跨生命周期对象
引用。跨文件 sidecar 需要结合项目、图片和成员定位信息做保守重绑定。

### 9.5 Inspector 和 Canvas

Inspector 的一次性扫描、Canvas 渲染顺序、命中测试和布局算法仍可使用下标或对象
地址，因为这些逻辑只服务当前内存状态。判断标准不是“能不能使用下标”，而是：

> 只要引用需要跨编辑、保存、重载、复扫或应用重启存在，就必须升级为持久 Shape
> ID或包含它的完整对象键。

## 10. 与业务字段的边界

`xanylabeling_shape_id` 只表达“这是哪个 Shape”，不表达：

- Shape 属于哪个人或哪个业务组；
- Shape 的类别；
- Shape 是否困难样本；
- Shape 的属性、flags 或 KIE 关系；
- Shape 当前位于什么坐标；
- Shape 是否通过质检。

修改以下字段不会改变身份：

```text
label, points, group_id, description, difficult,
flags, attributes, kie_linking
```

同理，身份迁移也不得覆盖这些字段。未知扩展字段必须原样保留。

## 11. 外部交换格式边界

`xanylabeling_shape_id` 是 X-AnyLabeling 私有字段。VOC、YOLO、COCO、DOTA 等没有
对应身份扩展契约的格式采用公共字段白名单：

- 不导出私有 ID；
- 不为了导出临时删除源 JSON 字段；
- 不修改源 JSON；
- 不承诺外部格式往返后恢复原 Shape 身份；
- 重新导入为独立新对象时应生成新身份。

如果未来某种交换格式需要保留身份，应设计显式扩展字段和版本契约，不能把私有键
偷偷塞进不支持的格式。

## 12. 兼容性和失败治理

### 12.1 向后兼容

旧版读取器通常会忽略未知 JSON 字段，因此增加顶层 Shape 私有字段属于增量兼容
变更。当前读取器也继续接受没有 ID 的旧文件，并在内存中惰性迁移。

### 12.2 损坏或重复身份

重复输入本身存在所有权歧义。系统采用确定规则：

- 按数组顺序保留首个有效出现者；
- 后续重复项生成新 ID；
- 日志记录原 ID、冲突位置、首次位置和替代 ID。

系统不能推断两个重复 Shape 中谁“更应该”拥有原 ID，因此不使用标签或几何做猜测。

### 12.3 并发限制

单文件写入是原子的，但两个独立进程同时修改同一 JSON 仍可能出现最后写入者覆盖
前一写入者的情况。项目批量迁移不承担分布式锁服务；操作期间应避免其他程序同时
批量写同一标注目录。

## 13. 核心代码地图

| 文件 | 职责 |
|---|---|
| `anylabeling/views/labeling/shape_identity.py` | UUID 生成、集合规范化、只读验证、诊断 |
| `anylabeling/views/labeling/shape.py` | Shape 字段、序列化、反序列化、复制语义 |
| `anylabeling/views/labeling/label_file.py` | 加载规范化、保存预检、原子写入 |
| `anylabeling/views/labeling/shape_identity_project.py` | 项目 JSON 扫描、身份修复、ID 首键和原子迁移 |
| `anylabeling/views/labeling/shape_identity_worker.py` | 后台扫描、节流进度、取消和线程生命周期 |
| `anylabeling/views/labeling/label_widget.py` | 工具菜单入口、确认、状态和结果反馈 |
| `scripts/ensure_shape_identity_order.py` | 命令行项目迁移 |
| `widgets/inspector/quality/quality_issue.py` | 质检 Shape/Issue 持久身份 |
| `widgets/inspector/quality/report_writer.py` | report/review 输出身份 |
| `widgets/inspector/quality/feedback.py` | 人工反馈身份字段 |
| `widgets/inspector/quality/quality_review_queue.py` | 复扫与反馈队列的稳定对象关联 |
| `widgets/inspector/virtual_review_controller.py` | 虚拟复核持久 ID map 与 runtime fallback |

## 14. 验收标准

最终能力至少满足以下验收条件：

1. 所有正式 Shape 类型创建后都有非空 ID。
2. 同一文件中所有 Shape ID 唯一。
3. 旧文件缺失、非法和重复 ID 能在加载边界得到诊断和修复。
4. 仅加载旧文件不会自动写盘或标记 dirty。
5. 正常保存—重载后 ID 稳定。
6. 编辑、撤销、重做和删除后撤销保留 ID。
7. Duplicate、粘贴、合并和导入新对象生成新 ID。
8. 保存前发现歧义身份时拒绝写出，并保持原子保存语义。
9. 项目批量迁移不补齐其他 Shape 字段、不修改几何和业务值。
10. `xanylabeling_shape_id` 在手工保存、批量迁移和脚本输出中均为第一个键。
11. 大型项目迁移在后台线程运行，不阻塞主界面。
12. 行为事件和持久复核输出不使用数组下标或对象地址作为跨生命周期主键。
13. VOC、YOLO 和 COCO 输出不包含私有 ID，且转换不修改源 JSON。

## 15. 设计结论

唯一 ID 是标注对象管理的基础设施，而不是一个可有可无的附加字段。它直接改变了
X-AnyLabeling JSON 的 Shape 结构，也为下游建立了稳定契约：

- JSON 中的 Shape 第一次拥有与标签、坐标和分组无关的正式身份；
- UI、行为分析、质检、复核和未来数据库可以围绕同一对象进行关联；
- 临时下标、对象地址和 QA ID被限制在其正确生命周期内；
- 旧项目可以惰性迁移，也可以通过明确的批量操作一次性持久化；
- 外部格式边界保持清晰，不因私有身份污染标准交换数据。

后续任何需要“跨时间管理同一个标注对象”的新功能，都应优先采用
`(project_id, image_id, xanylabeling_shape_id)`，并在设计评审中明确它使用的是
持久身份、业务分组身份还是扫描期临时身份。
