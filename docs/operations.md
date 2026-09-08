# 运行与运维手册（单机版）

> 适用于「智能推演指挥台」当前单机、非并行部署形态。

## 运行

```bash
# 离线冒烟（M0）
python -m app.main --smoke

# 测试
pytest tests

# 开发质量
ruff check app
```

## 数据文件布局（data/）
| 路径 | 内容 |
|---|---|
| `data/*.json` | EventBus 事件队列（events.json）与已处理去重 |
| `data/traces/` | TraceLogger 输出（启用 trace 时） |
| `data/replay/` | 复盘 timeline JSON（规划） |
| `data/*.db` | SQLite（切换 `Components.register_state_store` 后启用，M5 预留） |

## 启动与升级
1. `pip install -e ../agentorchestra`（升级框架后运行全量 `pytest tests` 回归）。
2. 只在 `app/core/`（config/components/observability）触碰框架装配；领域/引擎代码不直接依赖框架内部。
3. 升级前备份 `data/`。

## 备份
- 备份 `data/` 整目录即含事件队列/复盘产物；
- SQLite 启用后使用 `sqlite3 data/games.db ".backup ..."` 在线备份。

## 上线前检查清单
- [ ] `pytest tests` 全绿、`ruff check app` 通过
- [ ] 一键剧本可跑：`tests/test_m5_ops.py::test_scripted_scenario_and_replay`
- [ ] 审计可查：各动作落 AuditManager（含被拒尝试）
- [ ] 账目回滚演示通过（补偿测试）
- [ ] 无外部实时依赖、无隐式磁盘扫描
- [ ] 已知降级：模型不可用回退 Mock/规则路径说明

## 已知边界（当前明确不做）
- 多机/消息队列、GIS、文档 RAG、真实 IAM/加密 → 见 technical-roadmap §11。
