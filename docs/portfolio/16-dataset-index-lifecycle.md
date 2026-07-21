# 16 · 数据集索引生命周期工程化
#### Dataset Index Lifecycle Hardening

> 把 SQLite 派生索引从「能用的缓存」升级为「工程化的生命周期系统」——6 态状态机管理缓存身份、staging 临时库 + `integrity_check` + `os.replace` 实现原子化重建、并**移除** upstream 的应用级模态进度框、在原 `LabelCheckWorker` 链路**前**加一层缓存优先短路（worker 本身未重写）。核心契约：**JSON 永远是唯一真相源，索引可丢弃可重建，索引失败绝不拖垮一次成功的标签保存**。
>
> [← 返回作品集主页](../PORTFOLIO.md)

---

## 解决的痛点

模块 11（筛选系统）引入 SQLite 派生索引解决了 5000 图筛选卡死的痛点，但初版索引在工程健壮性上有三条裂缝，commit `951ba30a feat: harden dataset index lifecycle and persistence` 针对性加固：

```
痛点1：标签发现阻塞界面
  upstream 用应用级模态 QProgressDialog（"Loading Labels"）逐文件检查
  JSON 是否存在 —— 远程存储 + 3.8 万张图，打开数据集期间整个窗口被锁死。

痛点2：重建即停服
  Rebuild 在原库上 _clear_all + 批量插入，期间筛选要么读到半空数据、要么
  整体不可用；取消或解析异常时事务边界不清，可能留下脏库。

痛点3：索引失败拖垮保存
  标签保存路径与索引同步耦合 —— 索引写失败会让用户以为"保存失败"，
  实际 JSON 已落盘，但用户重画、丢数据。
```

---

## 方案：三大支柱

| 支柱 | 核心机制 | 解决的痛点 |
|------|---------|-----------|
| **生命周期状态机** | 6 态 `missing / cached_unverified / syncing / ready / stale / failed` + 持久化身份校验 | 缓存归属不清、状态可观测性 |
| **原子化重建** | staging 临时库（`delete` journal）+ `integrity_check` + `os.replace` | 痛点 2 |
| **标签发现路径短路** | 在原 `LabelCheckWorker` 链路前加缓存优先短路 + 移除模态对话框（worker 本身未重写）；保存原子化 + 索引同步失败只置 stale | 痛点 1、3 |

---

## 技术亮点

### 1. 6 态状态机 + 持久化身份校验

索引不再只有「有/无」两态，而是一个可观测的有限状态机：

```
missing ──打开有缓存──► cached_unverified ──校验通过──► syncing ──完成──► ready
                                 │                          │             │
                                 └──────── 不匹配 ──────────►┴── 异常 ───► failed
                                                                       │
                                                  保存同步失败 ──────► stale
```

每个缓存文件通过 `dataset_root` 的 SHA256 摘要前 16 位命名（`make_db_path`），独立隔离不同数据集。缓存内的 `dataset_meta` 表持久化**身份指纹**：

| 元数据键 | 含义 |
|---------|------|
| `dataset_root` | 数据集根目录规范化绝对路径 |
| `output_dir` | JSON 输出目录 |
| `build_state` | 构建完成时的状态（`ready`） |
| `completed_at` | 完成时间戳 |
| `file_count` / `shape_count` | 文件数 / shape 数 |

打开缓存时 `is_compatible()` 比对指纹——**跨数据集误用、缓存搬家、JSON 目录切换**都会被识别并拒绝挂载，回退到全量重建而非读到错误数据。

### 2. staging 库原子重建（核心）

Rebuild **绝不**在原库上动刀，而是在同目录开一个 staging 临时库（`make_staging_db_path`，后缀 `.rebuild-<uuid>.tmp`）：

```
正式库 (WAL, 持续可读)           staging 库 (delete journal, 全量重建中)
   │                                       │
   │  筛选/标签状态照常查询                  │  _clear_all → _insert_files
   │                                       │  → integrity_check()
   │                                       ▼
   │                              通过：os.replace(staged, target) ◄── 原子切换
   │                                       │
   └──── 重建期间查询不受影响 ◄────────────┘ 失败/取消：remove_database_files(staged)
```

