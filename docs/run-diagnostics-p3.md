# 运行诊断与数据可靠性 1.0（Phase 3）

本文档记录 #1391 Phase 3 的交付范围：在不新增配置的前提下，补齐运行诊断可见性并将历史排障信息回填到后端上下文快照，便于自部署环境快速定位异常。

## 本轮范围

- 历史报告详情新增默认折叠的「运行诊断 / 数据可靠性」区域；#1523 后 Web 展示标题调整为「运行诊断 / 运行状态」，历史阶段标题不变。
- 任务面板对进行中任务展示默认折叠的 trace 信息，便于和后端日志、SSE、历史报告诊断串联。
- 历史报告通过只读接口拉取诊断摘要：

```http
GET /api/v1/history/{record_id}/diagnostics
```

- 同步分析响应若已经带有 `diagnostic_summary`，前端可直接展示，不额外请求历史接口。
- 诊断面板支持复制后端生成的脱敏 `copy_text`，用于 issue 或部署排障。
- 分析链路在保存历史后会补齐任务/Provider/LLM/通知诊断到 `context_snapshot.diagnostics`，历史诊断接口统一聚合为用户可读摘要。

## 运行流视图

运行流视图是在运行诊断摘要之上的可视化排障入口，用于串联一次分析从触发、数据获取、ContextPack 组装、LLM 生成到保存/通知的大致链路。它不替代诊断摘要的 `copy_text`，而是把同一批脱敏诊断证据组织为节点、连线、事件和摘要指标，方便从 Web 首页快速定位异常或降级环节。

后端提供两个只读快照接口：

```http
GET /api/v1/analysis/tasks/{task_id}/flow
GET /api/v1/history/{record_id}/flow
```

- `tasks/{task_id}/flow` 面向活跃任务。任务仍在内存队列中时优先返回当前任务快照；任务已完成时可按同一 `task_id/query_id` 尝试读取历史诊断。缺少诊断时返回 skeleton flow，不伪造 provider、LLM 或通知事件。
- `history/{record_id}/flow` 面向历史报告，支持历史记录主键 ID 或可解析的 `query_id`。普通个股分析与 `MARKET/market_review` 大盘复盘复用同一 `RunFlowSnapshot` 契约。
- 快照顶层包含 `summary`、`lanes`、`nodes`、`edges`、`events` 和 `generated_at`。节点状态使用 `pending/running/success/failed/degraded/fallback/timeout/cancel_requested/cancelled/skipped/unknown`，其中用户取消类状态不会被映射成 `failed`。
- 旧历史、缺失 `context_snapshot.diagnostics` 或证据不足时，后端返回 `unknown` 或 skeleton 节点；Web 端按空/未知状态展示，不影响报告详情读取。

Web 入口：

- 首页活跃任务卡片提供运行流入口，打开抽屉后按 `task_id` 拉取任务快照。
- 历史报告摘要和运行诊断区域提供运行流入口，打开抽屉后按历史记录 ID 拉取历史快照。
- 面板展示摘要、基础拓扑、事件流和节点详情；复杂拓扑聚合、实时增量事件和布局 polish 会在后续阶段继续收敛。

脱敏与兼容边界：

- 运行流只读取既有任务信息、历史结果和 `context_snapshot.diagnostics` 中的低敏诊断字段，不新增配置项、不改数据库结构、不迁移旧历史。
- `model`、`provider`、`fallback_model` 仅用于展示实际诊断到的调用信息；不参与模型选择、请求路由、Base URL 解析或配置保存。
- `metadata`、错误信息和本地路径会经过后端裁剪与脱敏，避免暴露 API key、token、cookie、webhook、prompt/raw response、代理头和本地绝对路径。
- 回滚时可移除 Web 入口和查询路径；后端新增只读快照接口不改变原有分析、历史、通知或诊断摘要接口的成功/失败语义。

## 状态文案

总体状态：

- `normal`：正常
- `degraded`：部分降级
- `failed`：失败
- `unknown`：未知

组件状态：

- `ok`：正常
- `degraded`：最近失败后已降级
- `failed`：失败
- `unknown`：未知
- `not_configured`：未配置
- `skipped`：已跳过

## 交互边界

- 诊断区域默认折叠，避免挤占报告主要内容。
- 首屏只展示总体状态、首要原因和必要 trace 信息。
- 组件状态与高级 JSON 字段放在展开区域内；高级字段再二级折叠，避免信息过载。
- 旧报告、接口失败或证据不足时显示 `unknown`，不影响报告阅读。

## 兼容性边界

