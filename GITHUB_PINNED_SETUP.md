# GitHub 主页 Pinned 设置方案

> **目标**:把个人主页 Overview 右侧的 Pinned 卡片,从 `CVHub520/X-AnyLabeling`(别人的)换成 `ljh725/X-AnyLabeling`(你自己的 fork),点进去直接看到自己的代码。
>
> **耗时**:约 2 分钟。全部在网页操作,不需要命令行。

---

## 背景说明(为什么现在显示的是别人的仓库)

你现在打开 `https://github.com/ljh725`,右侧 Pinned 区显示的是 `CVHub520/X-AnyLabeling`,这是因为:

1. 你的仓库 `ljh725/X-AnyLabeling` 是从 `CVHub520/X-AnyLabeling` **fork** 来的,GitHub 记录了父子关系。
2. GitHub 的 Pinned 默认会把"最相关/最活跃"的仓库放上去,fork 仓库有时会被父仓库的卡片盖住。
3. 点那个卡片会跳到 `CVHub520/X-AnyLabeling`(别人的项目),而不是你的 fork。

**解决思路**:手动通过 "Customize your pins" 功能,把 CVHub520 取消、把自己的 fork 钉上去。

> ⚠️ 这个操作**只改你自己主页的展示**,不影响 CVHub520 的仓库,也不影响代码同步。纯展示层操作,零风险。

---

## 操作步骤(3 步搞定)

### 第 1 步:打开个人主页

浏览器访问:

```
https://github.com/ljh725
```

确认地址栏是你自己的用户名 `ljh725`,页面顶部能看到你的头像。

### 第 2 步:点击 "Customize your pins"

在页面**右侧**找到 **Pinned** 区块(标题叫 "Pinned" 或 "置顶")。

在这个区块的**右上角**,找到按钮:

```
┌──────────────────────────────────────┐
│  Pinned                       ┐      │
│                          ────┘      │
│  ┌────────────────────────┐          │
│  │ CVHub520/X-AnyLabeling │          │
│  └────────────────────────┘          │
│                       Customize your │  ← 点这个!
│                       pins           │
└──────────────────────────────────────┘
```

点击 **"Customize your pins"** (中文界面可能是 "自定义置顶" 或 "编辑置顶")。

会弹出一个编辑面板,带搜索框和所有仓库的复选框列表。

### 第 3 步:取消旧的,勾上新的,保存

在弹出的编辑面板里:

| 操作 | 具体动作 |
|------|----------|
| ❌ **取消勾选** | 取消 `CVHub520/X-AnyLabeling`(别人的仓库)前面的勾 |
| ✅ **勾选** | 勾上 `X-AnyLabeling`(用户名是 `ljh725` 的那个,你的 fork) |
| 💾 **保存** | 点底部的绿色按钮 **"Save changes"** |

```
编辑面板示例:
┌─────────────────────────────────────────────┐
│  Pin repositories                           │
│  ─────────────────────────────────────────  │
│  🔍 Search repositories                     │
│  ─────────────────────────────────────────  │
│  ☐ CVHub520/X-AnyLabeling   ← 取消勾选 ❌   │
│  ☑ X-AnyLabeling            ← 勾上这个 ✅   │  (owner: ljh725)
│  ☐ GenericAgent                             │
│                                             │
│                          [ Save changes ]   │  ← 点保存
└─────────────────────────────────────────────┘
```

**保存后立即生效**,刷新主页,右侧 Pinned 区就会显示你自己的 fork 卡片。

---

## 验证是否成功

设置完成后,刷新 `https://github.com/ljh725`:

- ✅ 右侧 Pinned 卡片标题显示 **`X-AnyLabeling`**(且没有 "forked from" 指向 CVHub520 的链接作为主标题)
- ✅ 点卡片 → 跳到 `https://github.com/ljh725/X-AnyLabeling`(你自己的仓库)
- ✅ 进入后能看到你的分支 `feature/selection-optimization` 和你的代码

如果点了还是跳到 CVHub520,说明勾错了仓库(勾到了父仓库)——重新进 Customize,确认勾的是 owner 为 `ljh725` 的那个。

---

## (可选)顺手改一下卡片描述

你的 fork 现在的 description 还是 CVHub520 原版的:

> "Effortless data labeling with AI support from Segment Anything and other awesome models."

建议改成你自己的描述,让卡片更清楚地表明这是定制版。

### 怎么改

1. 进入你的 fork 仓库:`https://github.com/ljh725/X-AnyLabeling`
2. 在右侧 **About** 区块右上角点 **⚙ 齿轮图标**
3. 在 **Description** 输入框填入下面任选一条:
4. (可选)在 **Topics** 输入框加几个标签:`pyqt6`, `annotation`, `pose-estimation`, `keypoint`, `labeling`
5. 点 **"Save changes"**

### Description 候选文案(任选其一)

**方案 A(简洁):**
```
基于 CVHub520/X-AnyLabeling 的个人定制版:姿态标注工作流优化
```

**方案 B(列要点):**
```
CVHub520/X-AnyLabeling 定制版。主要修改:选择优化 / Pose View / 关键点标签渲染 / Inspector 加固 / Pose QA 工具链
```

**方案 C(英文):**
```
Personal fork of CVHub520/X-AnyLabeling, focused on pose annotation workflow optimization.
```

### 推荐的 Topics 标签

```
pyqt6  annotation  pose-estimation  keypoint  labeling  tool
```

---

## 常见问题

**Q: 改了 Pinned 会影响我的代码吗?**
A: 不会。这只是主页展示设置,纯视觉层,不碰任何代码、分支、提交。

**Q: 会影响我和上游的同步吗?**
A: 不会。本地 `upstream` remote 照常工作,`git fetch upstream` 依然能拉 CVHub520 的更新。Pinned 和同步是两套独立机制。

**Q: 我能 pin 多少个仓库?**
A: 最多 6 个。你现在 pin 的不多,空间充足。

**Q: 为什么我在 Customize 里看不到 `ljh725/X-AnyLabeling`?**
A: 可能是搜索框输入了文字,清空搜索框,或翻到列表底部。你的 fork 一定在列表里(你是 owner)。

**Q: 设置后,同事打开我的主页看到的是什么?**
A: 和你看到的一样——Pinned 区显示你自己的 fork 卡片,点进去是你的代码。

---

## 附:本次定制涉及的 9 大功能模块(供 description 参考)

| 模块 | 提交数 | 说明 |
|------|--------|------|
| 🎨 选择优化 (canvas) | 12 | `_shape_hit_candidates` 多级优先级拾取算法 |
| ✨ Pose Label 关键点标签 | 14 | 新增 `pose_label/` 模块:PoseRenderer + 布局引擎 |
| 👁 Pose View 姿态视图 | 9 | 解耦、过滤驱动架构 |
| 🔍 Inspector 检查器 | 5 | FlatIndex 加固 + 外部结果导入 |
| 🤖 Pose QA 工具链 | 4 | vitpose 预标注对比 |
| 📚 文档沉淀 | 10 | 设计文档、模式卡片、规范 |
| 🐛 Label 修复 | 2 | 标签显示修复 |
| 📝 数字管理器 | 1 | 批量重命名 |
| 🔧 其他维护 | 55 | bug fix、重构、配置 |
| **总计** | **112** | 领先上游 112 个提交 |

---

*文档生成日期:2026-06-30*
*本地 git 分支:feature/selection-optimization*
