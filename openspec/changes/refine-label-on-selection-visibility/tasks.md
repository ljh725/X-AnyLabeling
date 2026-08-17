## 1. 梳理普通标签显示判定

- [ ] 1.1 在 `canvas.py` 中抽出普通标签可见性的集中判定逻辑
- [ ] 1.2 让该逻辑统一处理 `show_labels`、`label_on_selection`、`selected`、`hovered` 四类输入
- [ ] 1.3 确保 focused mode 开启时，只有选中 shape 与当前 hover shape 的标签可见

## 2. 移除交互副作用

- [ ] 2.1 定位并删除 `label_on_selection` 对点击释放选中流程的特殊分支影响
- [ ] 2.2 验证重复点击已选中 shape 时，选中/取消选中语义与标签开关无关
- [ ] 2.3 验证多选流程不会因标签开关而改变

## 3. 保持入口与配置一致

- [ ] 3.1 保持 `label_widget.py` 中菜单 action、canvas 属性和配置键同步
- [ ] 3.2 验证启动时默认值、切换时刷新、退出时配置保存三处行为一致
- [ ] 3.3 明确该逻辑仅作用于普通标签，不影响 Pose View 标签策略

## 4. 补充回归测试

- [ ] 4.1 为 focused mode 下“仅显示选中标签”补充测试
- [ ] 4.2 为 focused mode 下 hover 预览补充测试
- [ ] 4.3 为关闭 focused mode 后“显示全部普通标签”补充测试
- [ ] 4.4 为标签开关不再影响点击选中语义补充测试

## 5. 验证

- [ ] 5.1 运行 `pytest tests/test_canvas_interaction.py tests/test_size_overlay.py -q`
- [ ] 5.2 运行针对修改文件的静态检查或语法校验
- [ ] 5.3 手动验证普通模式下单选、多选、hover 标签显示与点击行为
