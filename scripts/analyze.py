# -*- coding: utf-8 -*-
"""主逻辑：解析 inbox → 去重/时间窗 → DeepSeek 分类 → QQ 推送。

两种模式（互不干扰）：
- auto   （定时触发）：seen.json 增量去重，只推本周期新增，推送后更新 seen。
- manual （QQ「更新」触发）：以触发时刻为基准推最近 12 小时，不读不写 seen。
"""
import os
import re
import sys
import json
import glob
from datetime import datetime, timedelta

import requests

from parse_html import parse_chem, parse_oa

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(REPO, "data", "inbox")
SEEN = os.path.join(REPO, "data", "seen.json")
PROMPT = os.path.join(REPO, "scripts", "prompt.md")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
QQ_APP_ID = os.environ.get("QQ_APP_ID", "")
QQ_APP_SECRET = os.environ.get("QQ_APP_SECRET", "")
QQ_USER_OPENID = os.environ.get("QQ_USER_OPENID", "")

MODE = os.environ.get("MODE", "auto")          # auto / manual
TRIGGER_TS = os.environ.get("TRIGGER_TS", "")  # 手动触发时刻（ISO）
WINDOW_HOURS = 12


# ---------- seen ----------
def load_seen():
    if os.path.exists(SEEN):
        with open(SEEN, encoding="utf-8") as f:
            return json.load(f)
    return {"chem_urls": {}, "oa_ids": {}}