关键不变量：
- **旧库重建期持续可读**：筛选、标签状态恢复照常走旧库，无停服窗口
- **取消走 rollback 而非 commit**：`_insert_files` 每批检测 `cancel_check()`，取消即 `self._conn.rollback()` 并清理 staging 文件，正式库零污染
- **integrity_check 是切换闸门**：staging 库必须通过完整性检查，结果才会 `install_staged_database()` 原子替换；`install_staged_database` 还会先清掉 target 的 `-wal/-shm` sidecar 再 `os.replace`
- **worker 线程隔离**：SQLite 连接不能跨线程，worker 在 `run()` 内部创建自己的 `DatasetFilterIndex` 实例，rebuild 时显式 `journal_mode="delete"`

### 3. 标签发现路径：移除模态对话框 + 缓存优先短路

这条线改的是「打开数据集时标签存在性检查的**编排方式**」，而非推倒重写整条加载链路。改动有两部分：

```
打开数据集（import_image_folder）
   │
   ├─ 扫描所有图片 → self._dataset_all_image_files（完整未过滤列表）
   │
   ├─ _attach_existing_dataset_index(dirpath, image_files)
   │     │
   │     ├─ 存在身份匹配且 ready 的缓存？
   │     │     YES ──► _apply_cached_dataset_statuses()
   │     │              │ 直接从 SQLite 读 INDEX_STATUS_MISSING（无远程 IO）
   │     │              │ 按 500 条/批 QTimer.singleShot(0,...) 异步派发
   │     │              │ → _on_label_check_batch()
   │     │              │ 同时把 label_paths 推给 inspector
   │     │              ▼
   │     │            _schedule_dataset_index_refresh()
   │     │              （1500ms 后台增量校验）
   │     │
   │     └─ NO 缓存 ──► _start_label_check_worker()（非模态）
   │                     进度通过状态栏显示，不再锁界面
```

**LabelCheckWorker**（`label_widget.py:164`）本身**没有重写**——它仍是那个逐文件检查 JSON 是否存在的后台线程。改的只是它的**调用编排**：从"必走、必然弹模态框"降级为"无缓存时的回退路径"。一旦 refresh/rebuild 完成，标签状态直接从索引恢复，零远程文件系统调用。换句话说，这是一次**入口短路 + 编排重排**，不是加载逻辑的重写。

### 4. 保存解耦：JSON 是唯一真相源

`label_file.py` 的 `LabelFile.save()` 改为**原子写**：

```python
# 同目录临时文件 → fsync → os.replace
file_descriptor, temporary_path = tempfile.mkstemp(...)
with os.fdopen(file_descriptor, "w", encoding="utf-8") as f:
    json.dump(...); f.flush(); os.fsync(f.fileno())
os.replace(temporary_path, filename)   # 原子替换
```

保存成功后调用 `_sync_dataset_index_after_save(image_path)`：
- worker 正在跑 → 图片加入 `_pending_dataset_index_refresh_files`，worker 结束后 `_refresh_pending_dataset_index_files()` 补同步
- worker 空闲 → 立即 `refresh_file()` 单条更新

**关键契约**（代码注释原话的精神）：*JSON is authoritative. A derived-index failure is isolated and retried later; it must never turn a successful label save into a failed save operation.* —— 索引同步失败只把状态置为 `stale` 等待后台重试，**绝不会让一次成功的 JSON 保存对用户显示为失败**。

### 5. 并发读取 + 单线程批量写

`_insert_files` 的并发模型针对 SQLite 的"单写多读"特性设计：

- **4 worker `ThreadPoolExecutor`**（`INDEX_READ_WORKERS = 4`）并行解析 JSON（纯 CPU+IO，无 DB 操作）
- **64 条/批**（`INDEX_READ_BATCH_SIZE = 64`）喂给线程池
- 主线程单线程批量 `INSERT`，避免 SQLite 写锁竞争
- `_prepare_index_file` 是 `@classmethod`，纯解析、零 DB IO，完美适配多线程

