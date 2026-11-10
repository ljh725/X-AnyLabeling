# 修正成本统计：固定验收样本设计（tasks.md 1.3）

- 变更：`openspec/changes/add-annotation-correction-cost-statistics`
- 任务：tasks.md **1.3 建立授权或自制固定样本**
- 状态：设计完成，待实施（本文件不在仓库受限区，只作方案记录）
- 约束：全部样本**程序生成**（PIL 纯色块 + 确定性噪声），**不使用任何真人照片、真实客户数据或网络资源**，
  无授权与隐私问题；生成器无 Qt 依赖。

---

## 0. 结论速览

| 项 | 结果 |
| --- | --- |
| 要求的 8 类样本 | **8/8 齐备**（scene key 见 §3） |
| scene 数量 | 10（8 主样本 + 2 负例/边界样本） |
| 变体（完成事务脚本）数量 | 22，覆盖等价坐标、锁定、形状转换、草稿/已保存、AI 追加/替换等分支 |
| 预期净值来源 | 由 `core.differences()` / `core.report_row()` 语义**推导并由 manifest 程序生成**，不手写数字（防漂移）；8 个关键变体已用真实 `core.differences()` 实机校验通过（见 §8） |
| 确定性 | 固定坐标、固定绘制顺序、无 RNG/时钟/EXIF；同 Pillow 版本内字节一致 |
| 复用先例 | 对齐 `scripts/generate_dense_review_samples.py` + `samples/dense_review/` + `tests/test_dense_review/test_samples.py` 的既有约定 |

---

## 1. 通用约定

### 1.1 目录与命名（建议落地位置）

```
scripts/generate_correction_metrics_samples.py   # 生成器（纯函数 + CLI + --check）
samples/correction_metrics/                      # 生成物（可入库的固定样本）
  <scene>.png           640×640 RGB
  <scene>.json          X-AnyLabeling 标注（主样本起点）
  manifest.json         预期净值 / 变体 / spec 映射（机器可读）
  README.md             人工可读说明（8 类样本与预期结果表）
tests/test_correction_metrics/test_samples.py     # 校验 manifest 与再生成结果一致
```

> 命名理由：与 `MANIFEST_SCHEMA = "xanylabeling.dense_review.samples/1"` 同构，改为
> `"xanylabeling.correction_metrics.samples/1"`；校验风格沿用
> `tests/test_dense_review/test_samples.py`（**只比较再生成 manifest 与对象内容，不比较 PNG 字节**，
> 避免 Pillow 版本差异造成假失败）。

### 1.2 图片

| 约定 | 值 |
| --- | --- |
| 尺寸 | 全部 **640×640**（固定；20×15 网格可容纳 300 框） |
| 模式 | `RGB`，PNG（`io.BytesIO` 输出，无 EXIF、无 tIME 块） |
| 背景 | 样本 1 为空图纯色 `(246,245,241)`；其余为**确定性噪声**（见下） |
| 绘制 | `ImageDraw` 画纯色矩形/多边形块；**不渲染文字**（避免字体依赖导致跨平台不一致） |
| 确定性噪声 | `r = ((x*1103515245 + y*12345 + 12345) >> 16) & 0xFF` 逐像素算术；**不用 `random`、不用超采样**（dense_review 用 `SUPERSAMPLE=2`，此处直接 1× 绘制以保证任何 Pillow 版本下绘制结果稳定） |
| 遮挡 | 仅靠绘制顺序：先画被标注目标，再画"遮挡块"（遮挡块**不进入标注**），用于样本 4 |

### 1.3 标注 JSON 结构（与生产格式一致）

字段顺序与 `anylabeling/views/labeling/shape.py::Shape.KEYS` 一致：

```json
{
  "version": "4.2.1",
  "flags": {},
  "checked": false,
  "shapes": [
    {
      "xanylabeling_shape_id": "p-001",
      "label": "cat",
      "score": null,
      "points": [[20, 20], [90, 20], [90, 110], [20, 110]],
      "group_id": null,
      "difficult": false,
      "shape_type": "rectangle",
      "flags": {},
      "description": "",
      "attributes": {},
      "kie_linking": [],
      "locked": false
    }
  ],
  "imagePath": "dense_30_six_classes.png",
  "imageData": null,
  "imageHeight": 640,
  "imageWidth": 640
}
```

要点（已按代码核对）：

1. **矩形用 4 点** LT→RT→RB→LB（`shape.py:493` 允许 1/2/4 点；dense_review 生成器同款 4 点写法）。
2. `xanylabeling_shape_id` 是 `core.snapshot()` 的唯一身份键（`core.py:90`）；缺失或重复 → issue
   `shape-identity-conflict`，键退化为 `?unmatched:<序号>`（`core.py:91-94`）。负例样本 9 覆盖该降级路径。
3. `locked` 会写进标注文件，但 **`snapshot()` 明确把 `locked` 排除在内容之外**（`core.py:116`）：
   锁定/解锁**不构成内容变化** —— 样本 5 的关键负例。
4. 缺省字段（`flags/attributes/kie_linking/description/difficult/group_id/score`）视为缺省等价（`core.py:109-118`），
   旧标注缺字段不会误判变化 —— 样本 7 用旧 `version` + `checked: true` 覆盖。
5. `checked: true` 只作"旧审核标记原样另列"，**不推导质量合格**（EVT-8 / REP-2）。

### 1.4 对象 ID 规范

- 统一正则 `[a-z0-9]+-\d{3}`（沿用 `tests/test_dense_review/test_samples.py:118` 的断言正则）。
- 前缀语义：`p-` 密集人像、`s-` 压力网格、`o-` 遮挡小目标、`l-` 锁定、`r-` 混合矩形、`g-` 多边形、
  `t-` 旋转框、`k-` 点、`n-` 本轮新建、`u-` 旧标注、`m-` 人工、`a-` AI。
