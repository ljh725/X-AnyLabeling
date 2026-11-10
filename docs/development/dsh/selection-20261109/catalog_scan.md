# DSH 插件市场全量目录扫描报告

- **获取时间**：2026-11-09（快照 2026-11-09T08:58 +08；线上复核 2026-11-09T09:35 +08）
- **扫描人**：catalog-scanner（共享任务 task-1）
- **工作目录**：`D:\X-AnyLabeling-4.2.1`（Windows，MSYS）
- **目标项目**：X-AnyLabeling（PyQt6 桌面标注工具，Windows）
- **目录口径**：全量，不看热门榜/搜索结果，遍历率 100%
- **机器可读产出**：`.tmp/dsh-sel-20261109/`（详见 §9）

---

## 0. 结论摘要（先看这 8 条）

1. **市场真正的完整索引 = `https://awesome-dsh-plugin.com/plugins.json`，单文件整包下载，没有分页接口、没有 per-category 分页**。`dshmarket` 插件源码里写死的常量就是它（`lib/regions.js:83`）。本次使用的快照即此文件：**12,860,854 字节，9,687 条，updated=2026-11-08，23 个分类**。
2. **`https://dshmarket.com/browse/` 不是数据源，是每日 CI 生成的静态快照页**：9463 条全部服务端渲染进 1.4MB HTML，页面里的 JS 只做前端过滤（`input#filter` 隐藏 `li`），不拉数据。页面自称 9463 与真实链接数 9463 完全一致——它没坏，只是**滞后**。
3. **9463 与 9687 的差是可精确对账的，不是"过滤/版本"差异**：页面 vs 快照的**集合差**为「页面缺 226 条（全部 added=2026-11-08）+ 页面多 2 条（已下架/改名历史条目）」，`9463 − 2 + 226 = 9687`，**分毫不差**。页面构建时间 2026-11-08 18:44:20 (+08)（HTTP `last-modified`），页脚自述 "refreshed daily by CI"。
4. **目录仍在高速增长**：复核时线上 plugins.json 已是 **count=9714、updated=2026-11-09**（比本地快照多 27 条：11-09 新增 22、11-08 新增 5，删除 0）。也就是说 **9,687 只是 2026-11-09 08:58 的切片**，选型必须锁版本。
5. **`dshmarket.com/index.json` 存在但不是目录索引**：3.92MB、4,872 条，字段为 `format/title/description/metadata/plugins`，条目含 `name/title/description/homepage/repository/metadata/versions` —— 这是 **npm 包索引**（≈ 目录中 4,870 个有 npm 包的条目），用于安装/版本，**不能替代全量目录**（无 stars/downloads/category）。
6. **全量统计**：9,687 条 / 9,687 遍历 / **三种口径重复均为 0**（owner+name、page、npm 各自唯一）；唯一 owner 6,312；npm 覆盖 4,870（50.3%），github: 安装 3,846（39.7%）；`added` 全量可解析，最早 2026-08-13。
7. **关键词初筛（A–G 七类）**：命中合计（含重叠）按类 A 412 / B 1,156 / C 1,262 / D 1,560 / E 2,221 / F 653 / G 4,566；去重后 **7,138 条**（占目录 73.7%），其中命中 ≥2 类 3,325、≥3 类 1,072。按"是否真提供工具/运行时"分为 **执行型 vs 提示词/技能/看板型**两类（见 §5）。
8. **证据层级只做到「目录级」**：完整目录筛查 ✅；作者文档 ❌、源码 ❌、实机运行 ❌（见 §7，由 Lead 继续深度核查）。

---

## 1. 数据源结论（市场真正的完整索引/分页接口）

### 1.1 证据链（4 类独立证据互相印证）

| # | 证据类型 | 具体证据 | 结论 |
|---|---|---|---|
| E1 | 已装插件源码常量 | `C:\Users\20441\.dsh\profiles\desktop\node_modules\dshmarket\lib\regions.js:83`：`const CATALOG_OFFICIAL = 'https://awesome-dsh-plugin.com/plugins.json';` | 目录源就是这个 URL |
| E2 | 同文件注释 | `registry.js:2`「Registry access: the curated list from awesome-dsh-plugin.com, fetched …」；`regions.js:77-82` 说明选用自定义域名的原因（Pages + CDN，抗 repo 改名） | 单文件拉取，非分页 |
| E3 | 中国区镜像策略 | `regions.js:100` `CATALOG_PACKAGE='dsh-plugin-catalog'`；`regions.js:124-127` 中国区 catalog 顺序 = **npm 包 → 官方 URL**；`regions.js:149-172 catalogSourcesFor()` 再把 npm 包作为 global 的兜底源 | 同一份内容的两条取数路径，仍无分页 |
| E4 | HTTP 实测 | `HEAD https://awesome-dsh-plugin.com/plugins.json` → 200、`ETag: W/"6af11d1c-c4cd45"`、`Last-Modified: Mon, 09 Nov 2026 01:08:44 GMT`、`application/json`、GET 12,897,605 B（gzip 线上 3,179,584 B） | 整包 JSON，无分页参数 |
| E5 | 页面自证 | `/browse/` HTML 首部注释：「Full catalog index. Deliberately one page rather than twenty category pages…One browsable list does the linking job」；`<script>` 仅 2 个、无 `__NEXT_DATA__`/内嵌 JSON，脚本内容是 filter 的 `addEventListener` | **服务端静态渲染 + 前端过滤**，不拉数据 |
| E6 | 站点元数据 | `/browse/` 页脚「Data: awesome-dsh-plugin · **refreshed daily by CI**」；`sitemap.xml` 仅 8 个 URL（`/`、`/zh/`、`/browse/`、`/zh/browse/`、`/install/`、`/zh/install/`、`/privacy/`、`/zh/privacy/`），**没有 per-plugin 或 per-category 页面** | 无分页可抓；插件详情页在 awesome-dsh-plugin.com |

