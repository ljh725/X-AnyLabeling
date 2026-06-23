# Pose QA —— 姿态标注质检工具集

对**人工 pose 标注**做批处理质检,自动发现"nose 标到脚踝""左右关键点互换"
等视觉语义错误,把全量数据压缩为 5%~10% 高风险尾部样本供人工复查。

## 这是什么

核心思路(**方式 A**):用人工标注的 person 框喂 **ViTPose**(纯 Transformer
姿态模型,ONNX 推理)预测 17 个 COCO 关键点,再与人工关键点比对 **OKS + 归一化
距离**,按分歧程度排序输出可疑清单。

```
人工 person 框 ──► ViTPose ONNX ──► 17 关键点预测
                                         │
                                         ▼
                              与人工关键点比对 OKS
                                         │
                                         ▼
                          风险分排序 ──► 尾部 5%~10% 可疑清单
```

详细设计与决策见 [`docs/pipeline_design.md`](docs/pipeline_design.md),
四层质检策略背景见 [`docs/quality_strategy.md`](docs/quality_strategy.md)。

## 目录结构

```
pose_qa/
├── README.md                          ← 本文件(总入口)
├── docs/
│   ├── pipeline_design.md             ← 完整开发文档(设计/算法/输出)
│   └── quality_strategy.md            ← 四层质检策略(L1~L4)
├── export/
│   └── export_vitpose_onnx.py         ← 步骤 1:ViTPose → ONNX
├── inference/
│   ├── vitpose_inference_demo.py      ← 步骤 2a:单图推理 + 可视化(已验证)
│   └── batch_infer.py                 ← 步骤 2b:批量推理(遍历目录)
└── qa/
    ├── pose_qa_compare.py             ← 步骤 3:OKS 比对 + 排序 + 报告
    └── export_for_inspector.py        ← 步骤 4:QA 报告 → Inspector 跳转
```

四阶段对应流水线的"导出模型 → 推理 → 比对排序 → 导入 Inspector 复查",互相解耦:
推理结果存成 `<stem>_pred.json` 后,QA 比对是**纯 CPU**,不依赖模型;最后把可疑
清单转成 Inspector 格式,在 UI 里点击跳转复查。

## 环境

需要**两个独立的 conda 环境**(别混用):

| 环境 | 用途 | 依赖 |
|------|------|------|
| `vitpose_export` | 仅导出 ONNX(一次性) | transformers, torch, torchvision, onnx, onnxscript, onnxruntime, numpy, pillow |
| `x-anylabeling-cu12` | 推理 + QA 比对(主用) | onnxruntime, opencv-python, numpy(项目自带,复用几何函数) |

```bash
# 导出环境(一次性建好,导完可退役)
conda create -n vitpose_export python=3.10 -y
conda activate vitpose_export
pip install transformers torch torchvision onnx onnxscript onnxruntime numpy pillow

# 推理/QA 环境(项目主环境,已存在)
conda activate x-anylabeling-cu12
```

## 完整运行流程

### 步骤 1:导出 ViTPose ONNX(`vitpose_export` 环境,一次性)

```cmd
conda activate vitpose_export
cd D:\xinjiegou-X-AnyLabeling-4.0.0-beta.4

python pose_qa\export\export_vitpose_onnx.py ^
    --model usyd-community/vitpose-base-simple ^
    --output D:\AI_yolo_mode\vitPose\vitpose-base-simple.onnx
```

导出完会打印 EXPORT SUMMARY,确认:
- `Keypoints K: 17`(匹配 COCO 17 点标注)
- `Heatmap size: 64 x 48`(stride 4)
- `Normalization`(推理端要照此归一化)

> **模型选择**:必须用 `vitpose-base-simple`(纯 COCO 17 点)。
> **不要**用 `vitpose-plus-*`(MoE 架构,无法导出 ONNX)。

### 步骤 2a:单图 demo(`x-anylabeling-cu12` 环境,验证用)

```cmd
conda activate x-anylabeling-cu12

python pose_qa\inference\vitpose_inference_demo.py ^
    --image D:\data\s1860.jpg ^
    --json  D:\data\s1860.json ^
    --onnx  D:\AI_yolo_mode\vitPose\vitpose-base-simple.onnx ^
    --output D:\out\s1860_demo.jpg
```

产出:
- `<output>` 可视化图(彩色=模型点+骨架,橙色空心圈=人工点)
- `<json 同目录>/<stem>_pred.json` —— 模型预测,**项目原生标注格式**
  (version/shapes[]/imagePath/...),可直接用 X-AnyLabeling 打开。shapes[]
  含 person 框(从 GT 原样复制)+ 17 个关键点 point(坐标为模型预测,置信度
  存在 shape 的 `score` 字段)。

