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

---

## 二、关键决策记录（长期记忆，勿随意推翻）

1. **AI 判断不做本地规则粗筛**（2026-09-08 用户明确要求）：
   - 把所有新通知一次性丢给 DeepSeek：学院送 `title + summary`，OA 送 `title + org`。
   - 不做关键词预筛、不因省 token 而抓详情正文。一次批量调用，输出 JSON。
2. **路由器存储只用 TF 卡**（`/media/AiCard_01/notify/`）；`/etc/storage` 仅 704KB 闪存，不放大文件。
3. **断电固化**：脚本/数据放 TF 卡天然持久；只有 cron 配置写 `/etc/storage`，改完必须 `/sbin/mtd_storage.sh save`。
4. **curl / jq 在 `/usr/sbin/`**，SSH 默认 PATH 不含，脚本必须 `export PATH=/usr/sbin:$PATH`。
5. **去重**：学院按 `url`，OA 按数字 `id`（递增）。存 `data/seen.json`。
6. **推送**：QQ 官方机器人单聊 `POST /v2/users/{user_openid}/messages`。
7. **定时**：路由器 12:31/19:01（CST）；Action `35 4`/`5 11`（UTC，即北京 12:35/19:05）。
8. **幂等**：Action 每次解析全部 inbox + seen 去重，重复运行不重推、不漏推。

---

## 三、目录结构

```
My-JLU-Inform/
├── .github/workflows/digest.yml
├── scripts/
│   ├── analyze.py          # 主逻辑：解析→去重→AI→QQ推送→写seen
│   ├── parse_html.py       # 学院 + OA 解析
│   ├── prompt.md           # AI 提示词
│   └── requirements.txt
├── router/
│   └── fetch_and_upload.sh # 路由器抓取上传脚本（部署到 TF 卡）
├── data/
│   ├── inbox/              # 路由器上传的原始 JSON（git 追踪，便于追溯）
│   └── seen.json           # 去重记录
└── docs/
    └── samples/            # 实测 HTML 样本（测试解析用）
```

---

## 四、任务清单与进度

### Phase 1 · 代码（已完成）
- [x] parse_html.py（学院 + OA 解析）
- [x] analyze.py（主逻辑）
- [x] prompt.md / requirements.txt
- [x] digest.yml
- [x] router/fetch_and_upload.sh

### Phase 2 · 本地验证
- [x] 用实测 HTML 样本验证解析逻辑（Python，90 条解析 + 去重幂等通过）

### Phase 3 · 上传仓库（已完成）
- [x] 获取 GitHub PAT（已提供）
- [x] 上传代码到 My-JLU-Inform（main 分支，11 文件）

### Phase 4 · 路由器部署（已完成）
- [x] 上传 fetch_and_upload.sh 到 `/media/AiCard_01/notify/`（2518B，sh -n 通过）
- [x] 配 cron（12:31/19:01）+ mtd_storage.sh save 固化

### Phase 5 · Secrets + 联调（需用户）
- [ ] `DEEPSEEK_API_KEY`
- [ ] `QQ_APP_ID` / `QQ_APP_SECRET` / `QQ_USER_OPENID`
- [ ] 端到端测试（待 Secrets）

---

## 五、待用户提供（阻塞项清单）

1. **GitHub fine-grained PAT**：仅授予 My-JLU-Inform 仓库 `Contents: Read/Write`。用于：我上传代码 + 路由器上传数据。
2. **DeepSeek API Key**。
3. **QQ 机器人 AppID / AppSecret**（q.qq.com/qqbot 创建机器人）。
4. **QQ 加机器人为好友 + user_openid**（采集方式见方案 §7.1）。

---

## 六、环境约束（重要）

- 本机：**无 git、无可用 Python**；有 Node.js（`D:\nodejs\node.exe`）、PowerShell 7、plink 0.85。
- 推送代码到 GitHub：用 GitHub REST API（Node/PowerShell），或临时安装 git。
- 解析测试：用 Node 模拟 BeautifulSoup 逻辑，或安装 Python。
- 路由器：MT7620 / 123MB RAM / busybox + curl + jq（在 /usr/sbin）/ openssl。

---

## 七、进度日志

- 2026-09-08：路由器抓取脚本实测上传成功（inbox 20260908_2000，120 条通知），seen.json 基线已初始化。
- 2026-09-08：修复 fetch 脚本两处 bug（dirname 拼第2页 URL、上传 body 改文件避免命令行超限）。

## 七、进度日志

- 2026-09-08：完成全部探测（路由器内存/工具、学院分页、OA 结构、QQ API），方案 v2 定稿。
- 2026-09-08：开始 Phase 1 代码实现。