> 本机 profile 侧配置：`~/.dsh/profiles/desktop/package.json` 依赖 `dshmarket ^1.73.8` 且在 `dsh.profile.bundles` 中启用；`cordis.patch.yml` 的 `plugin-market`（`@deepseek-ai/dsh-plugin-market`）`indexes: []` —— **内置市场未配任何外部索引，实际目录能力全部来自 dshmarket + 上述 plugins.json**。

### 1.2 `/browse/` 的渲染方式（实测属性）

| 属性 | 值 |
|---|---|
| HTTP | 200，`text/html; charset=utf-8`，`Last-Modified: Sun, 08 Nov 2026 10:44:20 GMT`（= 2026-11-08 18:44:20 +08） |
| 体积 | 1,402,142 字节（wire 221,604 B，gzip 后约 16%） |
| 全量链接 | HTML 里 `https://awesome-dsh-plugin.com/p/…` **唯一链接 9,463 个**（与自称 9,463 一致） |
| 分类导航 | 23 个 `<a href="#slug">名称<small>N</small></a>`，N 之和 = **9,463** |
| 数据注入 | 无（`jsonInHtml=False`、`hasNextData=False`） |
| 脚本 | 2 个 `<script>`；唯一功能是 `input#filter` 的客户端过滤（`li.hidden = !hit`、空分类 `section.hidden`） |
| 分页 | 无（单页全量；页码/`?page=` 均无） |

### 1.3 端点探测结果（含失败项，均为实测）

| 方法 | URL | 状态 | 大小 | 判定 |
|---|---|---|---|---|
| HEAD/GET | `https://awesome-dsh-plugin.com/plugins.json` | 200 | 12,897,605 B | ✅ **权威全量目录** |
| HEAD | `https://awesome-dsh-plugin.com/updates.json` | 200 | — | changelog 源（`dshmarket/lib/changelog.js:33`） |
| GET | `https://dshmarket.com/browse/` | 200 | 1,402,142 B | 静态快照页（不是数据源） |
| GET | `https://dshmarket.com/index.json` | 200 | 3,922,837 B | npm 包索引（4,872 条），非目录 |
| GET | `https://dshmarket.com/sitemap.xml` | 200 | 3,349 B | 8 个站点页 URL，无插件页 |
| GET | `https://dshmarket.com/robots.txt` | 200 | 67 B | `Allow: /` + sitemap 指向 |
| GET | `https://dshmarket.com/plugins.json` | **404** | — | 无 |
| GET | `https://dshmarket.com/catalog.json` | **404** | — | 无 |
| GET | `https://dshmarket.com/data/plugins.json` | **404** | — | 无 |
| GET | `https://dshmarket.com/api/plugins` | **404** | — | 无 |
| GET | `https://dshmarket.com/api/catalog` | **404** | — | 无 |
| GET | `https://dshmarket.com/api/v1/plugins` | **404** | — | 无 |
| GET | `https://dshmarket.com/browse.json` | **404** | — | 无 |
| GET | `https://dshmarket.com/updates.json` | **404** | — | 无 |
| GET | `https://dshmarket.com/plugins/index.json` | **404** | — | 无 |

> 失败项统计：**9 个猜测端点 404（HTTPError）**；无超时、无 TLS 失败。另有两处**工具侧**限制（非站点失败）：① `web_fetch` 抓 `/browse/` 会在约 70KB 处截断（只拿到 634/9,463 链接），改用 Python urllib 全量下载后完整；② `web_fetch` 抓 sitemap.xml 曾一次 `TypeError: fetch failed`，urllib 重试 200 —— 正式取数一律用 urllib，不用 web_fetch。

### 1.4 结论：**实际使用的是哪个数据源？是否等同 `/browse/`？差多少？**

- **实际数据源**：`https://awesome-dsh-plugin.com/plugins.json`（dshmarket 插件整包下载；中国区镜像为 npm 包 `dsh-plugin-catalog`，内容同源）。
- **它不是 `/browse/` 的"背后接口"，而是 `/browse/` 的上游**：`/browse/` 是这份 JSON 的每日 CI 静态快照。二者**不等同**。
- **差多少**：页面 9,463 vs 快照 9,687 → **净差 224**；按集合差拆解为 **页面缺 226 / 页面多 2**（§2）。以线上最新 JSON（9,714）计，页面滞后 **251** 条。
- **选型口径建议**：以 `plugins.json` 为准（信息最全：stars/downloads/capabilities/install/added）；`/browse/` 只适合人工浏览，**不可当全量清单**（会漏约 2.4% 最新插件）。

---

## 2. 页面 vs JSON 数量差异（9,463 / 9,687 / 9,714）

### 2.1 三个口径并存

| 口径 | 条目数 | 时点/来源 | 性质 |
|---|---|---|---|
| `/browse/` 页面 | **9,463** | 2026-11-08 18:44:20 +08（`last-modified`；页脚 "refreshed daily by CI"） | 静态 CI 快照，滞后 |
| `plugins.json` 本地快照 | **9,687** | `updated=2026-11-08`，抓取 2026-11-09 08:58 +08 | 权威目录（本次统计基准） |
| `plugins.json` 线上复核 | **9,714** | `updated=2026-11-09`，`last-modified` 2026-11-09 09:08:44 +08 | 仍在增长的实时值 |

### 2.2 集合差（可证伪的对账，非推算）

把页面 HTML 里 9,463 个 `/p/` URL 与快照 9,687 个 `page` 字段做**集合运算**：