- ID 在样本生命周期内**固定不变**：变体不得改动基线 ID（新增对象才用新 ID），否则身份集合比较失效。

### 1.5 起点/来源 fixture（与标注 JSON 分离）

每个 scene 额外给一份"轮次状态"描述（生成器输出到 manifest，测试用 `core.initialise_state` 装配，
**不写进标注 JSON**，符合 BASE-6"统计事件不写入标注 JSON"）：

```json
{
  "phase": "correction",
  "origin": "additive",
  "predicted": ["a-001", "a-002", "a-003"],
  "provenance": {
    "run_id": "run-20261103-01",
    "model": "yolov8n-det",
    "model_version": "v1.2",
    "config_digest": "sha256:0f6c",
    "category_version": "cv-1",
    "elapsed_s": 12.5
  },
  "saved": true,
  "quality": "not-assessed"
}
```

- `provenance` 只允许 `core.ORIGIN_FIELDS` 内的键（`core.py:18-23`）；**不得出现 URL/密钥**
  （`core.py:64` 丢弃含 `://` 的字符串）。样本 8 故意塞入一个 `api_key` 与 `endpoint: "https://…"` 的
  **非法附加字段**，断言被 `safe_provenance()` 过滤（覆盖 BASE-4"不含 API 密钥/凭据链接"）。
- `origin` 只取 `unknown-existing | replacement | additive`（`core.py:17`）。

### 1.6 确定性检查清单

- [x] 无 `random`、无 `time`、无 `uuid`（ID 全部字面量）、无 `os.environ` 分支；
- [x] 浮点只在确有需要处（样本 4 的 0.4px 亚像素），其余全整数；
- [x] JSON `ensure_ascii=False, indent=2` + 末尾换行；manifest 列表按 key 排序；
- [x] `--check` 比较 manifest + 标注 JSON + 图片尺寸，**不比 PNG 字节**；
- [x] 样本目录不写时间戳文件。

---

## 2. 预期净值口径（逐字段，来自 `anylabeling/services/correction_metrics/core.py`）

| 字段 | 计算规则（代码位置） |
| --- | --- |
| `baseline_count` | 起点中 `kind == "rectangle"` 的对象数（`core.py:133-135,141,166`） |
| `final_count` | 终态矩形数 |
| `added` | `F_keys − baseline.objects`（`core.py:144`） |
| `deleted` | `B_keys − final.objects`（**必须整个 ID 消失**；变形状不算 deleted，`core.py:145`） |
| `geometry_changed` (G) | `B∩F` 中规范化 bbox 发生变化的身份（`core.py:147`） |
| `class_changed` (C) | `B∩F` 中经 `aliases` 映射后标签变化的身份；`class_comparable=False` 时为 `None`（`core.py:148-149`） |
| `modified_original` | `len(deleted ∪ G ∪ C)`，按身份去重（`core.py:150`） |
| `unchanged` | `len(common − G − C)`；C 不可判时为 `None`（`core.py:151`） |
| `modified_rate` / `unchanged_rate` | 分母为 `baseline_count`；分母为 0 → `None`（即 N/A，`core.py:170-171`） |
| `unsupported_count` | 终态中非矩形对象数（`core.py:172`） |
| `scope_changes` | 形状类型发生转换的身份数，**既不计 added 也不计 deleted**（`core.py:146,173`） |
| `issues` | `unknown-origin`（origin=unknown-existing）、`partial-scope`、`type-conversion`、`unsaved-result`、`shape-identity-conflict`、`invalid-geometry`、`class-incomparable`（`core.py:216-234`） |
| `comparable` | `not issues`（`core.py:257`） |
| `transactions` | `counts` 中除 `review-confirm/review-undo/taxonomy/discard/undo` 外的事务总数（`core.py:253-254`） |
| `touches` / `unique_objects` | 每次事务 `touches += len(before ∪ after)`；去重集合大小（`core.py:325-327`） |
| `ai_count` | 起点中属于 `predicted_ids` 且为矩形的数量；`origin=unknown-existing` 时为 `None`（`core.py:250-252`） |

**两种规范化必须同时成立**（任务 2.3）：点序/数值表示等价 → 不算改框；真实 0.4px 级微调 → 算改框。

---

## 3. 八类样本定义

> 每节结构：用途 → 图片/对象 → 起点 fixture → 变体与预期 → 验证的 spec Scenario → 对应任务。

### 3.1 样本 1：空图（`empty_blank`）

- **用途**：零对象基线、零分母 N/A、空图导出、`ai_count=0` 的干净对照。
- **图片**：640×640 纯色背景，无对象、无遮挡块。
- **对象**：`()`。
- **起点**：`origin="replacement"`、`predicted=()`、`provenance` 带 model 信息（模型"本次预测 0 个"是合法轮次）。

| 变体 | baseline | final | added | deleted | G | C | modified | unchanged | rates | unsupported | scope | tx | touches | unique | ai | issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `freeze` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | N/A | 0 | 0 | 0 | 0 | 0 | **0** | `[]` |
| `add_three` | 0 | 3 | **3** | 0 | 0 | 0 | 0 | 0 | **N/A** | 0 | 0 | 1 | 3 | 3 | 0 | `[]` |
| `unknown_origin`（state 覆盖） | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | N/A | 0 | 0 | 0 | 0 | 0 | **None** | `["unknown-origin"]` |

