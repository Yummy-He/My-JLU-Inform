# My-JLU-Inform

吉林大学通知智能总结与转发：路由器定时抓取（OA 内网 + 化学学院）→ GitHub Action 用 DeepSeek 分类 → QQ 机器人推送。

## 工作原理

- **路由器**（Padavan，POSIX sh + curl + jq）每天 12:31 / 19:01 抓取页面 HTML，打包 JSON 上传到本仓库 `data/inbox/`。
- **GitHub Actions**（每天 12:35 / 19:05 北京）解析 inbox → 去重 → DeepSeek 判断「与我有关」→ QQ 推送 → 更新 `data/seen.json`。

## 目录

```
scripts/analyze.py            主逻辑
scripts/parse_html.py         学院 + OA 解析
scripts/prompt.md             AI 提示词
router/fetch_and_upload.sh    路由器抓取脚本
.github/workflows/digest.yml  定时任务
data/inbox/                   路由器上传的原始数据
data/seen.json                去重记录
```

## 配置（GitHub Secrets）

- `DEEPSEEK_API_KEY`：DeepSeek API Key
- `QQ_APP_ID` / `QQ_APP_SECRET`：QQ 机器人 AppID/AppSecret
- `QQ_USER_OPENID`：接收通知的用户 openid

## 路由器部署

见 `router/fetch_and_upload.sh` 顶部注释与 `PLAN.md`。