| 指标 | 值 | 说明 |
|---|---|---|
| JSON `page` 唯一数 | 9,687 | 无重复 |
| 页面 `/p/` 唯一链接数 | 9,463 | 无重复 |
| **页面缺少（JSON 有、页面无）** | **226** | **全部 added = 2026-11-08**（11-07 及更早 = 0） |
| **页面多出（页面有、JSON 无）** | **2** | `ltmroberthk915/markpilot--dsh-markdown-typora`（remote）、`qiaohelenjoe/dsh-app--plugin`（docs）—— 快照前已下架/改名 |
| 对账 | **9,463 − 2 + 226 = 9,687** ✅ | 与快照条目数完全相等 |

- 缺失项 added 日期：仅 `{2026-11-08: 226}`（最小=最大=2026-11-08）。
- 页面多出的 2 条正好解释了"每类 missing ≠ diff"的 2 个例外：`remote` diff 7 / missing 8、`docs` diff 9 / missing 10（各多 1 条历史条目）。
- 为什么**不能**用「11-07 + 11-08 日增量 = 156 + 231 = 387」去推算 224：日增量是"当天入库总量"，而差值只取决于**页面构建时刻之后**的增量，且期间有 2 条下架。所以必须用集合差，实测结果如上。

### 2.3 每类 page vs JSON 对账表（23 类）

| 分类 | JSON(9687) | 页面(9463) | 净差 | 页面缺失 | 备注 |
|---|---:|---:|---:|---:|---|
| ui | 1,925 | 1,870 | 55 | 55 | |
| tools | 1,313 | 1,284 | 29 | 29 | |
| session | 729 | 710 | 19 | 19 | |
| workflow | 569 | 554 | 15 | 15 | |
| dev | 551 | 543 | 8 | 8 | |
| usage | 512 | 501 | 11 | 11 | |
| model | 498 | 486 | 12 | 12 | |
| memory | 426 | 420 | 6 | 6 | |
| theme | 369 | 359 | 10 | 10 | |
| skill | 343 | 333 | 10 | 10 | |
| notify | 329 | 322 | 7 | 7 | |
| fun | 325 | 319 | 6 | 6 | |
| remote | 280 | 273 | 7 | 8 | +1 页面多出 |
| security | 253 | 247 | 6 | 6 | |
| browser | 200 | 195 | 5 | 5 | |
| vision | 181 | 180 | 1 | 1 | |
| git | 179 | 178 | 1 | 1 | |
| docs | 176 | 167 | 9 | 10 | +1 页面多出 |
| market | 130 | 128 | 2 | 2 | |
| voice | 128 | 125 | 3 | 3 | |
| identity | 117 | 116 | 1 | 1 | |
| wsl | 87 | 87 | 0 | 0 | |
| agi | 67 | 66 | 1 | 1 | |
| **合计** | **9,687** | **9,463** | **224** | **226** | −2 |

### 2.4 机制结论

`plugins.json` 由上游 CI 多次重建（2026-11-08 日间 → 2026-11-09 09:08 又有一次）；`dshmarket.com/browse/` 由**每日一次的 CI** 重新生成静态页（页脚与 sitemap `changefreq=daily` 均自述）。因此：

- 页面 = 某一时刻（2026-11-08 18:44 +08）的目录**真子集**（+2 条已下架历史条目）；
- 差值 = 该时刻之后的净新增（226 新增 − 2 下架 = 224）；
- 抓取时（2026-11-09 08:58）目录已达 9,687；几小时后（09:35）线上已 9,714。

**这不影响"全量扫描"的有效性**：本次以 `plugins.json` 为基准，9,687/9,687 全遍历；页面仅用于交叉验证与版本差解释。

---

## 3. 全量目录统计（基于 `.tmp/dsh-sel-20261109/plugins_raw.json`）

### 3.1 基础

| 指标 | 值 |
|---|---|
| 文件 | `.tmp/dsh-sel-20261109/plugins_raw.json`，12,860,854 字节 |
| 顶层 | `name=awesome-dsh-plugin`、`url=https://awesome-dsh-plugin.com`、`source=github.com/awesome-dsh-plugin/awesome-dsh-plugin`、`updated=2026-11-08` |
| 声明 `count` | **9,687** |
| 实际解析（遍历） | **9,687 / 9,687 = 100%**（0 条解析失败） |
| 分类数 | 23（全部命中 `categories` 字典，**未知分类 0**） |
| 唯一 owner | 6,312 |
| 有 npm 包 | 4,870（50.3%） |
| `install` 为 `dsh plugin --profile web add github:…` | 3,846（39.7%） |
| stars 有值 | 9,047（合计 685,066；最高 92,724） |
| downloads 有值 | 4,841（合计 20,502,713） |

### 3.2 缺失字段（共 9,687 条）

| 字段 | 缺失数 | 占比 | 影响 |
|---|---:|---:|---|
| `description.en` / `description.zh` | **0** / **0** | 0% | 双语描述齐全（本次初筛主要依据） |
| `install` / `added` / `name` / `owner` / `url` / `page` / `category` | 0 | 0% | 每条都可安装、可定位 |
| `npm` / `version` | **4,817** | 49.7% | 一半插件只能 github:/tgz 安装，版本不可 pin |
| `downloads` / `downloadsStart` / `downloadsEnd` / `downloadsCheckedAt` | 4,846 | 50.0% | 下载量只覆盖 npm 安装者，是**偏置指标** |
| `stars` | 640 | 6.6% | 少数无 GitHub 数据 |
| `capabilities` | **2,116** | 21.8% | 1/5 插件无能力声明 → "执行型/提示词型"分档对这些条目不可靠 |
| `capabilityRedLines` | 8,725 | 90.1% | 红线声明基本缺失（安全性只能靠源码审） |
| `capabilityCheckedAt` | 818 | 8.4% | |
| `icon` | 8,722 | 90.0% | 目录质量整体偏"机器自动收录" |

