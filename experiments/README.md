# Experiments

实验 = 一批在相同初始条件下、不同随机种子（或不同意识形态分布）的 Society，
用于研究"随机性如何改变社会结果"（§19–§20）。

## 通过 API 创建

```bash
curl -X POST http://127.0.0.1:8765/api/experiment/create \
  -H "Content-Type: application/json" \
  -d '{"society_count": 20, "seed_start": 0}'
```

```bash
curl -X POST "http://127.0.0.1:8765/api/experiment/{experiment_id}/run?speed=100"
```

## 对比最终结果

每个 Society 的宏观指标可通过
`GET /api/society/{id}/metrics` 拉取，用于对比极化、基尼、冲突率、政府稳定度等。

## 示例配置

把下面内容存成 YAML 放进本目录，通过 `configs/loader.load_config(path)` 加载，
或直接 POST 到 `/api/society/create` 作为 `config` 字段：

```yaml
# experiments/authoritarian-increase.yaml
population:
  count: 1000
  ideology_distribution:
    liberal: 0.20
    conservative: 0.20
    socialist: 0.10
    libertarian: 0.05
    authoritarian: 0.45
```

对照组（control）保持默认 20% authoritarian，实验组 45% authoritarian，
各跑 50 个 Society，比较 `political_polarization`、`conflict_rate`、
`government_stability` 的平均值。