def save_seen(seen):
    with open(SEEN, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


# ---------- inbox ----------
def parse_inbox_file(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ts = data.get("ts", "")
    fetched_date = ts[:10] if ts and len(ts) >= 10 else datetime.now().strftime("%Y-%m-%d")
    pages = data.get("pages", {})
    notices = []
    for key, src in (("chem1", "chem"), ("chem2", "chem"),
                     ("bks1", "bks"), ("bks2", "bks"),
                     ("yjs1", "yjs"), ("yjs2", "yjs")):
        html = pages.get(key, "")
        if html:
            notices.extend(parse_chem(html, src))
    html = pages.get("oa", "")
    if html:
        notices.extend(parse_oa(html, fetched_date))
    return notices


def dedup(notices, seen):
    """auto 模式：过滤已见过的通知。"""
    new = []
    for n in notices:
        if n["source"] == "oa":
            if n["id"] in seen["oa_ids"]:
                continue
        else:
            if n["url"] in seen["chem_urls"]:
                continue
        new.append(n)
    return new


def mark_seen(seen, notices):
    for n in notices:
        if n["source"] == "oa":
            seen["oa_ids"][n["id"]] = n.get("date", "")
        else:
            seen["chem_urls"][n["url"]] = n.get("date", "")
    return seen


def filter_manual_window(notices, trigger_ts):
    """manual 模式：以触发时刻为基准，推最近 12 小时。"""
    try:
        t = datetime.fromisoformat(trigger_ts[:19])  # 截前19字符，忽略时区，与解析出的 naive 时间比较
    except Exception:
        t = datetime.now()
    start = t - timedelta(hours=WINDOW_HOURS)
    out = []
    for n in notices:
        if n["source"] == "oa" and n.get("dt"):
            # OA 有精确时间：只用 dt 判断，不 fallback 到日期
            try:
                if datetime.strptime(n["dt"], "%Y-%m-%d %H:%M") >= start:
                    out.append(n)
            except ValueError:
                pass
            continue
        if n.get("date"):
            # 学院只有日期：按日期近似过滤
            try:
                if datetime.strptime(n["date"], "%Y-%m-%d").date() >= start.date():
                    out.append(n)
            except ValueError:
                pass
    return out


# ---------- DeepSeek ----------
def call_deepseek(notices):
    payload = []
    for i, n in enumerate(notices):
        payload.append({
            "id": str(i),
            "title": n["title"],
            "date": n.get("date", ""),
            "summary": (n.get("summary") or "")[:200],
            "org": n.get("org") or "",
            "source": n["source"],
            "url": n["url"],
        })
    with open(PROMPT, encoding="utf-8") as f:
        prompt = f.read()
    resp = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 1024,
        },
        timeout=90,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


# ---------- QQ ----------
def qq_get_token(app_id, app_secret):
    r = requests.post(
        "https://api.bot.qq.com/app/getAppAccessToken",
        json={"appId": app_id, "clientSecret": app_secret},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"getAppAccessToken no token: {data}")
    return token


def _markdown_to_plain(text):
    t = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1 \2", text)
    t = t.replace("**", "").replace("##", "").replace(">", "")
    return t


def qq_send(token, openid, markdown_text):
    for msg_type, content in ((2, markdown_text), (0, _markdown_to_plain(markdown_text))):
        body = {"msg_type": msg_type}
        if msg_type == 2:
            body["markdown"] = {"content": content}
        else:
            body["content"] = content
        try:
            r = requests.post(
                f"https://api.bot.qq.com/v2/users/{openid}/messages",
                headers={
                    "Authorization": f"QQBot {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json=body,
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"[qq] request error: {e}", file=sys.stderr)
            return False
        if r.status_code == 200:
            return True
        print(f"[qq] msg_type={msg_type} failed http={r.status_code} {r.text[:300]}", file=sys.stderr)
    return False


# ---------- 文案 ----------
def build_message(rel, oth, stamp, mode):
    head = "## JLU通知 · 手动更新（最近12小时）" if mode == "manual" else f"## JLU通知 · {stamp}"
    lines = [head]
    if rel:
        lines.append("")
        lines.append(f"### 与你相关 {len(rel)} 条")
        for n in rel:
            lines.append("")
            lines.append(f"- **{n['title']}**")
            lines.append(f"  - 关联：{n.get('why', '')}")
            lines.append(f"  - 日期：{n.get('date', '')}")
            lines.append(f"  - [查看链接]({n['url']})")
    if oth:
        cats = {}
        for n in oth:
            c = n.get("cat", "其他")
            cats[c] = cats.get(c, 0) + 1
        summary = "、".join(f"{k} {v} 条" for k, v in cats.items())
        lines.append("")
        lines.append(f"### 其余 {len(oth)} 条简要")
        lines.append(f"{summary}")
        lines.append("")
        lines.append("（全部通知见仓库 data/inbox）")
    return "\n".join(lines)


# ---------- main ----------
def main():
    if not DEEPSEEK_API_KEY:
        print("[error] DEEPSEEK_API_KEY 未配置", file=sys.stderr)
        sys.exit(2)
    if not (QQ_APP_ID and QQ_APP_SECRET and QQ_USER_OPENID):
        print("[error] QQ 配置不完整", file=sys.stderr)
        sys.exit(2)

    seen = load_seen()
    inbox_files = sorted(glob.glob(os.path.join(INBOX, "*.json")))
    all_notices = []
    for p in inbox_files:
        try:
            all_notices.extend(parse_inbox_file(p))
        except Exception as e:
            print(f"[warn] 跳过 {os.path.basename(p)}: {e}", file=sys.stderr)

    if MODE == "manual":
        trigger = TRIGGER_TS or datetime.now().isoformat()
        new = filter_manual_window(all_notices, trigger)
        print(f"[info] manual 模式：触发时刻={trigger}，12小时内通知={len(new)}")
    else:
        new = dedup(all_notices, seen)
        print(f"[info] auto 模式：inbox={len(inbox_files)} 总通知={len(all_notices)} 新增={len(new)}")

    if not new:
        print("[info] 无通知，结束")
        return

    result = call_deepseek(new)
    idx = {str(i): n for i, n in enumerate(new)}
    rel, oth = [], []
    for r in result.get("relevant", []):
        n = idx.get(str(r.get("id")))
        if n:
            n["why"] = r.get("why", "")
            rel.append(n)
    for r in result.get("others", []):
        n = idx.get(str(r.get("id")))
        if n:
            n["cat"] = r.get("cat", "其他")
            oth.append(n)
    covered = {str(r.get("id")) for r in result.get("relevant", []) + result.get("others", [])}
    for i, n in idx.items():
        if i not in covered:
            n["cat"] = "未分类"
            oth.append(n)

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = build_message(rel, oth, stamp, MODE)
    print(msg)

    token = qq_get_token(QQ_APP_ID, QQ_APP_SECRET)
    if not qq_send(token, QQ_USER_OPENID, msg):
        print("[error] QQ 推送失败", file=sys.stderr)
        sys.exit(1)

    if MODE == "auto":
        mark_seen(seen, new)
        save_seen(seen)
        print(f"[info] auto：已更新 seen（相关 {len(rel)}，其余 {len(oth)}）")
    else:
        print(f"[info] manual：不更新 seen（相关 {len(rel)}，其余 {len(oth)}）")


if __name__ == "__main__":
    main()
