# RSS -> Bilibili 收藏夹同步器设计与落实文档

## 1. 目标

实现一个可长期运行的同步服务，将 RSSHub 的 Bilibili 订阅源与指定收藏夹保持一致，支持：

- 新增：RSS 有、收藏夹无 -> 加入收藏夹
- 删除：收藏夹有、RSS 无 -> 从收藏夹删除
- 上限淘汰：超过 `FAV_MAX_ITEMS` 时先删旧再加新
- 凭据维护：使用 `bilibili-api-python` Cookie 自动刷新，并将新 cookie 落盘
- 异常通知：凭据失效/刷新失败/API 失败时发送邮件告警

## 2. 实现边界

- 单账号 + 单收藏夹
- 不下载视频、不做转存
- 不实现复杂编排控制台
- 风控（如 -412）通过降频与重试缓解，不做绕过承诺

## 3. 项目结构

```text
biliRSS2Fav/
  src/
    __init__.py
    browser_login.py
    config.py
    credential_store.py
    rss_reader.py
    bili_fav.py
    syncer.py
    notify.py
    main.py
  data/
    credential.example.json
    state.example.json
  .env.example
  requirements.txt
  AGENTS.md
```

## 4. 配置约定

必需环境变量：

- `RSS_URL`
- `FAV_TITLE`
- `FAV_PRIVATE` (`true/false`)
- `FAV_MAX_ITEMS` (int)
- `SYNC_INTERVAL_SECONDS` (int)
- `CREDENTIAL_JSON` (路径)
- `STATE_JSON` (路径)
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `ALERT_TO_EMAIL`
- `SMTP_FROM_NAME`（可选）

## 5. 数据文件约定

`credential.json`：直接存 `Credential.get_cookies()` 结果（至少包含 `SESSDATA`, `bili_jct`, `buvid3`, `buvid4`, `DedeUserID`, `ac_time_value`）。

`state.json`：

```json
{
  "media_id": 0,
  "last_sync_ts": 0
}
```

## 6. 同步流程（单次 tick）

1. 从 `credential.json` 读取 cookies 并构建 `Credential`
2. 若 `check_refresh()` 为真，则执行 `refresh()` 并立即写回 `credential.json`
3. 拉取当前登录用户 `mid`
4. 查询/创建目标收藏夹，得到 `media_id`，写入 `state.json`
5. 拉取 RSS，解析每个 `entry.link`，提取 BV/av 并转换为 aid，得到 `desired_aids`
6. 读取收藏夹现有 `existing_aids`
7. 计算差异：
   - `to_add = desired - existing`
   - `to_remove = existing - desired`
8. 容量控制：计算应用变更后的数量，若超过 `FAV_MAX_ITEMS`，额外淘汰最旧收藏项
9. 应用变更：
   - 先删后加
   - 新增/删除间隔 sleep（默认 0.3s）
10. 更新 `state.json.last_sync_ts`
11. 任一步失败 -> 发邮件告警，保留异常日志

## 7. 关键实现规则

- 刷新后必须落盘新 cookie；否则重启后失效
- 日志不打印完整 cookie 或邮箱密码
- 删除采用批量接口；新增按 aid 逐条调用 `Video.set_favorite`
- RSS 解析失败的条目跳过并记录 warning，不阻断全量同步
- 风控错误优先降频，必要时允许继续下轮重试

## 8. 落地计划（严格执行）

1. 建目录与基础模块骨架（`src/*`、`data/*`、`.env.example`、`requirements.txt`）
2. 实现配置加载与文件读写（`config.py`, `credential_store.py`）
3. 实现 RSS 解析与 BV/AV 转换（`rss_reader.py`）
4. 实现收藏夹与视频操作封装（`bili_fav.py`）
5. 实现邮件通知（`notify.py`）
6. 实现同步编排与上限淘汰逻辑（`syncer.py`）
7. 实现入口主循环（`main.py`，支持 `once` 与 `daemon`）
8. 自检：
   - 语法编译
   - 核心模块导入
   - 配置样例完整性
9. 输出执行结果与后续运行说明

## 9. 验收标准

- 可通过 `python -m src.main once` 完成单次同步流程（在配置正确时）
- 可通过 `python -m src.main daemon` 周期运行
- 可通过 `python -m src.browser_login --env-file .env` 打开浏览器登录并生成 `credential.json`
- Cookie 刷新后 `credential.json` 确认更新
- RSS 新增/删除会体现在收藏夹增删
- 凭据无效或接口失败会触发邮件告警