- **验证的 spec Scenario**：`EVT-7.2 空起点新增标注`（新增数显示、全部比例 N/A）；
  `REP-6.2 缺失来源和零分母导出`（N/A 不写成 0）；`REP-2.1 草稿不同于已保存版本`（空图对照）。
- **对应任务**：2.3、2.4、7.4、8.3、9.1。

### 3.2 样本 2：30 人多类别密集图（`dense_30_six_classes`）

- **用途**：主验收样本 —— 六类、30 框，改框/改类/同改/删/增五类净结果同时出现；密度分组与性能基线。
- **图片**：640×640 噪声背景；30 个纯色块（6 列 × 5 行，`x=20+col*100, y=20+row*110, w=70, h=90`）。
- **对象**：`p-001…p-030`，类别按 5 个一组：`cat/dog/person/car/tree/sign`。
- **起点**：`origin="replacement"`、`predicted=全部 30 个 ID` → `ai_count=30`。
- **主变体 `scripted_corrections`（编辑脚本，坐标固定）**：

| # | 事务 | 操作 | 对象 |
| --- | --- | --- | --- |
| T1–T4 | 4 个独立拖框事务 | 平移 (+6,+4) | `p-003`, `p-007`, `p-012`, `p-019` |
| T5 | 1 个拖框事务 | 平移 (+6,+4) | `p-014` |
| T6–T8 | 3 个单对象改类 | cat→dog / person→car / tree→sign | `p-002`, `p-011`, `p-025` |
| T9 | 1 个改类事务 | person→dog（与 T5 同一对象，独立完成） | `p-014` |
| T10 | 1 个批量删除事务 | 删除 | `p-021`, `p-028` |
| T11 | 1 个批量创建事务 | 新建（`cat` / `car`） | `n-101`, `n-102` |

| 变体 | baseline | final | added | deleted | G | C | modified | unchanged | modified_rate | unchanged_rate | tx | touches | unique | ai | issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `freeze` | 30 | 30 | 0 | 0 | 0 | 0 | 0 | 30 | 0.0 | 1.0 | 0 | 0 | 0 | 30 | `[]` |
| `identity_reorder` | 30 | 30 | 0 | 0 | 0 | 0 | 0 | 30 | 0.0 | 1.0 | **0** | 0 | 0 | 30 | `[]` |
| `scripted_corrections` | 30 | 30 | **2** | **2** | **5** | **4** | **10** | **20** | 1/3 | 2/3 | **11** | **13** | **12** | 30 | `[]` |
| `no_change_submit` | 30 | 30 | 0 | 0 | 0 | 0 | 0 | 30 | 0.0 | 1.0 | **0** | 0 | 0 | 30 | `[]` |
| `draft_not_saved`（draft 视图） | 30 | 30 | 2 | 2 | 5 | 4 | 10 | 20 | 1/3 | 2/3 | 11 | 13 | 12 | 30 | `[]` |
| `draft_not_saved`（saved 视图） | 30 | 30 | **None** | **None** | **None** | **None** | **None** | **None** | None | None | 11 | 13 | 12 | 30 | `["unsaved-result"]` |

推导：`modified_original = |{p-021,p-028} ∪ {p-003,p-007,p-012,p-019,p-014} ∪ {p-002,p-011,p-025,p-014}| = 2 + 8 = 10`；
`unchanged = (30−2) − |G∪C| = 28 − 8 = 20`；`touches = 5(拖框) + 4(改类) + 2(删) + 2(增) = 13`；
`unique = |5 ∪ 4−1 ∪ 2 ∪ 2| = 12`。

- **验证的 spec Scenario**：`EVT-3.1 原框同时改类和改框`（p-014 同时进 G 和 C，`modified_original` 只 +1）、
  `EVT-3.2 新增框再修改或删除`（n-101/n-102 只进 added）、`EVT-2.2 重复修改同一对象`（p-014 两个事务、去重 1）、
  `EVT-7.1 改类并改框`（几何归起点类、方向 A→B）、`EVT-1.2 取消或没有实际变化`（`no_change_submit`）、
  `BASE-1.1 重排对象不产生修正`（`identity_reorder`）、`REP-2.1 草稿不同于已保存版本`。
- **对应任务**：2.3、2.4、2.5、7.4、9.1、9.4（30 框性能基线）。

### 3.3 样本 3：300 矩形压力图（`stress_300_grid`）

- **用途**：规模与批量事务；性能基准（任务 9.4 的 300 框侧）；批量改类/批量删除的对象计数。
- **图片**：640×640 噪声背景；20×15 网格块（`x=col*32, y=row*42, w=28, h=38`，末列/末行仍在界内）。
- **对象**：`s-001…s-300`，类别循环 `cat/dog/person`（各 100）。
- **起点**：`origin="replacement"`、`predicted=全部 300` → `ai_count=300`。

| 变体 | baseline | final | added | deleted | G | C | modified | unchanged | rates | tx | touches | unique | ai |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `freeze` | 300 | 300 | 0 | 0 | 0 | 0 | 0 | 300 | 0.0 / 1.0 | 0 | 0 | 0 | 300 |
| `batch_relabel_10` | 300 | 300 | 0 | 0 | 0 | **10** | **10** | **290** | 1/30 / 29/30 | **1** | **10** | **10** | 300 |
| `batch_delete_5` | 300 | 295 | 0 | **5** | 0 | 0 | **5** | **295** | 5/300 / 295/300 | 1 | 5 | 5 | 300 |

- **验证的 spec Scenario**：`EVT-2.1 一次改动多个对象`（1 事务 / 10 触达 / 10 去重对象）、
  `REP-8.1 持续拖框`（性能门槛用本样本做长时拖拽）、`REP-5.1 汇总混合完整和不完整轮次`（样本量证据）。
