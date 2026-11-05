# X-AnyLabeling · 我的 4.2.1 修改版

基于官方 4.2.1，保留已迁移的个人改动。这里只列已提交的内容。

## 我的修改

- **编辑与选择**：批量编辑、数字键改标、选中优先级及隐藏/锁定行为调整。
- **标签显示**：仅显示选中对象的标签，保留悬停预览。
- **性能优化**：分阶段加载标注、后台搜索与审核回填，减少大数据集拖动时的重复刷新。
- **设置保存**：用户配置持久化与窗口设置恢复；恢复画布滚轮导航、填充透明度等控制。

## 我的扩展

- **画框工具**：单点拟合、拖边调整、创建十字线与四极值画框。
- **对象管理**：持久对象身份、组合筛选、聚焦与反选。
- **尺寸辅助**：矩形实时尺寸提示与最小尺寸规则。
- **视图复用**：同尺寸图片共享缩放和中心点。

- **Inspector 检查与复核**：规则方案、逐文件扫描进度、问题定位、复查与会话恢复。见[大白话操作说明](docs/zh_cn/inspector.md)。
- **Dense Review 密集复核**：按批次或逐框看已有标注，另用空间查漏检查遗漏。见[大白话操作说明](docs/zh_cn/dense_review.md)。

以上检查与复核能力已纳入本分支源码；正式质量验收与人工试用仍需按各功能记录开展。
旧版质检工具也不能视为已全部迁入。本次同步范围、测试结果与限制见[同步记录](reports/workspace_sync_20261105/README.md)。

以上依据已提交台账和实现记录整理，各项验证情况见[个人功能台账](docs/custom_changes/CATALOG-20261030.md)。

[切换到旧版](https://github.com/ljh725/X-AnyLabeling/tree/versions/4.0.0-beta.4) · [GitHub 操作说明](https://github.com/ljh725/X-AnyLabeling/blob/main/GitHub操作说明.md) · [版本与备份目录](https://github.com/ljh725/X-AnyLabeling/blob/main/版本与备份目录.md) · [原安装说明](https://github.com/ljh725/X-AnyLabeling/blob/9a37c5474c390e93243e33a88e8232a19c833280/README_zh-CN.md)

基于 [X-AnyLabeling 官方项目](https://github.com/CVHub520/X-AnyLabeling)进行个人定制，许可见 [LICENSE](LICENSE)。
