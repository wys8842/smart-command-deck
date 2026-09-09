# 性能基准报告（自动生成）

- 生成时间：2026-09-09 09:44:52
- Python：3.10.20 · 平台：Windows-10-10.0.26100-SP0
- 规模系数：1.0

| 项目 | 指标 | 数值 |
|---|---|---:|
| EventBus | enqueue ops/s | 12248 |
| EventBus | pending ops/s | 643625 |
| EventBus | mark_processed ops/s | 45915 |
| Ontology | insert ops/s | 20746 |
| Ontology | get ops/s | 480123 |
| Deck 推演 | events/s | 231 |
| Coordinator 事务 | tx ops/s | 469 |

> 说明：Deck 使用 MockLLM（排除真实模型网络时延），用于衡量框架编排/持久化开销。
