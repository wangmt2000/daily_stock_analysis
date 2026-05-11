# 通知能力基线

本文档记录通知能力 P0-P4 基线：渠道、配置 key、GitHub Actions 映射、Web 设置元数据、CLI 诊断口径、Web 一键测试、自定义 Webhook Body 模板语义、通知路由策略和降噪机制。P0 只做基线与只读诊断；P1 增加 Web 单渠道真实测试；P2 产品化现有 Body 模板；P3 增加 report / alert / system_error 路由；P4 增加进程内降噪，不包含 per-URL 模板、跨进程持久化、真实每日摘要或新增一等渠道。

## 渠道基线

| 渠道 | 类型 | Minimal key | Advanced key | 说明 |
| --- | --- | --- | --- | --- |
| 企业微信 | 静态配置 | `WECHAT_WEBHOOK_URL` | `WECHAT_MSG_TYPE` | 配置后参与批量通知发送 |
| 飞书 Webhook | 静态配置 | `FEISHU_WEBHOOK_URL` | `FEISHU_WEBHOOK_SECRET`, `FEISHU_WEBHOOK_KEYWORD` | `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 不会单独开启群 Webhook 推送 |
| Telegram | 静态配置 | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | `TELEGRAM_MESSAGE_THREAD_ID` | token 与 chat id 必须同时存在 |
| 邮件 | 静态配置 | `EMAIL_SENDER`, `EMAIL_PASSWORD` | `EMAIL_RECEIVERS`, `EMAIL_SENDER_NAME` | `EMAIL_RECEIVERS` 留空时发给自己 |
| Pushover | 静态配置 | `PUSHOVER_USER_KEY`, `PUSHOVER_API_TOKEN` | - | 两个 key 必须同时存在 |
| PushPlus | 静态配置 | `PUSHPLUS_TOKEN` | `PUSHPLUS_TOPIC` | `PUSHPLUS_TOPIC` 仅在 token 存在时生效 |
| Server酱3 | 静态配置 | `SERVERCHAN3_SENDKEY` | - | 手机 App 推送 |
| 自定义 Webhook | 静态配置 | `CUSTOM_WEBHOOK_URLS` | `CUSTOM_WEBHOOK_BEARER_TOKEN`, `CUSTOM_WEBHOOK_BODY_TEMPLATE`, `WEBHOOK_VERIFY_SSL` | 支持多个 URL，逗号分隔 |
| Discord | 静态配置 | `DISCORD_WEBHOOK_URL` 或 `DISCORD_BOT_TOKEN` + `DISCORD_MAIN_CHANNEL_ID` | `DISCORD_INTERACTIONS_PUBLIC_KEY` | Webhook 与 Bot 均可启用发送 |
| Slack | 静态配置 | `SLACK_WEBHOOK_URL` 或 `SLACK_BOT_TOKEN` + `SLACK_CHANNEL_ID` | - | Bot 优先用于文本与图片同频道发送 |
| AstrBot | 静态配置 | `ASTRBOT_URL` | `ASTRBOT_TOKEN`, `WEBHOOK_VERIFY_SSL` | `ASTRBOT_TOKEN` 可选 |
| `UNKNOWN` | 兜底枚举 | - | - | 仅为未知渠道兜底，不由静态环境变量启用 |
| 钉钉会话 | 运行时上下文 | - | - | 从来源消息上下文提取，无法仅由 `.env` 静态判断 |
| 飞书会话 | 运行时上下文 | - | - | 从来源消息上下文提取，无法仅由 `.env` 静态判断 |

## Minimal / Advanced 分层

- Minimal key：足以启用一个通知渠道的最小配置。
- Advanced key：只影响认证、安全、格式、线程、群组、证书校验或展示行为，不能单独启用渠道。
- P3 的 `NOTIFICATION_*_CHANNELS` 属于 Advanced key：只收窄已启用渠道，不会单独启用渠道。
- P4 的 `NOTIFICATION_DEDUP_TTL_SECONDS`、`NOTIFICATION_COOLDOWN_SECONDS`、`NOTIFICATION_QUIET_HOURS`、`NOTIFICATION_TIMEZONE`、`NOTIFICATION_MIN_SEVERITY`、`NOTIFICATION_DAILY_DIGEST_ENABLED` 属于 Advanced key：只影响已启用静态渠道的发送策略，不会单独启用渠道。
- 长尾渠道、更细粒度路由、跨进程降噪和真实每日摘要不在 P4 范围内；相关配置如未来引入，应先更新本文档、`.env.example`、Web 元数据与回归测试。

## GitHub Actions 映射

仓库自带 `.github/workflows/daily_analysis.yml` 只显式导入固定变量名。P0 补齐以下已存在发送链路所需的映射：

- `CUSTOM_WEBHOOK_BODY_TEMPLATE`
- `WEBHOOK_VERIFY_SSL`
- `FEISHU_WEBHOOK_SECRET`
- `FEISHU_WEBHOOK_KEYWORD`
- `PUSHPLUS_TOPIC`

P3 补齐以下通知路由映射：

- `NOTIFICATION_REPORT_CHANNELS`
- `NOTIFICATION_ALERT_CHANNELS`
- `NOTIFICATION_SYSTEM_ERROR_CHANNELS`

P4 补齐以下通知降噪映射：

- `NOTIFICATION_DEDUP_TTL_SECONDS`
- `NOTIFICATION_COOLDOWN_SECONDS`
- `NOTIFICATION_QUIET_HOURS`
- `NOTIFICATION_TIMEZONE`
- `NOTIFICATION_MIN_SEVERITY`
- `NOTIFICATION_DAILY_DIGEST_ENABLED`

默认 workflow 仍不映射 `MARKDOWN_TO_IMAGE_CHANNELS` 与 `MERGE_EMAIL_NOTIFICATION`。它们是发送形态或聚合行为开关，不是渠道凭证；在 Actions 中自动开始读取同名 Secret/Variable 会引入额外行为变化。

## CLI 诊断

```bash
python main.py --check-notify
```

该命令只读配置，不发送通知，不写入 `.env`。它会在配置加载和日志初始化后立即执行，完成后直接退出，不再进入 Web、调度、大盘复盘或默认分析流程。

- 返回码 `0`：没有 error 级诊断。
- 返回码 `1`：存在 error，例如 0 个静态通知渠道已配置，或成对 key 只配置了一半。

## Web 一键测试

Web 设置页的“通知渠道”分类提供单渠道测试入口。测试会使用当前页面草稿值合成临时配置，发送一条真实测试通知，但不会保存 `.env`，也不会修改运行时全局配置。

- 测试范围：11 个静态通知渠道，不包含 `UNKNOWN` 和运行时上下文渠道。
- 普通渠道：返回单次发送结果、耗时和通用错误码。
- 自定义 Webhook：按 URL 顺序返回 attempts，展示每个 URL 的成功/失败、HTTP 状态、耗时和错误码。
- 返回结果会脱敏 token、secret、password、Bearer、完整 webhook query 和疑似 path token。
- 配置缺失或发送失败返回 `success=false`，不会影响已保存配置和默认分析流程。

## 自定义 Webhook Body 模板

`CUSTOM_WEBHOOK_BODY_TEMPLATE` 是自定义 Webhook 的全局 JSON body 模板。配置后，它会先于 URL 自动识别生效，因此会覆盖 Bark、Slack、Discord、钉钉等自动 payload。未配置时仍使用原有 URL 自动识别；渲染后不是合法 JSON object 时会记录错误并回退默认 payload，不中断主通知流程。

可用占位符：

- `$content_json`：JSON 转义后的通知正文，推荐默认使用。
- `$title_json`：JSON 转义后的通知标题，推荐默认使用。
- `$content` / `$title`：原始字符串，不做 JSON 转义。正文含双引号、反斜杠或换行时可能导致 JSON 无效并触发 fallback。

通用 webhook 示例：

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$title_json,"content":$content_json}
```