### 3.3 分类分布（JSON 全量，含页面差值）

| 分类 | slug | 条目数 | 占比 |
|---|---|---:|---:|
| UI 增强 | ui | 1,925 | 19.9% |
| 工具与能力 | tools | 1,313 | 13.6% |
| 会话与消息 | session | 729 | 7.5% |
| 工作流与自动化 | workflow | 569 | 5.9% |
| 开发与运行时 | dev | 551 | 5.7% |
| 用量与计费 | usage | 512 | 5.3% |
| 模型与账号接入 | model | 498 | 5.1% |
| 记忆 | memory | 426 | 4.4% |
| 主题与外观 | theme | 369 | 3.8% |
| 技能包 | skill | 343 | 3.5% |
| 通知与集成 | notify | 329 | 3.4% |
| 娱乐 | fun | 325 | 3.4% |
| 远程与移动端 | remote | 280 | 2.9% |
| 安全与权限 | security | 253 | 2.6% |
| 浏览器与网页 | browser | 200 | 2.1% |
| 视觉与多模态 | vision | 181 | 1.9% |
| Git 与代码评审 | git | 179 | 1.8% |
| 文档与渲染 | docs | 176 | 1.8% |
| 插件市场与管理 | market | 130 | 1.3% |
| 语音与音频 | voice | 128 | 1.3% |
| 身份与通信 | identity | 117 | 1.2% |
| WSL 与 Windows 互操作 | wsl | 87 | 0.9% |
| AGI 架构探索 | agi | 67 | 0.7% |
| **合计** | 23 类 | **9,687** | 100% |

### 3.4 重复项（三种口径，均为 0）

| 口径 | 重复组 | 冗余条数 | 唯一值数 | 结论 |
|---|---:|---:|---:|---|
| `owner + name`（lower） | **0** | **0** | 9,687 | 无同名同作者 |
| `page`（URL） | **0** | **0** | 9,687 | 无重复详情页 |
| `npm`（包名，lower） | **0** | **0** | 4,870 | 有 npm 的条目里无重复包 |
| `url`（GitHub 仓库） | 未计入重复 | — | — | 一个仓库多包属正常（如 `zhu1090093659/dsh-web#packages/...`），非重复 |

> 说明：目录本身已做过 `owner+name` 去重（这是它的收录键），所以三种口径都干净。**"同仓库多插件"**（`#packages/...` 后缀）是真实的多包仓库形态，不应视为重复。

### 3.5 `added` 日期分布

| 指标 | 值 |
|---|---|
| 可解析 / 空 | 9,687 / 0 |
| 最早 ~ 最新 | **2026-08-13 ~ 2026-11-08** |
| 近 7 天（11-03~11-09） | **1,213** |
| 近 30 天（10-11~11-09） | **5,274**（54.4%） |
| 月度 | 2026-08: 2,843 / 2026-09: 1,471 / 2026-10: 3,781 / 2026-11(1–8日): 1,592 |

最近 10 天逐日：`10-31:182, 11-01:171, 11-02:208, 11-03:171, 11-04:222, 11-05:238, 11-06:195, 11-07:156, 11-08:231, 11-09:0`（快照抓取时 11-09 尚未入库；线上复核时 11-09 已新增 22 条）。

### 3.6 `capabilities` 词表（前 10，共出现 28,626 次）

| 能力 | 次数 | 含义 |
|---|---:|---|
| `fs-read` | 6,556 | 读文件 |
| `fs-write` | 5,263 | 写文件 |
| `env` | 5,257 | 读环境变量 |
| `network` | 5,234 | 联网 |
| `shell` | 3,406 | 执行 shell |
| `credentials` | 897 | 触碰凭据 |
| `llm` | 796 | 调用模型 |
| `dynamic-code` | 517 | 动态执行代码 |
| `host-runtime` | 507 | 宿主运行时 |
| `subagent` | 193 | 派生子代理 |

> 这 10 个值就是全目录的能力词表（`capabilityRedLines` 90% 为空）。本报告的"执行型"分档即基于此词表 + 是否带 npm/install 运行时。

---

## 4. 关键词初筛方法与口径

### 4.1 匹配口径

- **字段**：`name` + `owner` + `description.en` + `description.zh`（逐条，大小写不敏感；中文为子串匹配）。
- **关键词数**：7 类共 **141 个**中英文关键词（A 18 / B 23 / C 27 / D 22 / E 19 / F 13 / G 19；定义见 `.tmp/dsh-sel-20261109/analyze_market.py` 的 `BUCKETS`）。
- **分档**：
  - **执行型** = `capabilities` ∩ {`shell`,`dynamic-code`,`network`,`subagent`,`browser`,`desktop`,`gui`,`screenshot`,`vision`,`ocr`,`mcp`,`tool`,`computer-use`,`pty`,`fs-write`…} 非空（即有工具/命令/运行时）；
  - **提示词/技能/看板型** = 其余（纯 prompt/skill/看板/UI 覆盖）。
- **评分**（用于排序，不代表质量）：跨类命中数 > `stars`（≤500 计 2 分/星）> `downloads`（每 20 次 1 分）> 有 npm（+30）> 执行型（+40）。
- **CSV 全量**：`.tmp/dsh-sel-20261109/candidates.csv`（7,138 行，UTF-8 BOM，19 列：`rank,buckets,kind,name,owner,category,install,npm,version,stars,downloads,capabilities,keywords,added,page,url,desc_zh,desc_en,score`）。

### 4.2 七类命中统计

