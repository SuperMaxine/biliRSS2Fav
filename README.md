# biliRSS2Fav

一个用于将 RSSHub 的 B 站视频订阅，自动同步到指定 Bilibili 收藏夹的工具。  
支持增删同步、容量上限淘汰、Cookie 自动刷新，以及异常邮件通知。

## 功能概览

- RSS -> 收藏夹增量同步（以 RSS 新增为驱动）
- 自动新增：RSS 有但收藏夹没有的视频
- 自动删除：仅在超过 `FAV_MAX_ITEMS` 时淘汰较旧收藏
- 容量控制：超过 `FAV_MAX_ITEMS` 自动淘汰较旧收藏
- Cookie 自动刷新并落盘 `credential.json`
- 登录失效 / API 异常时发送告警邮件
- 提供受控浏览器登录组件（扫码/手动登录自动提取 Cookie）

## 程序设计思路（简述）

系统按“模块解耦 + 定时同步”设计：

- `src/browser_login.py`：只负责获取并写入登录凭据
- `src/rss_reader.py`：只负责 RSS 拉取与 BV/AV -> aid 解析
- `src/bili_fav.py`：只负责 B 站收藏夹 API 封装
- `src/syncer.py`：只负责同步编排（差异计算、限额淘汰、增删执行、异常通知）
- `src/main.py`：运行入口（`once` / `daemon`）

关键原则：

- 凭据是长期运行核心，刷新后必须落盘
- 同步先删后加，避免容量冲突
- 所有敏感信息从 `.env` 和 `data/credential.json` 读取，不硬编码

## 执行过程（每轮同步）

每次 `sync_once` 的步骤：

1. 读取 `credential.json` 并构造 `Credential`
2. 校验凭据有效性（`check_valid`）
3. 需要时刷新 Cookie（`check_refresh` -> `refresh`）并写回文件
4. 获取当前账号，查找或创建目标收藏夹
5. 拉取 RSS，解析出期望视频集合 `desired_aids`
6. 拉取收藏夹现有集合 `existing_aids`
7. 计算新增差异（仅 `to_add`，不会因 RSS 缩短而删库）
8. 若超过 `FAV_MAX_ITEMS`，按“较旧收藏优先”淘汰超额条目
9. 执行同步：先删后加（带操作间隔，默认 `0.3s`）
10. 更新 `state.json`
11. 任意环节异常 -> 发送告警邮件

## 项目结构

```text
biliRSS2Fav/
  src/
    browser_login.py
    main.py
    syncer.py
    bili_fav.py
    rss_reader.py
    credential_store.py
    config.py
    notify.py
  data/
    credential.example.json
    state.example.json
  .env.example
  requirements.txt
  README.md
```

## 部署与运行教程（Windows / Linux 通用）

### 1. 环境要求

- Python 3.10+
- 可访问 Bilibili 与你的 RSSHub 地址
- SMTP 邮箱（用于告警邮件，可选但建议配置）

### 2. 安装依赖

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 3. 配置 `.env`

复制 `.env.example` 为 `.env` 并填写：

```env
RSS_URL=http://206.190.236.109:1200/bilibili/followings/video/8613786/false
FAV_TITLE=RSS 同步收藏夹
FAV_PRIVATE=false
FAV_MAX_ITEMS=200
SYNC_INTERVAL_SECONDS=300
OP_DELAY_SECONDS=0.3

CREDENTIAL_JSON=data/credential.json
STATE_JSON=data/state.json

SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=example@qq.com
SMTP_PASS=your-smtp-auth-code
ALERT_TO_EMAIL=alert-target@example.com
SMTP_FROM_NAME=biliRSS2Fav
```

说明：

- `FAV_MAX_ITEMS` 是你定义的“公开窗口大小”，不是 B 站硬上限
- `OP_DELAY_SECONDS` 越大越稳（可降低风控概率）

### 4. 生成凭据（推荐：受控浏览器自动抓取）

执行：

```bash
python -m src.browser_login --env-file .env --credential-json data/credential.json --timeout-seconds 600
```

然后在弹出的浏览器中：

- 扫码登录，或
- 手动输入账号密码登录

登录成功后脚本会自动写入：

- `SESSDATA`
- `bili_jct`
- `buvid3`
- `buvid4`
- `DedeUserID`
- `ac_time_value`

### 5. 首次联调（单次同步）

```bash
python -m src.main once --env-file .env --verbose
```

看到类似日志即表示成功：

```text
Sync done media_id=... desired=... existing=... removed=... added=... refreshed_cookie=...
```

### 6. 常驻运行

```bash
python -m src.main daemon --env-file .env
```

程序会按 `SYNC_INTERVAL_SECONDS` 周期执行同步。

## Linux 常驻部署（systemd 示例）

创建 `/etc/systemd/system/bilirsstofav.service`：

```ini
[Unit]
Description=biliRSS2Fav sync daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/biliRSS2Fav
ExecStart=/usr/bin/python3 -m src.main daemon --env-file .env
Restart=always
RestartSec=5
User=your_user

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable bilirsstofav
sudo systemctl start bilirsstofav
sudo systemctl status bilirsstofav
```

## 常见问题排查

### 1) `Missing file: data\credential.json`

说明凭据文件不存在。先执行浏览器登录组件生成凭据：

```bash
python -m src.browser_login --env-file .env --credential-json data/credential.json
```

### 2) `Credential is invalid (check_valid=False)`

登录态已失效，重新执行登录组件覆盖 `credential.json`。

### 3) 登录后仍提示缺少 `ac_time_value`

确保登录后页面完全加载，或重新执行：

```bash
python -m src.browser_login --env-file .env --timeout-seconds 600
```

### 4) 同步过程中出现风控/请求受限

- 增大 `OP_DELAY_SECONDS`（例如 `0.5` 或 `1.0`）
- 适当增加 `SYNC_INTERVAL_SECONDS`

### 5) 邮件告警不发送

检查：

- `SMTP_HOST/PORT/USER/PASS`
- 发件箱是否开启 SMTP 服务并使用授权码
- `ALERT_TO_EMAIL` 是否正确

可用测试脚本验证邮件配置：

```bash
python mail_example.py "SMTP test" --env-file .env
```

## 安全建议

- 不要提交 `.env` 与 `data/credential.json`
- 不要在日志中打印完整 Cookie
- 建议为运行目录设置最小权限

## 常用命令速查

```bash
# 安装依赖
pip install -r requirements.txt
python -m playwright install chromium

# 登录并生成凭据
python -m src.browser_login --env-file .env --credential-json data/credential.json

# 单次同步
python -m src.main once --env-file .env --verbose

# 常驻同步
python -m src.main daemon --env-file .env
```