- **对应任务**：2.4、9.1、9.4（p95 ≤ 5 ms / 300 框）。

### 3.4 样本 4：遮挡小目标（`occluded_small`）

- **用途**：几何规范化等价性与"真实微坐标仍被识别"的成对正负例；一拖框=一事务。
- **图片**：640×640 噪声背景；先画 6 个 8×8 小目标与 6 个 60×80 目标，再画 3 个 200×180 灰色遮挡块
  （遮挡块**不标注**），使 `o-001…o-006` 视觉上被遮住。
- **对象**：`o-001…o-006`（8×8）、`o-007…o-012`（60×80），类别 `cat/dog` 交替。
- **起点**：`origin="replacement"`、`predicted=全部 12` → `ai_count=12`。

| 变体 | 操作 | G | C | modified | unchanged | rates | tx | touches | unique | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `freeze` | 无 | 0 | 0 | 0 | 12 | 0.0 / 1.0 | 0 | 0 | 0 | 对照 |
| `equivalent_rewrite` | 全部矩形改写为**逆序 4 点**、3 个改为**2 点对角线**、`o-007` 整数改 `float` | **0** | 0 | 0 | 12 | 0.0 / 1.0 | **0** | 0 | 0 | 点序/表示等价不算改框 |
| `one_pixel_edge` | `o-004` 右边 +1px（8×8 → 9×8） | **1** | 0 | 1 | 11 | 1/12 | 1 | 1 | 1 | 真实 1px 拖边必须识别 |
| `subpixel_noise` | `o-005` 右上角 +0.4px | **1** | 0 | 1 | 11 | 1/12 | 1 | 1 | 1 | 微坐标识别 |
| `move_occluded_pair` | 一次事务同时平移 `o-001`、`o-002` (+2,+2) | **2** | 0 | 2 | 10 | 2/12 | **1** | **2** | **2** | 一事务多对象 |

- **验证的 spec Scenario**：`EVT-3`（净结果按稳定身份集合、规范化几何比较等价坐标）、
  `EVT-1.1 一次拖框有多次移动事件`（测试侧模拟鼠标采样 37 次、同一 `transaction_id` 提交 → 仍 1 事务）。
- **对应任务**：2.3、4.5、9.1。

### 3.5 样本 5：部分锁定对象（`partial_locked`）

- **用途**：锁定对象不计入受影响集合；锁状态本身不是内容。
- **图片**：640×640 噪声背景；10 个纯色块。
- **对象**：`l-001…l-010`（`cat/dog` 各 5）；`locked: true` 的是 `l-002`、`l-005`、`l-008`、`l-010`。
- **起点**：`origin="replacement"`、`predicted=全部 10` → `ai_count=10`。

| 变体 | 操作 | G | C | modified | unchanged | tx | touches | unique | issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `freeze` | 无 | 0 | 0 | 0 | 10 | 0 | 0 | 0 | `[]` |
| `batch_relabel_all_10` | 单事务批量改类 → `sign`（含 4 个锁定对象） | 0 | **6** | **6** | **4** | **1** | **6** | **6** | `[]` |
| `drag_three_two_locked` | 单事务拖 3 个（`l-001`/`l-002`(locked)/`l-003`） | **2** | 0 | 2 | 8 | 1 | 2 | 2 | `[]` |
| `lock_toggle_only` | 切换 3 个对象的 `locked` 标志（`l-001` 锁、`l-002`/`l-005` 解锁） | **0** | 0 | 0 | **10** | **0** | 0 | 0 | `[]` |
| `description_only`（**待 spec 澄清**） | 只改 `l-004` 的 `description` | 0 | 0 | 0 | 10 | **1** | 1 | 1 | `[]` |

- 关键断言：锁定对象**不进入** `touches`/`unique_objects`（EVT-2）；`locked` 不进快照内容（`core.py:116`），
  因此 `lock_toggle_only` 不产生事务、净结果为 0。
- **验证的 spec Scenario**：`EVT-2.1 一次改动多个对象`（"被锁定、未改变或未实际应用的对象不计入"）、
  `EVT-1.2 取消或没有实际变化`（锁定切换属无内容变化）。
- **对应任务**：2.6、4.4、4.5、9.2（GUI 锁定对象回归）。

### 3.6 样本 6：混合非矩形（`mixed_shapes`）

- **用途**：矩形范围不完整、形状类型转换单列、完整比较被排除但矩形事实仍可见。
- **图片**：640×640 噪声背景；8 个矩形块 + 2 个三角形 + 1 个旋转矩形 + 1 个点标记。
- **对象**：
  - 矩形：`r-001…r-008`（`cat/dog`）；
  - 多边形：`g-001`（3 点三角形）、`g-002`（4 点四边形）；
  - 旋转框：`t-001`（`shape_type: "rotation"`，4 点）；
  - 点：`k-001`（`shape_type: "point"`，1 点）。
- **起点**：`origin="replacement"`、`predicted=r-001…r-008` → `ai_count=8`（非矩形不参与 AI 计数）。

| 变体 | 操作 | baseline | final | added | deleted | G | C | modified | unchanged | unsupported | scope | tx | issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `freeze` | 无 | 8 | 8 | 0 | 0 | 0 | 0 | 0 | **8** | **4** | 0 | 0 | `["partial-scope"]` |
| `edit_rects_only` | 拖 `r-001`，改类 `r-002` | 8 | 8 | 0 | 0 | **1** | **1** | **2** | **6** | 4 | 0 | 2 | `["partial-scope"]` |
| `convert_one_rect` | `r-004` 由矩形转为多边形（ID 不变） | 8 | **7** | **0** | **0** | 0 | 0 | **0** | 7 | **5** | **1** | 1 | `["partial-scope","type-conversion"]` |