| 类别 | 关键词主题 | 命中 | 执行型 | 提示词/技能/看板型 |
|---|---|---:|---:|---:|
| **A** 需求澄清与需求记录 | clarify/question/requirement/spec/intent/需求/澄清/追问/问卷 | **412** | 276 | 136 |
| **B** 验收标准与任务规划 | acceptance/criteria/plan/task/roadmap/milestone/验收/计划/里程碑/拆解 | **1,156** | 876 | 280 |
| **C** 实现/排错/测试/代码复核 | lsp/ast/test/pytest/debug/review/lint/refactor/代码/测试/排错/复核 | **1,262** | 909 | 353 |
| **D** 持续执行/有限重试/中断恢复 | goal/loop/continue/retry/resume/checkpoint/autonomous/续跑/中断/恢复 | **1,560** | 1,182 | 378 |
| **E** 浏览器/桌面操作 | browser/playwright/chrome/computer-use/desktop/screenshot/gui/浏览器/桌面/截图 | **2,221** | 1,621 | 600 |
| **F** 截图理解与视觉验收 | vision/screenshot/ocr/visual/multimodal/看图/视觉/多模态 | **653** | 510 | 143 |
| **G** 项目状态与交付证据保存 | session/trace/evidence/artifact/report/memory/证据/报告/记忆/会话/留痕 | **4,566** | 3,410 | 1,156 |
| **跨类去重后唯一** | — | **7,138** | — | — |

- 重叠：命中 ≥2 类 **3,325**；≥3 类 **1,072**（说明"多阶段一体"的插件不少，如 `dsh-expert-mode` 一次覆盖 A/B/C/D/E/G）。
- **重要局限**：`G` 类占目录 47%，因为它包含了几乎所有插件都会写的 `session`/`memory`/`report` 词 → **G 类召回过宽，精确率低**；同理 `E`/`D` 含大量桌宠/皮肤/通知类噪声。候选清单只用于"缩小到 7,138 → 每类 10~25 条"，**不等于可用性结论**。

---

## 5. 候选清单（按流水线 7 阶段 × 执行型优先）

> 排序参考 `score`（跨类命中+热度+执行型），**已剔除**明显不符项目需求的高热噪声（余额挂件、皮肤、桌宠等）。每条只代表"目录描述声称"，**未读 README、未看源码、未实机跑**（见 §7）。

### A. 需求澄清与需求记录

| 名称 | owner | 分类 | 类型 | ★ | 下载 | 安装 | 一句话 |
|---|---|---|---|---:|---:|---|---|
| `dsh-doublecheck` | PerryLink | workflow | 执行型 | 58 | 4,741 | `dsh plugin --profile web add dsh-doublecheck` | 工程纪律守门：**动笔前审讯需求**、红绿测试证据门、交付后对抗评审 |
| `dsh-personal-workbench` | Dely0 | workflow | 执行型 | 46 | 3,503 | `dsh plugin --profile web add @dely0/dsh-personal-workbench` | 日历+层级任务：**AI 辅助澄清、拆解、执行（用户验收）与复盘** |
| `dsh-qa` | naodeng | workflow | 执行型 | 33 | 1,914 | `dsh plugin --profile web add dsh-qa` | QA 工作台：**需求/用例/缺陷/里程碑/报告/审批门禁**（18 个工具+浏览器 UI） |
| `dsh-expert-mode` | Asher-2000 | tools | 执行型 | 14 | — | `dsh plugin --profile web add github:Asher-2000/dsh-expert-mode` | 五段式质量门禁：**需求澄清→实现→验证→独立评审→集成**（最多回炉 2 轮） |
| `ouroboros` | Q00 | workflow | 提示词型 | 6,308 | — | `dsh plugin --profile web add github:Q00/ouroboros#path:/integrations/dsh-plugin` | 36 个工具覆盖**需求访谈/Seed/执行/评估**（MCP 纯配置包） |
| `dsh-prompt-enhance` | rongxingda | session | 执行型 | 34 | 9,258 | `dsh plugin --profile web add dsh-prompt-enhance` | 把草稿改写成含**验收标准/边界条件**的结构化提示词（非程序员友好） |

### B. 验收标准与任务规划

| 名称 | owner | 分类 | 类型 | ★ | 下载 | 安装 | 一句话 |
|---|---|---|---|---:|---:|---|---|
| `dsh-pua` | MichengAI | agi | 执行型 | 65 | 26,965 | `dsh plugin --profile web add @michengai/dsh-pua` | 失败后促换方法 + **宣称完成前核验收据** + 可选验收循环（到命令通过/上限/用户取） |
| `dsh-swarm-orchestrator` | linkbag | workflow | 执行型 | 10 | 3,024 | `dsh plugin --profile web add dsh-swarm-orchestrator` | 架构/建造/评审/集成角色化蜂群，含**评审循环、证据合约、人工评审门**（40 测试） |
| `dwgward-dsh-hmos` | Dogwind221 | workflow | 执行型 | 0 | 1,762 | `dsh plugin --profile web add dwguard-dsh-hmos` | **四维验收任务包（可量化判据+机器可校验断言）**+ 截图/布局树/日志/SHA-256 证据包 |
| `dsh-delivery-kit` | Lucky020 | docs | 执行型 | 0 | 2,904 | `dsh plugin --profile web add dsh-delivery-kit` | 仓库→**验收/测试/上线报告 + 带截图使用说明书**（GB/T 8567-88；需 python-docx、Chrome） |
| `LoopX` | loopx-project | workflow | 提示词型 | 6,537 | — | `dsh plugin --profile web add <tgz 见 CSV>` | **Goal/Todo/门禁/证据/配额/恢复** 的本地持久状态内核（长周期 Agent） |
| `dsh-task-ledger` | cq-guojia | workflow | 提示词型 | — | 23,622 | `dsh plugin --profile web add dsh-task-ledger` | 纯文本**任务台账**：负责人/状态/下一步全程留痕，Git 同步 |

