# My-JLU-Inform · 实现计划与长期记忆

> 本项目：吉林大学通知智能总结与转发（路由器抓取 → GitHub Action 分析 → QQ 机器人推送）
> 仓库：https://github.com/Yummy-He/My-JLU-Inform
> 方案全文：`E:\通知\通知自动化方案.md`

---

## 一、目标

每天两个周期（昨日 19:00–今日 12:30 / 今日 12:30–19:00）：
1. 抓取 学校 OA（内网）+ 化学学院通知（公开）。
2. AI 判断「与我有关」（23 级化学本科生，2027 年拟 27 级直博）。
3. 有关的**详细推送**到 QQ，其余**简要总结**。
4. 手动触发：QQ 私聊机器人发「更新」，推送**最近 12 小时**通知（与自动周期互不干扰）。

---

## 二、关键决策记录（长期记忆，勿随意推翻）

1. **AI 判断不做本地规则粗筛**（2026-09-08 用户明确要求）：
   - 把所有新通知一次性丢给 DeepSeek：学院送 `title + summary`，OA 送 `title + org`。
   - 不做关键词预筛、不因省 token 而抓详情正文。一次批量调用，输出 JSON。
2. **路由器存储只用 TF 卡**（`/media/AiCard_01/notify/`）；`/etc/storage` 仅 704KB 闪存，不放大文件。
3. **断电固化**：脚本/数据放 TF 卡天然持久；只有 cron 配置写 `/etc/storage`，改完必须 `/sbin/mtd_storage.sh save`。
4. **curl / jq 在 `/usr/sbin/`**，SSH 默认 PATH 不含，脚本必须 `export PATH=/usr/sbin:$PATH`。
5. **去重**：学院按 `url`，OA 按数字 `id`（递增）。存 `data/seen.json`。
6. **推送**：QQ 官方机器人单聊 `POST /v2/users/{user_openid}/messages`；AccessToken 接口 `POST https://api.bot.qq.com/app/getAppAccessToken`，body `{appId, clientSecret}`，header `Authorization: QQBot <token>`。
7. **定时**：路由器 12:31/19:01（CST）抓取上传；Action `35 4`/`5 11`（UTC，即北京 12:35/19:05）。
8. **幂等**：auto 模式每次解析全部 inbox + seen 去重；manual 模式不读不写 seen。
9. **手动触发走云端（Cloudflare Worker，无状态 HTTP）**，不在路由器常驻进程（内存太小，也无 Python）。

---

## 三、目录结构

```
My-JLU-Inform/
├── .github/workflows/digest.yml
├── cloudflare/worker.js     # QQ 手动触发监听（CF Worker）
├── scripts/
│   ├── analyze.py           # 主逻辑：解析→去重/时间窗→AI→QQ推送→写seen
│   ├── parse_html.py        # 学院 + OA 解析
│   ├── prompt.md            # AI 提示词
│   └── requirements.txt
├── router/
│   ├── fetch_and_upload.sh  # 路由器抓取上传（部署到 TF 卡）
│   └── check_trigger.sh     # 路由器轮询手动触发标志（每3分钟）
├── data/
│   ├── inbox/               # 路由器上传的原始 JSON
│   ├── trigger/             # Worker 写入的手动触发标志（临时）
│   └── seen.json            # 去重记录
└── docs/
    └── samples/
```

---

## 四、任务清单与进度

- [x] Phase 1 代码：parse_html / analyze / prompt / digest.yml / fetch_and_upload.sh
- [x] Phase 2 本地验证：HTML 样本解析 + 去重幂等
- [x] Phase 3 上传 GitHub（main 分支）
- [x] Phase 4 路由器部署：fetch 脚本 + cron（12:31/19:01）+ mtd_storage save
- [x] Phase 5 自动链路联调：DeepSeek 分类 + QQ 推送 端到端通过
- [x] Phase 6 手动触发云端方案：CF Worker（op=13 验签 + C2C 消息）+ 路由器 check_trigger.sh + analyze.py manual 模式
- [ ] Phase 7 手动触发收尾：用户更新 Worker 代码与 Secrets，重新保存 QQ 回调并实测「更新」

---

## 五、手动触发链路（Phase 6/7 关键）

1. QQ 开放平台配「回调地址」→ QQ 发 `op=13` 验证。
2. CF Worker 用 `QQ_APP_SECRET` 做 Ed25519 签名回 `{plain_token, signature}`（**必须用纯 JS Ed25519**：Workers 不支持 raw Ed25519 私钥 import）。
3. 用户私聊发「更新」→ Worker 收到 `C2C_MESSAGE_CREATE` → 写 `data/trigger/trigger_<ts>.json` 到 GitHub → 回 QQ 确认。
4. 路由器 `check_trigger.sh` 每 3 分钟轮询 `data/trigger/` → 发现则抓取上传 + `workflow_dispatch`（mode=manual, trigger_ts=ts）→ 删除 trigger 文件。
5. Action 跑 `analyze.py` manual 模式：`trigger_ts` 统一转北京时间（Worker 写的是 UTC 带 Z），过滤最近 12 小时，不写 seen。

### CF Worker Secrets（Workers 页面 Settings → Variables and Secrets）
- `QQ_APP_SECRET`
- `QQ_APP_ID`
- `GH_TOKEN`（GitHub fine-grained PAT，Contents 读写）

### Ed25519 签名算法（QQ 官方）
- seed = AppSecret 重复到 ≥32 字节后截前 32 字节
- 签名字符串 = `event_ts + plain_token`，结果 hex
- 已用 QQ 官方示例验证：secret `DG5g3B4j9X2KOErG` → `87befc…c706`

---

## 六、环境约束（重要）

- 本机：git `D:\Git\bin\git.exe`、Python `D:\Python312\python.exe`、Node `D:\nodejs\node.exe`、plink `E:\通知\plink.exe`。
- 路由器：MT7620 / 内存很小 / busybox + curl + jq（`/usr/sbin`）/ 无 Python；SSH `admin@192.168.123.1`（密码 admin）。
- 路由器只能轮询，不能常驻 listener（内存不足）。
- Action 内部用 UTC；路由器与通知时间为北京时间（CST）。

---

## 七、进度日志

- 2026-09-08：路由器抓取脚本实测上传成功（inbox 120 条），seen 基线初始化。
- 2026-09-08：修复 fetch 脚本 dirname 拼第2页 URL、上传 body 改文件。
- 2026-09-08：自动链路端到端通过；digest.yml 双 cron + workflow_dispatch。
- 2026-09-08：新增手动触发（CF Worker + check_trigger.sh + analyze.py manual）。
- 2026-09-08：修复 Worker Ed25519（改纯 JS，因 Workers 不支持 raw 私钥 import）；修复 manual 触发 trigger_ts 时区（UTC→北京）。