- 本轮不新增 `.env` 配置项，不修改数据库结构，不引入数据迁移。
- Web 只消费 Phase 1/2 已追加的可选字段和只读诊断接口；后端补齐 `src/core/pipeline.py`、`src/services/run_diagnostics.py`、`src/storage.py` 与 `src/services/history_service.py` 的诊断持久化与刷新逻辑，并通过 `api/v1/endpoints/history.py` 提供可读端点。
- 后端变更范围包含任务编排、历史保存后补写、历史诊断查询与通知结果诊断记录；这些链路只追加 `context_snapshot.diagnostics` 诊断快照和摘要，不改变分析主流程、通知发送成败语义或历史报告主体字段。
- 复制文本由后端生成并脱敏；前端只负责展示和复制。
- Desktop 复用 Web 构建产物，未单独改动 Electron 主进程或打包脚本。
- 运行时配置/模型/provider/base_url 兼容语义不调整：除诊断持久化链路外，不改 provider 优先级、LiteLLM 路由、运行时清理与配置回退逻辑。
- 旧历史与旧配置兼容规则不变：历史诊断查询新增可选字段不影响既有历史查询响应解析；回退方式为移除本轮展示与相关前端查询路径，或按现有指南恢复模型和配置。
- 回滚策略：优先回退前端展示与查询入口；若需完全隔离新增链路，可回滚本轮 PR（回退后保留历史记录原有响应，新增诊断端点不再在 Web 中展示）。

### 结构化检测澄清

本轮 review 的结构化检测命中了外部模型/API 兼容和运行时配置迁移风险；复核后结论如下：

- 模型名/provider/Base URL：本轮不新增、不替换、不重排任何模型名、provider、Base URL、channel 或 fallback 默认值，也不改变 `LITELLM_MODEL`、`AGENT_LITELLM_MODEL`、`VISION_MODEL`、`LITELLM_FALLBACK_MODELS`、`OPENAI_*`、`GEMINI_*`、`ANTHROPIC_*`、`DEEPSEEK_*` 的解析优先级。
- SDK/依赖默认值：本轮不修改 `requirements.txt`、`package.json` 依赖约束或 LiteLLM/OpenAI-compatible 调用默认参数；外部来源仍以 `docs/llm-providers.md` 和 `docs/LLM_CONFIG_GUIDE*.md` 中已记录的官方文档与当前锁定依赖说明为准。
- 保存前清理/配置迁移：本轮不触发 `.env`、Web 设置页 channel、桌面端用户数据目录、Docker 运行时配置文件或历史旧配置的迁移、清理、删除、回写策略变更。
- 本轮实际运行时改动只把既有分析 trace、provider/LLM/通知结果和脱敏错误摘要写入 `context_snapshot.diagnostics`，并通过历史只读接口和 Web 默认折叠面板展示；诊断记录失败按 fail-open 处理，不改变分析或通知的成功/失败判定。
- 因此本次属于结构化检测误报/文档澄清；无新增官方来源、旧配置迁移步骤或 provider 回退路径需要执行。若需回退，按本节回滚策略移除诊断展示/查询入口即可，模型与运行时配置恢复路径不变。

## 兼容性回归与验证（PR 合并前关键证据）

- 后端回归覆盖：
  - `tests/test_pipeline_market_phase_context.py`
  - `tests/test_realtime_types.py`
  - `tests/test_scheduler_background.py`
  - `tests/test_analysis_api_contract.py`（子集：诊断上下文入出参/状态查询契约）
  - `tests/test_analysis_history.py`（子集：历史 API 与持久化链路）
- 覆盖关系：API 合约由 `tests/test_analysis_api_contract.py` 与 `tests/test_analysis_history.py` 覆盖；任务编排、历史保存和 `context_snapshot.diagnostics` 由 `tests/test_pipeline_market_phase_context.py` 覆盖；通知路径通过 `./scripts/ci_gate.sh` 中的既有通知回归与导入检查兜底。
- 回归命令（PR 合并前至少确认全部通过）：

```bash
./scripts/ci_gate.sh
python -m pytest tests/test_realtime_types.py tests/test_scheduler_background.py tests/test_pipeline_market_phase_context.py tests/test_analysis_api_contract.py tests/test_analysis_history.py
cd apps/dsa-web && npm run lint && npm run build
```

## 验证建议

```bash
cd apps/dsa-web
npm run lint
npm run build
```

可补充执行（非阻断）：

```bash
cd apps/dsa-web
npm test -- --run src/components/report/__tests__/ReportDiagnostics.test.tsx src/components/tasks/__tests__/TaskPanel.test.tsx src/hooks/__tests__/useTaskStream.test.tsx
```

可补充确定性脚本校验：

```bash
python -m py_compile api/v1/endpoints/analysis.py api/v1/endpoints/history.py api/v1/schemas/analysis.py api/v1/schemas/history.py src/core/pipeline.py src/services/run_diagnostics.py src/storage.py
```

## 回滚

最小回滚方式：revert Phase 3 PR。由于本轮为可选字段与可读接口增强，回滚后后端历史快照与已落库数据保留，Web 不再展示诊断面板与 trace 诊断入口。