### C. 实现 / 排错 / 测试 / 代码复核

| 名称 | owner | 分类 | 类型 | ★ | 下载 | 安装 | 一句话 |
|---|---|---|---|---:|---:|---|---|
| `dsh-code-review` | MichengAI | git | 执行型 | 16 | 24,718 | `dsh plugin --profile web add @michengai/dsh-code-review` | `/review` 用**独立子 Agent 审查 Git 范围**（基准分支/未提交/某提交） |
| `dsh-auto-review` | PerryLink | security | 执行型 | 244 | 6,533 | `dsh plugin --profile web add dsh-auto-review` | 审批链上的**第二模型自动审查**，只读子代理返回 allow/deny，默认 fail-closed |
| `Aegis` | GanyuanRan | skill | 执行型 | 1,411 | — | `dsh plugin --profile web add github:GanyuanRan/Aegis` | 软件工程方法包：**基线优先规划、系统化调试、完成前验证** |
| `brooks-lint` | hyhmrright | skill | 提示词型 | 1,556 | 2,208 | `dsh plugin --profile web add brooks-lint` | 六个代码质量技能：**代码审查/架构审计/技术债/测试质量** |
| `GraphFlow` | Roarpeng | tools | 执行型 | 30 | 16,381 | `dsh plugin --profile web add @roarpeng/graphflow` | 10 个 MCP 工具：**DAG 规划、增量 AST 建图**、诊断、图谱导出 |
| `dsh-simplify` | MichengAI | dev | 执行型 | 11 | 16,895 | `dsh plugin --profile web add @michengai/dsh-simplify` | `/simplify` 在选定 Git 范围**简化/重构代码** |

### D. 持续执行 / 有限重试 / 中断恢复

| 名称 | owner | 分类 | 类型 | ★ | 下载 | 安装 | 一句话 |
|---|---|---|---|---:|---:|---|---|
| `dsh-auto-continue` | HsiangNianian | ui | 执行型 | 187 | 10,818 | `dsh plugin --profile web add dsh-client-auto-continue` | **非人为失败（网络/超时/宿主崩溃）后自动发"继续"**，错误分类+自适应退避 |
| `dsh-rewind` | SiriLee | session | 执行型 | 245 | 35,636 | *已装 `dsh-rewind-plugin 0.19.1`* | **回退到任意更早用户消息**并可还原工作区文件（/rewind 语义） |
| `dsh-plugin-heartbeat` | LittleBlackTong | workflow | 执行型 | 3 | 3,165 | `dsh plugin --profile web add dsh-plugin-heartbeat` | 心跳 diff**待办/任务板/目标**，只在有信号时开口（L1 汇报/L2 提问/L4 升级） |
| `dsh-autonomous-restart` | meng-lx | session | 执行型 | 0 | 769 | `dsh plugin --profile web add dsh-autonomous-restart` | agent **自主发起重启**并唤醒原会话（仅 Windows，10 秒可取消倒计时） |
| `dsh-expert-mode` | Asher-2000 | tools | 执行型 | 14 | — | `dsh plugin --profile web add github:Asher-2000/dsh-expert-mode` | 任务状态机 `pending/ready/running/done/failed` + 依赖 DAG + **重试 + 崩溃恢复** |
| `dsh-context-compression-improved` | drscrewdriver | session | 执行型 | 10 | 16,669 | `dsh plugin --profile web add dsh-context-compression-improved` | 长会话压缩（代码骨架闸门），降低中断概率 |

### E. 浏览器 / 桌面操作（**本项目最关键一类**：PyQt6 桌面验证）

| 名称 | owner | 分类 | 类型 | ★ | 下载 | 安装 | 一句话 |
|---|---|---|---|---:|---:|---|---|
| `dsh-computer-use-win` | Yu-tao-Li | tools | 执行型 | 420 | 25,319 | `dsh plugin --profile web add dsh-computer-use-win` | **UI Automation 操作 Windows 桌面程序**：点击/输入/截图/识别文字（网页走自己的后台浏览器） |
| `dsh-windows-mcp` | helloHub1212 | tools | 执行型 | 132 | 422,478 | `dsh plugin --profile web add dsh-windows-mcp` | 桥接 Windows-MCP：**截屏/UI 树快照/鼠标键盘/剪贴板/进程/注册表** |
| `dsh-browser` | wqty123 | browser | 执行型 | 162 | 34,096 | `dsh plugin --profile web add dsh-builtin-browser` | 共享真实 Electron 浏览器 + **20 个 `browser_*` 工具**（CDP，人可接管） |
| `dsh-ego-browser` | Fisfzy | browser | 执行型 | 395 | 24,643 | `dsh plugin --profile web add dsh-ego-browser` | **35 个结构化工具**驱动真实 Chrome/Chromium（导航/语义快照/CDP/下载/标签页） |
| `dsh-cdp` | dougen | browser | 执行型 | 1 | 2,330 | `dsh plugin --profile web add @dougen/dsh-cdp` | 常驻 CDP 连**本机已开 Chromium**，含 **CSS/DOM/像素断言** |
| `BrowserSkill` | Tencent | browser | 提示词型 | 9,929 | 46,565 | `dsh plugin --profile web add @wxg-prc-cpg/browser-skill-dsh-plugin` | 腾讯 BrowserSkill 桥接：控制可见 Chrome/Edge Agent Window（类型存疑，待核） |

### F. 截图理解与视觉验收