- 关键断言：`convert_one_rect` **不产生 added+deleted**（`scope_changes=1`），`comparable=false`，
  但 `added/deleted/G/C/unchanged` 仍为可判定的矩形事实（BASE-8 最后一条、EVT-3 最后一句）。
- **验证的 spec Scenario**：`BASE-8.3 混合形状或形状转换`、`REP-2.2 统计发生缺口`、`REP-5.1 汇总混合完整和不完整轮次`。
- **对应任务**：2.6、7.3、7.4、9.1。

### 3.7 样本 7：未知来源旧标注（`legacy_unknown`）

- **用途**：`unknown-existing` 起点、`ai_count=None`、旧 `checked` 标记、删除不判误检、质量默认未评估。
- **图片**：640×640 噪声背景；25 个纯色块（5×5 网格）。
- **对象**：`u-001…u-025`，5 类各 5（`cat/dog/person/car/tree`）。
- **标注 JSON**：`version: "3.0.0"`（旧版本号）、`checked: true`（旧审核标记）、无 provenance。
- **起点**：`origin="unknown-existing"`、`predicted=()`、`provenance={}`。

| 变体 | 操作 | baseline | final | added | deleted | G | C | modified | unchanged | rates | tx | touches | unique | ai | issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `freeze` | 无 | 25 | 25 | 0 | 0 | 0 | 0 | 0 | 25 | 0.0 / 1.0 | 0 | 0 | 0 | **None** | `["unknown-origin"]` |
| `delete_one_relabel_two` | 删 `u-007`；改类 `u-003` cat→dog、`u-014` person→tree | 25 | **24** | 0 | **1** | 0 | **2** | **3** | **22** | 3/25 / 22/25 | **3** | 3 | 3 | None | `["unknown-origin"]` |
| `complete_then_browse` | 保存 → 显式完成 → 再浏览 | 25 | 25 | 0 | 0 | 0 | 0 | 0 | 25 | 0.0 / 1.0 | 0 | 0 | 0 | None | `["unknown-origin"]`；`quality="not-assessed"` |

- **验证的 spec Scenario**：`BASE-2.1 对历史标注开始统计`、`BASE-2.2 后续编辑不修改起点`、
  `EVT-8.1 用户删除一个框`（只记删除，不加误检/不降精度）、`REP-6.2 缺失来源和零分母导出`、
  `REP-2.2 统计发生缺口`、`TIM-8.1 完成后留在画面浏览`（计时侧配合）。
- **对应任务**：2.1、2.6、5.6、8.3、9.1。

### 3.8 样本 8："5 人工框 + 3 AI 框"追加案例（`additive_5_plus_3`）

- **用途**：增量预测起点 —— 8 个矩形里只有 3 个属于本次 AI 预测；`ai_count` 必须为 3 而非 8。
- **图片**：640×640 噪声背景；8 个纯色块（5 人工块 + 3 AI 块，颜色区分但**不影响标注**）。
- **对象**：`m-001…m-005`（人工/旧标注，`cat/dog`）、`a-001…a-003`（本次 AI，`dog/car`）。
- **起点**：`origin="additive"`、`predicted=["a-001","a-002","a-003"]`、provenance 见 §1.5
  （额外塞入 `api_key`、`endpoint: "https://…"` 两个非法字段，断言被 `safe_provenance` 丢弃）。

| 变体 | 操作 | baseline | final | added | deleted | G | C | modified | unchanged | tx | touches | unique | ai | issues |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `freeze` | 无 | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 8 | 0 | 0 | 0 | **3** | `[]` |
| `fix_after_append` | 改类 `a-001` dog→cat；拖 `m-002`；删 `a-003` | 8 | **7** | 0 | **1** | **1** | **1** | **3** | **5** | 3 | 3 | 3 | 3 | `[]` |
| `second_ai_import` | 一次追加预测导入 `a-004…a-006`（`source="prediction"`） | 8 | **11** | **3** | 0 | 0 | 0 | 0 | 8 | **1** | 3 | 3 | **3** | `[]` |

- 关键断言：`ai_count == 3`（不是 8，也不是 6）；`m-001…m-005` 的"人工/旧"来源不得被改写为本次 AI 对象
  （**注意：`core.report_row()` 只暴露轮次级 `origin`，无逐对象来源字段 → 见 §7 GAP-2**）。
- **验证的 spec Scenario**：`BASE-3.1 AI 追加到人工框`、`EVT-5.2 AI 批量导入`（记录预测应用与来源，
  不增加相同数量的人工新增事务）、`EVT-5.1 接受候选与手工绘制`（过程来源可区分）。
- **对应任务**：2.1、4.1、4.2、4.3、8.1、9.1。

### 3.9 负例样本 9：旧标注缺少对象 ID（`legacy_unknown_missing_id`）

- 与样本 7 相同 25 个框，但 `u-013` 的 `xanylabeling_shape_id` 被**故意删除**。
- 预期：`snapshot()` 产生 issue `shape-identity-conflict`、该对象键退化为 `?unmatched:12`；
  `report_row()` 将 `added/deleted/geometry_changed/class_changed/modified_original/unchanged/*_rate`
  **全部置 None**，`classes` 只保留 `initial`/`final` 两类行；`baseline_count` 25、`final_count` 25 仍可读；
  issues `["shape-identity-conflict","unknown-origin"]`、`comparable=false`。