Bark 通过 custom webhook 使用时，默认会按 `api.day.app` 自动生成 `title` / `body` / `group`。如果配置全局模板，需要自己写出 Bark body：

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"title":$title_json,"body":$content_json,"group":"stock"}
```

AstrBot 已是一等通知渠道，优先使用 `ASTRBOT_URL` 和可选的 `ASTRBOT_TOKEN`。只有需要把 AstrBot 兼容端点放入 `CUSTOM_WEBHOOK_URLS` 时，才使用 custom webhook 模板，例如：

```env
CUSTOM_WEBHOOK_BODY_TEMPLATE={"content":$content_json}
```

NapCat / OneBot HTTP API 需要按实际 endpoint 和目标类型调整。下面只是常见 body 形态示例，`user_id`、`group_id`、URL 路径和鉴权方式都应以你的 NapCat 配置为准：

```env
# 私聊：CUSTOM_WEBHOOK_URLS=http://127.0.0.1:3000/send_private_msg
CUSTOM_WEBHOOK_BODY_TEMPLATE={"user_id":123456,"message":$content_json}
```

```env
# 群聊：CUSTOM_WEBHOOK_URLS=http://127.0.0.1:3000/send_group_msg
CUSTOM_WEBHOOK_BODY_TEMPLATE={"group_id":123456789,"message":$content_json}
```

## 通知路由策略

P3 新增三类通知路由配置：

| 路由类型 | 配置 key | 当前生产者 |
| --- | --- | --- |
| `report` | `NOTIFICATION_REPORT_CHANNELS` | 单股推送、聚合日报、大盘复盘、合并推送、飞书文档成功链接 |
| `alert` | `NOTIFICATION_ALERT_CHANNELS` | EventMonitor 触发通知 |
| `system_error` | `NOTIFICATION_SYSTEM_ERROR_CHANNELS` | 预留能力；当前不新增自动系统错误生产者 |

配置值为逗号分隔渠道枚举：`wechat,feishu,telegram,email,pushover,pushplus,serverchan3,custom,discord,slack,astrbot`。

- 留空或未配置：保持旧行为，发送到所有已配置静态渠道。
- 非空：只发送到路由列表与已配置渠道的交集；交集为空时不会 fallback 到全渠道。
- `send_to_context()` 不受路由限制，机器人会话上下文仍会收到触发任务的回复。
- 路由过滤发生在 Markdown 转图片前，`MARKDOWN_TO_IMAGE_CHANNELS` 只对路由后的渠道子集生效。
- `MERGE_EMAIL_NOTIFICATION` 不需要额外配置；只要 `email` 仍在 report 路由后的渠道中，现有合并邮件行为保持不变。
- `--check-notify` 会把未知渠道值报为 error，把合法但未启用的路由目标报为 warning。

## 通知降噪机制

P4 新增进程内降噪，只影响静态配置渠道，不影响 `send_to_context()` 的机器人触发会话回执。默认所有配置关闭，未设置时保持旧行为。

| 配置 key | 默认值 | 说明 |
| --- | --- | --- |
| `NOTIFICATION_DEDUP_TTL_SECONDS` | `0` | 同一稳定去重 key 在 TTL 内只发送一次；`0` 关闭 |
| `NOTIFICATION_COOLDOWN_SECONDS` | `0` | 同一冷却 key 在窗口内限频；`0` 关闭 |
| `NOTIFICATION_QUIET_HOURS` | 空 | 静默时段，格式 `HH:MM-HH:MM`，支持跨午夜 |
| `NOTIFICATION_TIMEZONE` | 空 | 静默时段时区，如 `Asia/Shanghai`；留空使用 Python 运行时本地时区（通常由进程 `TZ` 或系统时区决定） |
| `NOTIFICATION_MIN_SEVERITY` | 空 | `info`, `warning`, `error`, `critical`；留空不过滤 |
| `NOTIFICATION_DAILY_DIGEST_ENABLED` | `false` | 预留配置；当前不会发送每日摘要或持久化摘要内容 |

严重级别默认值：

- `report`：`info`
- `alert`：`warning`
- `system_error`：`error`
- 未知或未设置路由：`info`

实现边界：

- 去重 / 冷却状态是当前 Python 进程内 dict，适用于 `main.py` 单进程和 `--serve` 单 worker。
- `uvicorn --workers N`、多容器或多台机器场景下状态不共享，降噪为 per-worker 近似生效。
- pipeline 单股和聚合报告路径使用稳定 key，避免报告内生成时间变化击穿去重；其他未显式传入 `dedup_key` 的 report 通知按内容 hash 去重。
- 未显式传入 `cooldown_key` 的调用按路由和严重级别共享默认冷却槽位，例如 report / info 的普通通知会共用同一个槽位。
- 同一进程内相同 key 的并发发送会先占用短生命周期 in-flight 槽位，避免突发重复发送；静态渠道全部失败时释放该槽位，不写入正式去重 / 冷却状态。
- 降噪判断异常时 fail-open：记录日志并继续发送静态渠道。
- `NOTIFICATION_TIMEZONE` 留空时使用 `datetime.now().astimezone()` 解析到的运行时本地时区；Actions / Docker 场景建议显式配置 `NOTIFICATION_TIMEZONE` 以避免时区歧义。

## 场景占位

- Local：优先使用 `.env`，可用 `python main.py --check-notify` 做本地诊断。
- Docker：配置来源与本地一致，需确保容器环境变量已注入。
- GitHub Actions：只会读取 workflow `env:` 中显式映射的 Secret/Variable。
- Desktop：桌面端内嵌 Web 设置页可复用同一通知测试入口；测试仍只使用临时配置，不写入 `.env`。
