# Smart Command Deck · 智能推演指挥台

> 面向「军事指挥 / 兵棋推演」类业务的**回合制多智能体决策推演平台**——以
> [agentorchestra](https://github.com/wys8842/agentorchestra-v0.2.0)（Symphony）
> 作为**第三方底层库**进行构建；**单机部署、非并行（单进程事件循环内协作）**。

本目录是与框架仓库 **相互隔离** 的独立应用工程（建议单独建 git 仓库），
只通过标准依赖方式使用框架，不改动框架源码。

## 项目定位（为什么是 9.5/10 的适配形态）

| 维度 | 取值 | 说明 |
|---|---|---|
| 触发 | 回合制 + 事件驱动（秒~分钟级） | 切合框架 `Scheduler + Inbox + Graph` |
| 协作 | 多角色多智能体（参谋 Agent / 研判 / 建议 / 批准） | 切合 `Graph / AgentNode / Router` |
| 模型 | 结构化战场/业务对象 | 切合 `ontology` |
| 正确性 | 账目平账 + 审计留痕 + 可复盘 | 切合 `tx / govern / state / observability` |
| 范围外 | 毫秒实时、GIS、海量文档、分布式 | 明确外挂，不进入框架计分 |

## 目录约定（规划）

```
smart-command-deck/
├── docs/
│   └── technical-roadmap.md      # 详细技术路线（本项目的实施主线）
├── app/
│   ├── core/                     # 装配：Config / components 门面 / 依赖注入
│   ├── domain/                   # ontology 领域模型 + 动作 + 规则（对接框架 ontology）
│   ├── engine/                   # 回合时钟 / 事件泵 / Graph 蓝图 / HITL 状态
│   ├── api/                      # 接入入口（事件 API / 批准 API / 复盘导出）
│   └── main.py                   # 单机 Supervisor 入口
├── tests/
└── pyproject.toml                # 依赖：agentorchestra（本地 editable / git tag）
```

## 关键文档
- [详细技术路线](docs/technical-roadmap.md)：从 M0 到 M5 的分步实施方案、架构与验收标准。
- [运行与运维手册](docs/operations.md)：启动/备份/上线检查清单（单机版）。

## 安装

```bash
# 1. 安装框架（同级目录，开发期 editable）
pip install -e ../agentorchestra

# 2. 安装本工程（开发依赖）
pip install -e ".[dev]"
```

## 运行

```bash
# M0 离线冒烟 —— 验证『app → agentorchestra』通路
python -m app.main --smoke

# 运行测试
pytest tests
```

## 当前进度

| 里程碑 | 状态 | 说明 |
|---|---|---|
| M0 工程骨架 | ✅ 通过 | pyproject + 目录结构 + 离线冒烟（SimpleAgent + MockLLM） |
| M1 领域建模 | ✅ 通过 | ontology 4 类对象 + 6 类动作 + engine.mount 挂工具 |
| M2 回合时钟+事件泵 | ✅ 通过 | EventBus(JSON)+事件契约 + 最小研判图(entry→intel Agent→record) + 重启去重 |
| M3 完整 DAG+HITL | ✅ 通过 | 分级路由(low/high) + approve HITL 续跑(approved/rejected→execute/settle) |
| M4 账目+权限+审计 | ✅ 通过 | 事务补偿(resupply 失败回滚)、RBAC 权限矩阵、AuditManager 审计(含被拒留痕) |
| M5 复盘+观测+加固 | ✅ 通过 | 一键剧本复盘导出、Prometheus 指标、3 局并发冒烟、运维手册 |

## 里程碑验收速览

```bash
pytest tests            # 19 passed：M1 建模 / M2 事件泵 / M3 DAG+HITL / M4 事务+权限+审计 / M5 复盘+观测
ruff check app          # All checks passed
python -m app.main --smoke   # M0 离线冒烟
```

## 工程目录

```
smart-command-deck/
├── docs/technical-roadmap.md   # 详细技术路线
├── app/
│   ├── main.py                 # 单机入口（--smoke 冒烟）
│   ├── core/                   # 装配层（Config / Components / MockLLM）
│   ├── domain/                 # ontology 领域模型（M1 开始实现）
│   ├── engine/                 # 推演引擎（M2 开始实现）
│   └── api/                    # 事件/批准/复盘 API（M3 开始实现）
├── tests/
└── pyproject.toml