### 步骤 2b:批量推理(`inference/batch_infer.py`)

遍历整个标注目录,为每张图生成预测 json。**文件名与 GT 同名**(`s55.json`),
因此 `--pred-dir` 必须是独立目录,避免覆盖人工标注。支持断点续跑、
JSON↔图片分目录、dry-run。为 3.5 万图准备,GPU 约半小时。

```cmd
python pose_qa\inference\batch_infer.py ^
    --json-dir   D:\data\labels ^
    --image-dir  D:\data\images ^
    --onnx       D:\AI_yolo_mode\vitPose\vitpose-base-simple.onnx ^
    --pred-dir   D:\data\preds  ^
    --workers 4
```

> ⚠️ pred 文件与 GT 同名(都叫 `s55.json`),靠**不同目录**区分:
> `--json-dir`(人工标注) vs `--pred-dir`(模型预测)。切勿设成同目录。

### 步骤 3:QA 比对 + 排序(`x-anylabeling-cu12` 环境,纯 CPU)

```cmd
python pose_qa\qa\pose_qa_compare.py ^
    --gt-dir   D:\data\labels ^
    --pred-dir D:\data\preds  ^
    --output   D:\report\pose_qa ^
    --tail-percent 10
```

产出三件套(路径前缀相同):
- `<prefix>.json` —— 完整报告(配置 + 摘要 + 每图每人 OKS)
- `<prefix>.md` —— 人类可读,含 Top-N 可疑目标表
- `<prefix>_tail.txt` —— 可疑图片名清单(可直接喂给复查工具)

### 步骤 4:导入 Inspector 跳转复查(`x-anylabeling-cu12` 环境)

把 QA 报告的可疑清单转成 Inspector 原生格式,然后在 UI 里点击 issue 直接跳转到
对应图片并选中整个 person(框 + 17 个关键点)。

**4a. 转换报告**(纯 CPU):

```cmd
python pose_qa\qa\export_for_inspector.py ^
    --qa-report D:\report\pose_qa.json ^
    --gt-dir    D:\data\labels ^
    --output    D:\report\pose_qa_inspector.json
```

默认只导出尾部可疑 person(`in_tail==true`),避免 inspector 被几万条 issue 淹没。
severity 按 risk 自动映射:>0.7 error、>0.4 warning、其余 info。每个 issue 的
`shape_index` 指向该 group 的 person 框,点击跳转高亮 person 框 + 连带选中同组
关键点。

**4b. 在 X-AnyLabeling 里导入**:

1. 打开图片目录(`Ctrl+O`),让目标图片进入 image_list(QA 的 file_path 靠
   basename 匹配,必须先打开目录)。
2. 显示 Inspector 面板(菜单「Inspector」或对应快捷键)。
3. 点 Inspector 面板头部的「导入」按钮,选 `pose_qa_inspector.json`。
4. Issue 列表按 `pose_qa_disagreement` 规则分组,每条是一个尾部 person。
5. 单击/双击某条 issue → 自动跳转到该图片 → 选中该 group 的 person 框 + 所有关键点 → 画布居中。

**已知边界**(非本次引入,使用时注意):
- 目标图片必须已在当前打开的目录里(`_json_path_to_image` 靠 basename 匹配)。
- 若该 shape 被当前 label/gid/type 过滤器隐藏,跳转后不会高亮(`select_shapes`
  会过滤掉非 interactive 的 shape)。需要先清除过滤器。

## 关键参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--tail-percent` | 10.0 | 尾部可疑比例(取风险分最高的 N%) |
| `--kpt-score-thr` | 0.3 | 模型点置信度阈值,低于此视为模型不确定(不参与最坏点选取) |
| `--oks-warn`(脚本内) | 0.5 | OKS 低于此直接标 suspicious |
| `--norm-dist-warn`(脚本内) | 0.2 | 归一化距离高于此直接标 suspicious |

## 算法要点

- **OKS 公式**:`exp(-norm_d² / (2·k²))`,尺度归一化后与 person 框大小无关。
- **kappa** 用 COCO 官方 17 点常量(nose=0.026 ... ankle=0.089)。
- **不可见点不参与**:标注里 `description: "invisible"` 的关键点跳过,避免遮挡误报。
- **尺度 = person 框对角线**,对侧身/瘦长框比 COCO 面积公式更稳。

详见 [`docs/pipeline_design.md`](docs/pipeline_design.md) 第三章。

## 状态

- ✅ 导出脚本 + demo + QA 比对 + 批量推理 + Inspector 跳转:已用 `s1860.jpg` 跑通验证
- ✅ `_on_inspector_navigate` group 聚合选中已增强(`label_widget.py`)
- ⏳ 全量 3.5 万图运行:待用户跑批量推理后验证