- **验证的 spec Scenario**：`BASE-1 图片和轮次身份可追溯`（无法可靠关联时标记缺口，任务 2.2）、
  `BASE-8.1 标注已保存但统计检查点缺失`（缺口披露而非重建）。

### 3.10 负例样本 10：替换预测保留受保护对象（`replacement_5_plus_3`）

- 与样本 8 同一张图与同一份 8 框标注，但 `origin="replacement"`、`predicted=["a-001","a-002","a-003"]`。
- 变体 `freeze`：baseline 8 / final 8 / 全 0 / unchanged 8 / `ai_count=3` / issues `[]`。
- 变体 `replace_adds_two`：本次预测把 3 个 AI 框替换为 2 个新框（`a-101`、`a-102`），保留 5 个人工框 →
  added **2**、deleted **3**、modified **3**、unchanged **5**、final **7**、`ai_count` **3**、
  tx 1、touches 5、unique 5；**逐对象来源保留**需 2.1 补充（§7 GAP-2）。
- **验证的 spec Scenario**：`BASE-3.2 替换保留受保护对象`、`EVT-5.2 AI 批量导入`。

---

## 4. 生成器接口草案

### 4.1 模块与依赖

- 路径：`scripts/generate_correction_metrics_samples.py`（与 `scripts/generate_dense_review_samples.py` 平级）。
- 依赖：**仅** `argparse, io, json, dataclasses, pathlib, typing, PIL.Image, PIL.ImageDraw`。
- **不得 import Qt**（`PyQt6`/`anylabeling.views.*`）、**不得 import 业务服务**（生成器不能被产品代码反向依赖）。
- 测试侧可以在生成器结果上调用 `anylabeling.services.correction_metrics.core.differences/snapshot`
  **派生**预期值；生成器本身不依赖 core（保持零耦合，先例同 dense_review）。

### 4.2 数据类型

```python
@dataclass(frozen=True)
class SampleObject:
    """一个标注对象 + manifest 元数据。points() 输出 JSON 就绪的列表。"""
    shape_id: str
    label: str
    bounds: tuple[int, int, int, int] = ()          # 矩形 (l, t, r, b)
    polygon: tuple[tuple[int, int], ...] = ()        # 多边形/旋转框/点
    shape_type: str = "rectangle"                    # rectangle|polygon|rotation|point
    locked: bool = False
    difficult: bool = False
    truth_label: str = ""                            # 仅记录用途，不写入统计
    tags: tuple[str, ...] = ()
    note: str = ""

    def points(self) -> list[list[float]]: ...       # 矩形 → 4 点 LT/RT/RB/LB
    def bbox(self) -> tuple[float, float, float, float]: ...


@dataclass(frozen=True)
class Edit:
    """一次"完成事务"的声明式重放步骤（测试用它把起点推到终态）。"""
    op: str                      # create|delete|move|relabel|convert|rewrite|reorder|lock|undo|discard|save
    ids: tuple[str, ...] = ()
    dx: int = 0
    dy: int = 0
    label: str = ""              # relabel / create 的目标类
    shape_type: str = ""         # convert 的目标类型
    polygons: tuple[tuple[tuple[int, int], ...], ...] = ()   # create 的目标几何
    transaction_id: str = ""     # 固定字符串，保证幂等/去重可复现
    source: str = "manual"       # manual|prediction|candidate|undo|review
    repeat_syncs: int = 1        # "一次拖框有多次移动事件"：同一 tx 提交 N 次


@dataclass(frozen=True)
class Variant:
    key: str
    title: str
    edits: tuple[Edit, ...]
    expected: Mapping[str, Any]                 # 见 §2 字段；None 表示 N/A
    state: Mapping[str, Any] = field(default_factory=dict)   # 覆盖 origin/predicted/saved/quality
    draft_only: bool = False                    # True → 同时给 draft/saved 两个视图的预期


@dataclass(frozen=True)
class Scene:
    key: str
    title: str
    purpose: str
    objects: tuple[SampleObject, ...]
    origin: str                                  # unknown-existing|replacement|additive
    predicted: tuple[str, ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    label_version: str = "4.2.1"
    checked: bool = False                        # 旧标注用 True
    primary: bool = True                         # False = 负例/边界样本
    variants: tuple[Variant, ...] = ()
    scenarios: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    draw: Callable[[ImageDraw.ImageDraw, Mapping[str, SampleObject]], None] = _draw_blocks


@dataclass(frozen=True)
class Sample:
    """对外最小产物：图片字节 + shapes 列表（可直接喂给 core.snapshot）。"""
    key: str
    image_png: bytes
    shapes: tuple[dict[str, Any], ...]          # JSON 就绪的 shape dict 列表
    label_payload: dict[str, Any]
    state: dict[str, Any]
    variants: tuple[Variant, ...]
```

### 4.3 公共函数（纯函数；除 `generate/check` 不触盘）