| 名称 | owner | 分类 | 类型 | ★ | 下载 | 安装 | 一句话 |
|---|---|---|---|---:|---:|---|---|
| `modlens` | liustack | vision | 执行型 | 4,725 | 257,137 | *已装 `@liustack/modlens 3.27.2`* | 纯文本模型视觉桥：输出**结构化 JSON 证据（OCR/版面/语义）** |
| `dsh-vision-router` | ysr666 | vision | 执行型 | 1,211 | 56,719 | `dsh plugin --profile web add dsh-vision-router` | 免 Key 视觉链 + **像素级工具**（定位/裁剪/像素对比/取色/OCR/抠图/截图） |
| `dsh-vision-toolkit` | Anionex | vision | 执行型 | 922 | 15,049 | `dsh plugin --profile web add @anionex/dsh-vision-toolkit` | 图片问答/多图比较/**长截图 OCR/截图还原 UI/元素定位/像素对比** |
| `dsh-computer-use-win` | Yu-tao-Li | tools | 执行型 | 420 | 25,319 | `dsh plugin --profile web add dsh-computer-use-win` | 桌面截图 + OCR（与 E 类同一条，**桌面验收链路核心**） |
| `dsh-video-storyboard` | SAOS-3624 | vision | 执行型 | 384 | 24,456 | `dsh plugin --profile web add dsh-video-storyboard` | 视频→可寻址宫格图（编号/时间/台词），`video_zoom` 高清重看 |

### G. 项目状态与交付证据保存

| 名称 | owner | 分类 | 类型 | ★ | 下载 | 安装 | 一句话 |
|---|---|---|---|---:|---:|---|---|
| `billion-context` | ranxianglei | session | 执行型 | 4,666 | 3,023,850 | `dsh plugin --profile web add billion-context` | 上下文压缩（小窗口省 token / 数月级超长单会话） |
| `dsh-context` | bowenliang123 | usage | 执行型 | 4,559 | 400,497 | *已装 `dsh-context 0.80.2`* | 上下文洞察面板 + `/context`（组成/演进/压缩事件） |
| `dsh-cost-meter` | Han-1413141 | usage | 执行型 | 649 | 138,437 | `dsh plugin --profile web add dsh-cost-meter` | 会话/当日费用、预算图框、**历史看板** |
| `dsh-mnemon` | omdsh-dev | memory | 执行型 | 920 | 100,427 | `dsh plugin --profile web add dsh-mnemon` | 跨 Agent、本地优先的**持久记忆** |
| `clearai-dsh` | Clearailhc | agi | 执行型 | 690 | 7,882 | `dsh plugin --profile web add clearai-dsh` | 以证据为准的预设：**每步需系统核验的观测**，整场会话折成**可重放账本** |
| `dsh-archive-manager` | MichengAI | session | 执行型 | 311 | 106,124 | `dsh plugin --profile web add @michengai/dsh-archive-manager` | 归档会话的**搜索/恢复/删除** |
| `dsh-task-ledger` | cq-guojia | workflow | 提示词型 | — | 23,622 | `dsh plugin --profile web add dsh-task-ledger` | 任务台账留痕（见 B 类） |

### 5.x 组合建议（只作初筛输入，非结论）

- **最小可用流水线（全部执行型，安装命令均在上表）**：
  `dsh-doublecheck`（A 澄清）→ `dsh-pua` 或 `dwgward-dsh-hmos`（B 验收判据）→ `dsh-code-review` + `Aegis`（C 实现/复核）→ `dsh-auto-continue` + `dsh-expert-mode`（D 续跑/恢复）→ `dsh-computer-use-win` + `dsh-windows-mcp`（E 桌面操作）→ `dsh-vision-router` 或已装 `modlens`（F 截图验收）→ `dsh-cost-meter` + `dsh-task-ledger`（G 证据/成本）。
- **已装可直接用的底座**（来自 profile，非本次安装）：`@liustack/modlens`（F）、`dsh-context`（G）、`dsh-rewind-plugin`（D）、`@linxin666/dsh-client-ui-task-board`（B）、`dsh-better-sidebar`、`dsh-ops`、`cc-safety-net`。
- **缺口（目录里没有强候选）**：① 直接针对 **PyQt6 控件级断言**的插件（`dsh-computer-use-win` 的 UI Automation 最接近，但需实测 PyQt6 无障碍树是否可读）；② "自然语言需求 → 结构化验收标准"的**专用**插件（现有多为泛化 gate/台账，靠 preset 粘合）。

---

## 6. 获取失败项与已知限制

| 类型 | 项 | 结果 | 处理 |
|---|---|---|---|
| HTTP 404 | `dshmarket.com` 的 9 个 JSON/API 猜测端点（§1.3） | 全部 404 | 记录，不作为数据源 |
| 工具截断 | `web_fetch` 抓 `/browse/` 约 70KB 处截断（634/9,463 链接） | 非站点失败 | 改 Python urllib 全量 1,402,142 B |
| 工具瞬时失败 | `web_fetch` 抓 `sitemap.xml` 一次 `TypeError: fetch failed` | 非站点失败 | urllib 重试 200（3,349 B） |
| 执行器故障 | 本会话 `ops_bash` 并发时 `EXECUTOR_UNAVAILABLE`（`Niubash execution tree link count mismatch`） | 环境问题 | 脚本由 Lead 顺序执行；产出已就绪 |
| 数据时效 | 目录每天多次重建（9,687 → 9,714 仅数小时） | 固有 | 报告全程标注时点；选型须锁 commit/版本 |
| 指标偏置 | `downloads` 仅覆盖 npm 安装者（50% 条目无值） | 固有 | 排序只作参考，不作质量结论 |

---

## 7. 记录层级：这次做到了哪一层（明确边界）

| 层级 | 内容 | 状态 | 证据/说明 |
|---|---|---|---|
| **L1 完整目录筛查** | 9,687/9,687 字段级统计、三种重复口径、缺失字段、分类分布、added 分布、capabilities 词表、页面/线上 JSON/API 三方对账、A–G 关键词初筛 + CSV | ✅ **已完成** | 本报告 §1–§5；脚本可复现（§9） |
| **L2 作者文档/README** | 候选插件的 GitHub README、CHANGELOG、安装前置、DSH 版本要求、维护活跃度 | ❌ **未做** | 只用了目录内 `description.en/zh`（CSV 中截断到 220 字符）；未抓任何 README、未核 `engines.dsh` |
| **L3 源码核查** | 候选包 `package.json`/`dist` 里真实注册的工具名、权限、是否与 `capabilities` 声明一致、是否有安装脚本 | ❌ **未做** | 仅读了**本机已装 `dshmarket` 包**用于定位数据源（§1.1 E1–E3），未读任何候选插件源码 |
| **L4 实机运行验证** | 隔离 profile 试装、在 X-AnyLabeling 上跑"启动→截屏→OCR→断言"最小闭环、Windows 兼容性 | ❌ **未做** | 本次**未安装/卸载/修改任何插件或 profile**（纪律要求：只读调查） |

**→ 由 Lead 继续**：L2→L3→L4 深核（建议顺序与命令见 §8）。本报告的所有"候选"仅为**目录声明级证据**，不得当作已核实能力。

---

## 8. 待 Lead 执行清单（本会话无法完成的部分）

1. **复跑/再取数**（脚本已在 `.tmp/dsh-sel-20261109/`，纯标准库、只读、只写该目录）：
   - `python .tmp/dsh-sel-20261109/analyze_market.py`（统计+关键词+CSV）
   - `python .tmp/dsh-sel-20261109/audit_sets.py`（页面/JSON 集合差 + 线上增量 + index.json 逆向）
   - `python .tmp/dsh-sel-20261109/probe_endpoints.py`（端点/表头/页面解析）
   - 若要锁证据：重跑 `probe_endpoints.py` 时记录新 `ETag`/`Last-Modified`（目录在变）。
2. **L2 文档层**：对 §5 候选逐个抓 GitHub README + `package.json`，核对：DSH `engines.dsh` 兼容 0.2.2-rc.1、Windows 支持、外部依赖（Chrome/Python/ffmpeg）、是否需要 API Key。
3. **L3 源码层**：`npm view <pkg> version repository dist.tarball`（核包真实存在/维护度）；解包后看注册的**工具名清单**是否与宣称一致；检查有无 postinstall 脚本与网络外联。
4. **L4 实机层**：用**一次性 profile** 试装（不要动 `desktop`），在 X-AnyLabeling 上跑最小验收闭环：
   - 启动主窗口 → `dsh-computer-use-win` 截屏 → `modlens`/`dsh-vision-router` 结构化解析 → 断言"顶部菜单/图层面板"存在 → 记录证据链。
5. **风险项**：50% 插件无 npm 包（github:/tgz 安装，不可 pin 版本）；21.8% 无 `capabilities` 声明；90% 无 `capabilityRedLines` —— 安装前必须人工审权限。

---

## 9. 附录：产出文件清单与复现

### 9.1 文件清单（均在 `.tmp/dsh-sel-20261109/`）

| 文件 | 大小 | 内容 |
|---|---:|---|
| `plugins_raw.json` | 12,860,854 B | 目录快照（9687 条，本次统计基准） |
| `plugins_live_check.json` | 13,170,752 B | 线上复核 JSON（9,714 条，2026-11-09 09:35） |
| `browse.html` | 1,412,849 B | `/browse/` 全量静态页（9,463 链接） |
| `stats.json` / `stats_brief.md` | 7,304 / 3,049 B | 全量统计（机器/人读） |
| `candidates.csv` | 5,367,952 B | **7,138 条候选**（19 列，UTF-8 BOM，可直接 Excel 打开） |
| `candidates_by_bucket.md` | 56,747 B | 每类 top 25 的 Markdown 表 |
| `duplicates.txt` | 129 B | 三种口径重复明细（均为 0 组） |
| `probe.json` / `probe_brief.md` | 39,434 / 4,511 B | 端点/表头/页面解析 |
| `audit.json` / `audit_brief.md` | — | 集合差审计（9463 vs 9687 对账） |
| `index_sample.json` | — | `dshmarket.com/index.json` 前 5 条样例（npm 索引结构） |
| `analyze_market.py` / `probe_endpoints.py` / `audit_sets.py` | — | 可复现脚本（纯标准库） |

### 9.2 参考 URL

- 目录源：https://awesome-dsh-plugin.com/plugins.json ｜ 站点 https://awesome-dsh-plugin.com ｜ 更新流 https://awesome-dsh-plugin.com/updates.json
- 市场页：https://dshmarket.com/browse/ ｜ 中文 https://dshmarket.com/zh/browse/ ｜ 安装页 https://dshmarket.com/install/ ｜ npm 包索引 https://dshmarket.com/index.json
- 站点仓库：https://github.com/dsh-market/dsh-market ｜ 目录仓库：https://github.com/awesome-dsh-plugin/awesome-dsh-plugin
- 本机配置：`~/.dsh/profiles/desktop/package.json`、`~/.dsh/profiles/desktop/cordis.patch.yml`、`~/.dsh/profiles/desktop/node_modules/dshmarket/lib/regions.js`

### 9.3 关键结论一句话

> **权威全量目录是 `plugins.json`（9,687 条 @2026-11-08，现已 9,714）；`/browse/` 是它的每日 CI 静态子集（9,463，缺 226 / 多 2，可精确对账）；`index.json` 是 npm 包索引（4,872）不是目录。项目七阶段共筛出 7,138 条候选（执行型优先已分档），但文档/源码/实机三层均未验证，须由 Lead 继续深核。**
