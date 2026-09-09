# 运维手册（单机）

## 1. 运行

```bash
LLM_PY="D:/python/miniconda/envs/llm/python.exe"

"$LLM_PY" -m app.api.launch          # 启动服务（默认 127.0.0.1:8000）
"$LLM_PY" -m app.main --smoke        # 离线冒烟
"$LLM_PY" -m pytest tests -q         # 回归（62 用例）
"$LLM_PY" -m ruff check app          # 代码检查
```

端口与主机在 `app/api/launch.py::main(host, port, reload)` 中设置。

停止服务：`Stop-Process -Id <pid> -Force`（pid 记录在 `server.pid`）。

## 2. 配置

启动时 `app/core/env.py::load_env()` 读取 `.env`（不覆盖已有环境变量）。可用项：

| 变量 | 默认 | 说明 |
|---|---|---|
| `LLM_MODEL_ID` / `LLM_API_KEY` / `LLM_BASE_URL` | 空 | 真实模型；缺失回退 `MockLLM` |
| `LLM_TIMEOUT` | 60 | 调用超时（秒） |
| `LLM_MAX_RETRIES` | 3 | 重试次数 |
| `LLM_RETRY_BASE_DELAY` | 1.0 | 退避基数（秒） |
| `LLM_CACHE_SIZE` | 256 | 响应缓存条数（0=关闭） |
| `LLM_CACHE_TTL` | 3600 | 缓存有效期（秒） |
| `DECK_MAX_CONCURRENCY` | 1 | 单批事件并发度 |
| `DECK_TENANT_QUOTA` | 100000 | 每租户 token 配额 |
| `TRACE_ENABLED` | 1 | 是否开启 TraceLogger |
| `TRACE_DIR` | data/traces | 轨迹目录 |
| `OTEL_ENDPOINT` | 空 | 配置后开启 OTLP 导出 |

## 3. 数据文件

| 路径 | 说明 | 备份 |
|---|---|---|
| `data/games.db` | Ontology 对象（单位/目标/命令/账目/记录） | 停机复制或 `sqlite3 .backup` |
| `data/state.db` | CheckpointStore（Inbox/iteration/Interrupt/锁/幂等/DLQ/审计） | 同上 |
| `data/events.json` | EventBus 事件与已处理标记（JSONL） | 复制 |
| `data/replay.json` | 节点时序（JSONL） | 复制 |
| `data/experience.jsonl` | 战例库 | 复制 |
| `data/traces/` | TraceLogger 输出 | 可清理 |

`data/`、`*.db`、`server.pid`、`.env` 均不进入版本库。

## 4. 健康与可观测

- `GET /health`：`orders`、`pump`、`queued`、`llm_mode`、`llm_model`、`capabilities`
- `GET /metrics`：Prometheus 文本；关键指标
  - `deck_events_processed_total`
  - `deck_event_latency_seconds{kind}`
  - `deck_pump_cycle_seconds`
  - `deck_approval_wait_seconds{decision}`
  - `deck_quota_denied_total{tenant}`
- `GET /interrupts`：待人工批准（框架 Interrupt）
- `GET /tenants`：配额与用量
- `GET /experience/stats`：战例召回缓存命中
- `data/traces/`：每局 JSONL + HTML 轨迹

## 5. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 启动报 `No module named 'sqlalchemy'` | 框架依赖缺失 | `pip install "sqlalchemy>=2.0" aiosqlite` |
| `asyncio has no attribute 'timeout'` | Python 3.10 | `app/core/compat.py` 已自动安装垫片；确认导入顺序 |
| 事件一直 `queued` | pump 未启动或模型超时 | 检查 `/health.pump`、`/metrics.deck_pump_cycle_seconds`、`LLM_TIMEOUT` |
| `llm_mode=mock` | 未配置 key/model | 填写 `.env` 后重启 |
| 命令长期 `pending` | 未批准 | `GET /interrupts` 查看；`POST /approvals/{order_id}` 批准 |
| 事件进入 `denied` | 配额超限 | 提高 `DECK_TENANT_QUOTA` 或减少 `tokens` |
| 端口占用 | 已有进程 | `Stop-Process` 旧 pid，或改端口 |
| push 失败 | 本机代理不可达 | `git -c http.proxy= -c https.proxy= push` |

## 6. 升级

1. 更新框架：`pip install -e ../agentorchestra`（或目标 tag）。
2. 运行 `pytest tests` 与 `scripts/acceptance.py` 回归。
3. 备份 `data/` 后再启动。

## 7. 安全

- 密钥仅存 `.env`；`.gitignore` 忽略 `.env`、`*.key`、`*.pem`、`secrets/`。
- 提交前钩子 `.githooks/pre-commit` 调 `scripts/check_secrets.py`；CI 同样拦截。
- `tests/test_no_secrets.py` 断言已跟踪文件无密钥、`.env` 未被跟踪。
- 若密钥曾泄露：先在平台轮换，再清理历史。