```python
SCENES: tuple[Scene, ...]                     # 10 个 scene
IMAGE_WIDTH = 640
IMAGE_HEIGHT = 640
LABEL_FORMAT_VERSION = "4.2.1"
MANIFEST_SCHEMA = "xanylabeling.correction_metrics.samples/1"
DEFAULT_OUTPUT = REPO_ROOT / "samples" / "correction_metrics"

def background(width: int = IMAGE_WIDTH, height: int = IMAGE_HEIGHT) -> Image.Image: ...
def render_scene(key: str) -> Sample: ...      # 关键接口：bytes + shapes
def build_label_payload(scene: Scene) -> dict[str, Any]: ...
def build_state_payload(scene: Scene) -> dict[str, Any]: ...
def build_manifest() -> dict[str, Any]: ...
def apply_edits(objects: Sequence[SampleObject], edits: Sequence[Edit]) -> list[dict[str, Any]]: ...
def render_samples() -> dict[str, bytes]: ...  # 文件名 → 字节（内存）
def generate(output_dir: Path | str, *, force: bool = False) -> dict: ...
def check(output_dir: Path | str) -> list[str]: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

`apply_edits` 是**测试与 manifest 共用的唯一重放实现**：manifest 的 `expected` 由
`differences(snapshot(baseline_shapes), snapshot(apply_edits(...)))` 生成，因此预期值不可能与样本脱节。
（`correction_metrics.core.differences(baseline, final, aliases=None, class_comparable=True)`，返回值见 §2。）

### 4.4 manifest 结构

```json
{
  "schema": "xanylabeling.correction_metrics.samples/1",
  "generator": "scripts/generate_correction_metrics_samples.py",
  "image_width": 640,
  "image_height": 640,
  "label_format_version": "4.2.1",
  "scenes": [
    {
      "key": "additive_5_plus_3",
      "title": "5 人工框 + 3 AI 框追加",
      "image": "additive_5_plus_3.png",
      "label": "additive_5_plus_3.json",
      "primary": true,
      "object_count": 8,
      "class_distribution": {"car": 1, "cat": 3, "dog": 4},
      "shape_type_distribution": {"rectangle": 8},
      "image_width": 640,
      "image_height": 640,
      "state": {"origin": "additive", "predicted": ["a-001", "a-002", "a-003"], "saved": true},
      "objects": [{"id": "m-001", "label": "cat", "shape_type": "rectangle",
                   "bbox": [40, 40, 130, 150], "locked": false}],
      "variants": [
        {
          "key": "freeze",
          "edits": [],
          "expected": {"baseline_count": 8, "final_count": 8, "added": 0,
                        "deleted": 0, "geometry_changed": 0, "class_changed": 0,
                        "modified_original": 0, "unchanged": 8,
                        "modified_rate": 0.0, "unchanged_rate": 1.0,
                        "unsupported_count": 0, "scope_changes": 0,
                        "transactions": 0, "touches": 0, "unique_objects": 0,
                        "ai_count": 3, "issues": [], "comparable": true}
        }
      ],
      "scenarios": {
        "annotation-correction-baseline": ["3.1", "3.2"],
        "annotation-correction-events": ["5.1", "5.2"],
        "annotation-correction-reporting": ["5.2"]
      }
    }
  ]
}
```

### 4.5 CLI（沿用先例）

```
python scripts/generate_correction_metrics_samples.py                # 生成到 samples/correction_metrics
python scripts/generate_correction_metrics_samples.py --output DIR --force
python scripts/generate_correction_metrics_samples.py --check       # 只校验，不写
```

### 4.6 使用示例（测试侧，无 Qt）

```python
from anylabeling.services.correction_metrics import core
from scripts.generate_correction_metrics_samples import render_scene, apply_edits, SCENES

sample = render_scene("dense_30_six_classes")
scene = next(s for s in SCENES if s.key == "dense_30_six_classes")
variant = next(v for v in sample.variants if v.key == "scripted_corrections")