### 6. schema 版本化 + 损坏即重建

`SCHEMA_VERSION = "2"` 写入 `dataset_meta`。打开缓存时若版本不匹配，**自动重建**而非报错退出——因为索引是派生的，重建零数据风险。这也是「派生缓存」设计哲学的直接收益：损坏了直接扔掉重来，JSON 永远在。

---

## 与模块 11 的关系

两篇共享 `dataset_filter_index.py` 这一个文件，但**视角互补不重叠**：

| | 模块 11：筛选系统 | 本功能：索引生命周期工程化 |
|---|---|---|
| **目的** | 解决"5000 图筛选卡死" | 解决"索引本身的健壮性与标签加载体验" |
| **视角** | 把索引当作筛选的**加速器**（`FilterEngine` 优先 `query()` 否则回退扫描） | 把索引当作需要工程化的**独立子系统**（状态机/原子重建/解耦） |
| **触发场景** | 用户设置筛选条件 | 打开数据集 / 手动 Rebuild / 保存标注 |
| **关注点** | 匹配语义（label OR within set，再与 gid/shape_type AND） | 生命周期正确性、原子性、失败隔离 |

模块 11 回答"索引怎么加速筛选"，本篇回答"索引怎么不炸、怎么不阻塞、怎么不拖垮保存"。两者是同一个派生索引在「加速用途」和「工程健壮性」两条正交轴线上的展开。

---

## 代码定位

| 位置 | 说明 |
|------|------|
| [`dataset_filter_index.py:34-39`](../../anylabeling/views/labeling/dataset_filter_index.py) | 6 态状态机常量 `DATASET_INDEX_MISSING/CACHED/SYNCING/READY/STALE/FAILED` |
| [`dataset_filter_index.py:195`](../../anylabeling/views/labeling/dataset_filter_index.py) | `snapshot_state()` 读取缓存构建状态 |
| [`dataset_filter_index.py:213`](../../anylabeling/views/labeling/dataset_filter_index.py) | `is_compatible()` 身份指纹校验 |
| [`dataset_filter_index.py:255`](../../anylabeling/views/labeling/dataset_filter_index.py) | `integrity_check()` 切换闸门 |
| [`dataset_filter_index.py:338`](../../anylabeling/views/labeling/dataset_filter_index.py) | `rebuild()` 重建入口（`_clear_all` → `_insert_files` → `_write_snapshot_metadata`） |
| [`dataset_filter_index.py:406`](../../anylabeling/views/labeling/dataset_filter_index.py) | `_write_snapshot_metadata()` 持久化身份指纹 |
| [`dataset_filter_index.py:859`](../../anylabeling/views/labeling/dataset_filter_index.py) | `_insert_files()` 4 worker / 64 批 并发读取 + 单线程写 |
| [`dataset_filter_index.py:1287`](../../anylabeling/views/labeling/dataset_filter_index.py) | `make_db_path()` SHA256 前 16 位命名 |
| [`dataset_filter_index.py:1305`](../../anylabeling/views/labeling/dataset_filter_index.py) | `make_staging_db_path()` staging 临时库名 |
| [`dataset_filter_index.py:1310`](../../anylabeling/views/labeling/dataset_filter_index.py) | `remove_database_files()` 清理库 + `-wal/-shm` sidecar |
| [`dataset_filter_index.py:1323`](../../anylabeling/views/labeling/dataset_filter_index.py) | `install_staged_database()` `os.replace` 原子切换 |
| [`dataset_filter_index_worker.py:65`](../../anylabeling/views/labeling/dataset_filter_index_worker.py) | `DatasetIndexWorker.run()` rebuild 走 staging 库 + `journal_mode="delete"` |
| [`label_widget.py:164`](../../anylabeling/views/labeling/label_widget.py) | `LabelCheckWorker`（降级为无缓存时的标签发现） |
| [`label_widget.py:4643`](../../anylabeling/views/labeling/label_widget.py) | `_attach_existing_dataset_index()` 挂载就绪缓存 |
| [`label_widget.py:4688`](../../anylabeling/views/labeling/label_widget.py) | `_apply_cached_dataset_statuses()` 500 条/批异步派发 |
| [`label_widget.py:4712`](../../anylabeling/views/labeling/label_widget.py) | `_schedule_dataset_index_refresh()` 1500ms 延迟后台增量校验 |
| [`label_widget.py:4824`](../../anylabeling/views/labeling/label_widget.py) | `_on_dataset_index_finished()` 处理 staging 原子安装 + 失败回退 |
| [`label_widget.py:6677`](../../anylabeling/views/labeling/label_widget.py) | `_sync_dataset_index_after_save()` 保存后单条同步（失败只置 stale） |
| [`label_widget.py:8864`](../../anylabeling/views/labeling/label_widget.py) | `_start_label_check_worker()` 非模态标签发现（无缓存回退路径） |
| [`label_file.py:182`](../../anylabeling/views/labeling/label_file.py) | `LabelFile.save()` 原子写（`tempfile.mkstemp` + `fsync` + `os.replace`） |

