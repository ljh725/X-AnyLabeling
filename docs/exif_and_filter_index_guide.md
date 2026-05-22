# 菜单功能技术说明：EXIF 扫描 / 数据集索引 / 全局过滤

> 本文档整理自开发对话，说明主界面菜单栏中 **Scan EXIF Orientation**、**Refresh/Rebuild Dataset Index**、**Enable Global Filter** 三个功能的实际行为、使用流程及相互关系。

---

## 1. 功能说明

### 1.1 Scan EXIF Orientation（手动扫描 EXIF 方向）

**触发位置**：主界面菜单栏 → `Scan EXIF Orientation`

**行为**：
- 扫描当前已打开目录中所有图片的 EXIF 方向标记。
- 如果发现带方向信息的图片，会弹出确认对话框：
  - 标题：`EXIF Orientation Detected`
  - 内容提示将创建备份到 `x-anylabeling-exif-backup` 目录。
- 确认后在后台批量处理，自动校正图片方向。

**成功提示**：
- 对话框标题：`EXIF Processing Complete`
- 提示内容：`Successfully processed X images.`
- 同时显示原图备份路径：`x-anylabeling-exif-backup`

**无图片时**：
- 状态栏提示：`No images to scan. Open a directory first.`

---

### 1.2 Refresh Dataset Index / Rebuild Dataset Index（数据集索引）

**触发位置**：主界面菜单栏 → `Refresh Dataset Index` / `Rebuild Dataset Index`

**行为**：
- 这两个按钮都用于构建或更新数据集派生索引缓存（SQLite）。
- **Refresh**：增量刷新，只处理新增/修改/删除的文件。
- **Rebuild**：清空旧索引后从头重建，用于索引损坏或需要完全同步的场景。
- 后台线程执行，过程中状态栏显示进度。

**过程中的状态提示**：
- 开始：`Building dataset index...`
- 进度：`Building dataset index: current/total filename`

**完成后的提示**：
```
Dataset index ready: inserted=..., updated=..., removed=..., failed=...
```

**取消时**：
- 请求取消：`Cancelling dataset index build...`
- 最终提示：`Dataset index build cancelled`

**失败时**：
- 提示：`Dataset index build failed: {message}`

---

### 1.3 Enable Global Filter（启用全局过滤保持）

**触发位置**：主界面菜单栏 → `Enable Global Filter`

**行为**：
- 这是一个开关选项（checkable）。
- **开启时**：切换图片（翻页）后，当前设置的过滤条件（label / gid / shape_type）会被保留并应用到新图片。
- **关闭时**：切换图片后，过滤条件自动清空重置。

**注意**：
- 它不控制索引构建，只控制**过滤状态的跨图片持久化**。

---

## 2. 三者之间的关系

### 2.1 EXIF 扫描 vs 数据集索引

- **完全独立**，互不依赖。
- EXIF 扫描修改的是图片文件本身（校正方向 + 备份原图）。
- 数据集索引读取的是 JSON 标注文件，构建 SQLite 缓存用于加速查询。

### 2.2 数据集索引 vs Data Inspector（数据检查器）

- 菜单中的 `Refresh/Rebuild Dataset Index` 和 Data Inspector 面板使用的是**同一套索引**（`DatasetFilterIndex`）。
- 这套索引是给**过滤导航（Filter Result Navigation）** 和 Data Inspector 的查询加速用的。
- 索引只缓存派生数据，永远不会修改原始 JSON 标注。

### 2.3 Enable Global Filter vs 过滤导航

- **Enable Global Filter** 控制的是：翻页时是否保留过滤条件。
- **Filter Result Navigation** 依赖当前过滤条件和数据集索引：
  - 启用导航前，必须先有活跃过滤条件（`has_active_filter`）。
  - 导航功能会查询数据集索引，生成匹配文件列表，然后支持在结果间跳转。
- 间接关系：如果你想连续使用过滤导航翻页，通常需要开启 `Enable Global Filter`，否则切到下一张图时过滤条件会被清空，导航就失效了。

---

## 3. 实际使用流程

```text
打开数据目录
  │
  ├─(可选) Scan EXIF Orientation
  │    ├─扫描当前图片列表
  │    ├─发现 EXIF 方向信息 -> 弹确认框
  │    └─处理完成 -> 生成 x-anylabeling-exif-backup 备份
  │
  ├─Refresh Dataset Index / Rebuild Dataset Index
  │    ├─Refresh: 增量更新索引
  │    ├─Rebuild: 删除旧索引后重建
  │    ├─后台构建 SQLite 索引
  │    └─完成后显示 Dataset index ready...
  │
  ├─设置过滤条件 (label / gid / shape_type)
  │
  ├─Enable Global Filter
  │    ├─开: 切图时保留当前过滤条件
  │    └─关: 切图时清空过滤条件
  │
  └─Filter Result Navigation
       ├─依赖当前过滤条件
       ├─依赖 Dataset Index 已就绪
       ├─生成匹配文件列表
       └─用上一条/下一条在匹配结果间跳转
```

### 推荐操作顺序

1. **打开数据目录**
2. **构建索引**：先执行 `Refresh Dataset Index`（或 `Rebuild Dataset Index`）
3. **（可选）校正图片**：如有需要，执行 `Scan EXIF Orientation`
4. **设置过滤条件**：在界面中选择 label / gid / shape_type
5. **开启全局过滤保持**：勾选 `Enable Global Filter`
6. **启用过滤导航**：开启 `Filter Result Navigation`，即可在匹配结果间跳转

---

## 4. 一句话记忆

| 功能 | 作用 |
|------|------|
| `Scan EXIF Orientation` | 修图像方向，生成备份 |
| `Dataset Index` | 给过滤/导航加速的 SQLite 缓存 |
| `Enable Global Filter` | 切图时保留过滤状态 |