baseline = core.snapshot(sample.shapes)
final = core.snapshot(apply_edits(scene.objects, variant.edits))
net = core.differences(baseline, final)
assert net["modified_original"] == 10 and net["unchanged"] == 20   # 样本 2 主变体
```

---

## 5. 每个样本 ↔ spec Scenario 映射（速查）

| 样本 | 主验证 Scenario（可多条） | tasks.md |
| --- | --- | --- |
| 1 `empty_blank` | EVT-7.2、REP-6.2、REP-2.1 | 2.3, 2.4, 7.4, 8.3, 9.1 |
| 2 `dense_30_six_classes` | EVT-3.1、EVT-3.2、EVT-2.2、EVT-7.1、EVT-1.2、BASE-1.1、REP-2.1 | 2.3–2.5, 7.4, 9.1, 9.4 |
| 3 `stress_300_grid` | EVT-2.1、REP-8.1、REP-5.1 | 2.4, 9.1, 9.4 |
| 4 `occluded_small` | EVT-3、EVT-1.1 | 2.3, 4.5, 9.1 |
| 5 `partial_locked` | EVT-2.1、EVT-1.2 | 2.6, 4.4, 4.5, 9.2 |
| 6 `mixed_shapes` | BASE-8.3、REP-2.2、REP-5.1 | 2.6, 7.3, 7.4, 9.1 |
| 7 `legacy_unknown` | BASE-2.1、BASE-2.2、EVT-8.1、REP-6.2、REP-2.2、TIM-8.1 | 2.1, 2.6, 5.6, 8.3, 9.1 |
| 8 `additive_5_plus_3` | BASE-3.1、EVT-5.1、EVT-5.2 | 2.1, 4.1–4.3, 8.1, 9.1 |
| 9 `legacy_unknown_missing_id` | BASE-1、BASE-8.1 | 2.2, 3.5 |
| 10 `replacement_5_plus_3` | BASE-3.2、EVT-5.2 | 2.1, 4.2, 4.3 |

编号规则（与 `scenario-coverage.md` 一致）：`BASE`→`annotation-correction-baseline`、
`EVT`→`annotation-correction-events`、`REP`→`annotation-correction-reporting`、
`TIM`→`annotation-work-timing`；`R` 为 Requirement 序号，`R.m` 为其中第 m 个 Scenario。

样本**未覆盖**的场景（须在其他测试文件中验证，见覆盖表 TODO）：身份/同名数据集、单张与批量预测失败、
迟到结果、重新预测新轮次、存储故障、保存失败重试、丢弃草稿、恢复与外部修改、撤销/复核、类别改名与合并拆分、
完成/批量完成/完成失效、完成数量去重、导出快照与取消、全部计时场景。

---

## 6. 验收断言清单（样本相关）

1. `test_manifest_matches_regenerated_scenes`：**再生成的 manifest 与入库 manifest 完全相等**（沿用先例，不比 PNG 字节）。
2. `test_generated_scene_counts_classes_and_ids`：每个 scene 的 `object_count`、类分布、`shape_type` 分布、
   ID 顺序与正则 `[a-z0-9]+-\d{3}`、ID 唯一、图片尺寸、`imagePath`、`imageData is None`。
3. `test_primary_samples_cover_eight_categories`：8 个 `primary: true` 的 scene，key 集合固定为
   `{empty_blank, dense_30_six_classes, stress_300_grid, occluded_small, partial_locked, mixed_shapes, legacy_unknown, additive_5_plus_3}`。
4. `test_expected_net_values_match_core`：每个 variant 用 §4.6 方式重算并断言 `expected`
   （**把样本接进业务逻辑的关键断言**）。
5. `test_samples_are_privacy_safe`：manifest 无内嵌 `imageData`、无真实人像引用、PNG 无 EXIF
   （`Image.open(...).getexif()` 为空）。
6. `test_locked_and_identity_edges`：样本 5/9 的负例断言（锁定不产事务、缺 ID 时计数全 None）。

---

## 7. 已发现的语义缺口（需在 2.x 补齐后才可断言）

> 从 `core.py` 现状与 spec 的差集中发现的实际问题，建议 Lead 转给实现任务。

- **GAP-1（事件统计缺 source 维度）**：`report_row()` 只按 kind 聚合 `operation_counts`（`core.py:255`），
  **没有按 `source`（manual/prediction/candidate/undo/review）聚合**。因此
  `EVT-5.1 接受候选与手工绘制`、`EVT-5.2 AI 批量导入`、`EVT-8.1 删除不判误检` 里的"来源可区分"无法从报告行断言，
  只能读事件表。建议 2.4 增加 `source_counts`（并按 source 区分"人工新增事务"）。
- **GAP-2（缺逐对象来源）**：`initialise_state()` 只保存轮次级 `origin` 与 `predicted_ids`（`core.py:184-207`），
  **没有逐对象 `object_origin` 映射**。`BASE-3.1/3.2` 要求"保留的已有对象保留各自来源"，
  样本 8/10 因此无法从 `report_row()` 断言（只能断言 `ai_count == 3`）。建议 2.1 增加
  `object_origins: dict[id, origin]`。
- **GAP-3（saved 视图的 `final_count`）**：`report_row()` 在 `saved is None` 时把多个字段置 None，
  但 `final_count` 仍等于 `baseline_count`（`core.py:215-221`）。样本 2 的 `draft_not_saved` 已把该行为写进预期，
  **建议复核是否应显示为 N/A**（否则界面可能显示"终态 30 框"却没有任何已保存结果）。
- **GAP-4（`description` 等 details 编辑的语义）**：改 `description`/`flags` 会产生 1 个事务
  （`_replace` → kind `edit`，`core.py:366-397`），但净差异里仍是 `unchanged`。
  spec 未定义"非几何非类别的字段编辑"是否算内容修正 —— 样本 5 的 `description_only` 标为待澄清。
- **GAP-5（`unsupported_count/scope_changes` 未被 unsaved-result 置空）**：与 GAP-3 同源，
  建议统一"缺失即 N/A"。

---

## 8. 落地边界说明

本文件是设计产物，位于 `.local/stage/team/samples-design.md`。`scripts/`、`samples/`、`tests/` 均不在本会话
可写范围，任务 1.3 的实现由后续实现任务承担。本会话 **PyQt6 未安装**，无法运行 `tests/` 下任何测试
（`import anylabeling` 会因 `PyQt6` 失败）；但 `correction_metrics/core.py` 只依赖标准库，因此已用
`importlib` 直接加载该文件，对本文推导的预期值做**实机校验**：

| 校验项 | 实机结果 | 与设计是否一致 |
| --- | --- | --- |
| 样本 2 `scripted_corrections` | `30/30 added 2 deleted 2 G 5 C 4 modified 10 unchanged 20`，rates `1/3`、`2/3` | ✅ |
| 样本 2 `identity_reorder` | 全 0，`unchanged 30` | ✅ |
| 样本 4 `equivalent_rewrite`（逆序 4 点 + 2 点对角线 + int→float） | `G = 0`，`unchanged 12` | ✅ |
| 样本 4 `one_pixel_edge` | `G = 1`，`unchanged 11`，`modified_rate 1/12` | ✅ |
| 样本 6 `freeze` | `unsupported_count 4`，`unchanged 8` | ✅ |
| 样本 6 `convert_one_rect` | `baseline 8 / final 7 / added 0 / deleted 0 / scope_changes 1 / unsupported 5` | ✅ |
| 样本 1 `add_three` | `added 3`，`modified_rate = unchanged_rate = None`（N/A） | ✅ |
| 样本 5 `lock_toggle_only` | 两次 `snapshot()` 完全相等（`locked` 不进内容） | ✅ |
| 样本 9 缺 ID | issues `["shape-identity-conflict"]`，键退化为 `?unmatched:12` | ✅ |

未实机校验的部分：事务/触达/去重计数（需 `MetricsStore` 与 SQLite，非纯函数）、`report_row()` 的
`draft`/`saved` 视图与 `issues` 传播 —— 这些仍需在 2.x 落地后用 §6.4 的自动断言覆盖。
样本落地时的一切数字以再生成的 manifest 与测试断言为准。