---

## 边界处理

| 场景 | 处理 |
|------|------|
| Rebuild 期间筛选 | 旧库 WAL 持续可读，筛选照常走旧库 |
| Rebuild 取消 | `_insert_files` 每批检测 `cancel_check()`，`rollback()` + 清理 staging 文件 |
| staging `integrity_check` 失败 | 抛异常 → worker `failed.emit` → 保留旧库 → 状态置 `stale` 或 `failed` |
| `os.replace` 安装失败 | 清掉 staging，尝试重新打开旧库；旧库可用置 `stale`，不可用置 `failed` |
| 跨数据集误用缓存 | `is_compatible()` 拒绝挂载，回退全量重建 |
| schema 版本不匹配 | 自动重建，零数据风险（派生缓存可丢弃） |
| 保存时索引同步失败 | JSON 已原子落盘视为成功，索引状态置 `stale`，下次 refresh 重试 |
| 保存时 worker 正在跑 | 图片入 `_pending_dataset_index_refresh_files`，worker 结束后补同步 |
| 切换/关闭目录 | `_prepare_dataset_index_for_directory(force=True)` 取消 worker、断开连接、清 pending；磁盘缓存保留供下次复用 |
| SQLite 并发锁 | `busy_timeout=30000ms`，同步失败隔离为 `stale` 不抛到用户 |
| worker 数据集切换（中途切到别的目录） | `_on_dataset_index_finished` 比对 `worker_root` 与 `current_root`，不一致直接丢弃结果 |

---

## 测试覆盖

| 文件 | 覆盖点 |
|------|--------|
| [`tests/test_dataset_filter_index.py`](../../tests/test_dataset_filter_index.py) | 状态机、身份校验、原子重建、staging 安装、取消回滚、损坏重建 |
| [`tests/test_dataset_index_worker.py`](../../tests/test_dataset_index_worker.py) | worker 线程隔离、refresh/rebuild 双模式、进度/取消信号 |
| [`tests/test_dataset_index_widget_semantics.py`](../../tests/test_dataset_index_widget_semantics.py) | UI 集成语义：状态切换、菜单可用性 |
| [`tests/test_label_file_atomic_save.py`](../../tests/test_label_file_atomic_save.py) | JSON 原子写（临时文件 + fsync + replace + 失败清理） |

---

## 设计文档

- 📄 [**dataset_filter_index_function_record.md**](../Document-Index/feature-records/dataset_filter_index_function_record.md) — 功能记录文档（修改目的 / 影响流程 / 三个优先级 P0/P1/P2 / 依赖锚点 / 验证步骤 / 已知副作用 / 后续注意）

---

## 截图

> `[截图待补]` — 计划补充：Rebuild 进度条 + 重建期间筛选仍可查询的对比演示
