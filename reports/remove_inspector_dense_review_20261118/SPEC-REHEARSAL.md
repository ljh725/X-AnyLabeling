# OpenSpec 同步预演

在 `.tmp/retire-openspec-rehearsal/` 复制实施时的 OpenSpec 文件。按 [设计](../../openspec/changes/remove-inspector-and-dense-review/design.md) 分别比对每份主规格和 REMOVED 增量中无重复的 `### Requirement:` 标题集合。

| 主规格 | 完整退役的要求数 |
| --- | ---: |
| `duplicate-box-inspection` | 8 |
| `inspection-execution` | 8 |
| `inspection-profiles` | 8 |
| `inspection-result-navigation` | 7 |
| `inspection-review-handoff` | 8 |
| `inspection-review-queue` | 8 |
| `inspector-focused-review` | 7 |

54 条标题逐字匹配。在副本移除七份全量退役主规格，替换 `canvas-controls-recovery` 的一条要求，新增 `retired-review-data-compatibility` 的三条要求。其余画布要求标题保留。`openspec validate --specs --strict` 为 15 通过、0 失败。

副本用 `openspec archive <change> --skip-specs --yes` 复演旧密集复核（61/66）、旧界面打磨（20/20）和本变更后续可用的归档方式。三份目录移动成功，旧增量继续随各自存档。副本在模拟三份归档后运行 `openspec validate --all --strict` 为 20 通过、0 失败。
