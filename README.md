# Jargon Theory helper

这个仓库提供了一个可以在定性研究中快速应用“行话 (Jargon) 理论”步骤的命令行脚本。通过准备一份语言配置文件（列出核心术语、分类以及维度权重）和一组案例文本，脚本能够计算每个案例中行话的分布情况、概念维度得分以及整体的行话密度指标。

## 快速开始

1. 创建（或调整）一个语言配置文件，描述你在研究中使用的专业术语和维度。你可以参考 `examples/language.json`。
2. 将需要分析的案例整理成 JSON 或 YAML 格式，最简单的形式是一个包含 `id` 和 `text` 字段的数组，参见 `examples/cases.json`。
3. 运行分析命令：

   ```bash
   python jargon_theory.py analyze \
       --language examples/language.json \
       --cases examples/cases.json \
       --format markdown
   ```

   结果会直接输出在终端，你也可以通过 `--output` 参数保存到文件中。

## 语言文件说明

语言文件至少需要一个 `terms` 数组。每个术语支持以下字段：

| 字段 | 说明 |
| --- | --- |
| `term` | 术语本身（必填）。 |
| `category` | 归属的概念类别。用于不同维度的权重计算。 |
| `weight` | 默认 1.0，可用于强调某些术语的重要性。 |
| `description` | 术语的描述性说明。 |
| `variants` | 术语的变体（同义词、缩写等）。 |

可选地，还可以在 `dimensions` 中定义若干维度，每个维度提供对不同 `category` 的权重（`__default__` 为兜底权重）。`density_thresholds` 用来控制行话密度的高、中、低阈值。

## 案例文件说明

案例文件可以是一个数组，也可以是带 `cases` 键的对象。每条记录必须包含：

- `id`：案例编号。
- `text`：需要分析的文本。

其他字段会被保留并在输出中展示，便于追溯。

## 输出结果

脚本可以生成 JSON（默认）或 Markdown 两种格式。每个案例都会包含：

- 行话出现总次数、涉及的不同术语数量、文本总词数。
- 行话密度以及基于阈值的高/中/低判断。
- 维度得分（如果定义了维度）。
- 每个识别到的术语的详细计数和元数据。

## 依赖

- Python 3.11+
- 可选：如需读取 YAML 文件，请先安装 [PyYAML](https://pyyaml.org/)：`pip install PyYAML`

## 示例

仓库的 `examples/` 目录内包含示例的语言与案例文件，可直接用于测试。
