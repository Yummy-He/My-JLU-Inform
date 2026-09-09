# -*- coding: utf-8 -*-
"""主逻辑：解析 inbox → 去重/时间窗 → DeepSeek 分类 → 全文/简报 → QQ 推送。

两种模式（互不干扰）：
- auto   （定时触发）：seen.json 增量去重，只推本周期新增；推送后更新 seen，并把 inbox 清洗为 data/notices。
- manual （QQ「更新」触发）：以触发时刻为基准推最近 12 小时，不读不写 seen，不清洗 inbox。
"""
import os
import re
import sys
import json
import glob
from datetime import datetime, timedelta, timezone

import requests

from parse_html import parse_chem, parse_oa, parse_chem_detail, parse_oa_detail

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(REPO, "data", "inbox")
NOTICES = os.path.join(REPO, "data", "notices")
SEEN = os.path.join(REPO, "data", "seen.json")
PROMPT = os.path.join(REPO, "scripts", "prompt.md")

UA = "Mozilla/5.0 (compatible; JLU-Notify/1.0)"

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
QQ_APP_ID = os.environ.get("QQ_APP_ID", "")
QQ_APP_SECRET = os.environ.get("QQ_APP_SECRET", "")
QQ_USER_OPENID = os.environ.get("QQ_USER_OPENID", "")

MODE = os.environ.get("MODE", "auto")          # auto / manual
TRIGGER_TS = os.environ.get("TRIGGER_TS", "")  # 手动触发时刻（ISO，UTC 带 Z）
WINDOW_HOURS = 12
CST = timezone(timedelta(hours=8))


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
def _dedup_within(notices):
    seen = set()
    out = []
    for n in notices:
        key = ("oa", n["id"]) if n["source"] == "oa" else ("chem", n["url"])
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _ts_date(ts):
    """从 ts 字符串解析出 YYYY-MM-DD，兼容 ISO 和 MM/DD/YYYY。"""
    if not ts:
        return datetime.now().strftime("%Y-%m-%d")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", ts)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", ts)
    if m:
        return f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    return datetime.now().strftime("%Y-%m-%d")


def parse_inbox_file(path):
    """解析单个 inbox JSON，返回 {stamp, ts, notices}。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    ts = data.get("ts", "")
    fetched_date = _ts_date(ts)
    pages = data.get("pages", {})
    oa_details = data.get("oa_details", {})

    notices = []
    for key, src in (("chem1", "chem"), ("chem2", "chem"),
                     ("bks1", "bks"), ("bks2", "bks"),
                     ("yjs1", "yjs"), ("yjs2", "yjs")):
        html = pages.get(key, "")
        if html:
            notices.extend(parse_chem(html, src))

    oa_html = pages.get("oa", "")
    if oa_html:
        oa_items = parse_oa(oa_html, fetched_date)
        for n in oa_items:
            dh = oa_details.get(n["id"], "")
            if dh:
                try:
                    n["fulltext"] = parse_oa_detail(dh)["fulltext"]
                except Exception:
                    n["fulltext"] = ""
        notices.extend(oa_items)

    notices = _dedup_within(notices)
    return {"stamp": data.get("stamp", ""), "ts": ts, "notices": notices}


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


def _parse_trigger(trigger_ts):
    """把触发时刻统一转成北京时间(naive)。"""
    if trigger_ts:
        s = trigger_ts.strip()
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            t = datetime.fromisoformat(s)
            if t.tzinfo is not None:
                return t.astimezone(CST).replace(tzinfo=None)
            return t
        except ValueError:
            pass
    return datetime.now()


def filter_manual_window(notices, trigger_ts):
    """manual 模式：以触发时刻为基准，推最近 12 小时。"""
    t = _parse_trigger(trigger_ts)
    start = t - timedelta(hours=WINDOW_HOURS)
    out = []
    for n in notices:
        if n["source"] == "oa" and n.get("dt"):
            try:
                if datetime.strptime(n["dt"], "%Y-%m-%d %H:%M") >= start:
                    out.append(n)
            except ValueError:
                pass
            continue
        if n.get("date"):
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
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 2048,
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    return json.loads(content)


# ---------- 详情正文 ----------
def fetch_chem_fulltext(n):
    """为学院通知抓详情页正文；OA 的正文已由路由器抓取并写入 inbox。"""
    if n["source"] == "oa":
        return n
    if n.get("fulltext"):
        return n
    try:
        r = requests.get(n["url"], headers={"User-Agent": UA}, timeout=20)
        r.raise_for_status()
        r.encoding = "utf-8"
        d = parse_chem_detail(r.text)
        n["fulltext"] = (d.get("fulltext") or "").strip() or (n.get("summary") or "").strip()
    except Exception as e:
        print(f"[warn] 详情获取失败 {n['url']}: {e}", file=sys.stderr)
        n["fulltext"] = (n.get("summary") or "").strip()
    return n


# ---------- QQ ----------
def qq_get_token(app_id, app_secret):
    r = requests.post(
        "https://api.bot.qq.com/app/getAppAccessToken",
        json={"appId": app_id, "clientSecret": app_secret},
        timeout=30,
    )
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError(f"getAppAccessToken 无 token: {r.text[:200]}")
    return token


def _markdown_to_plain(text):
    t = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1 \2", text)
    t = t.replace("**", "").replace("##", "").replace(">", "")
    return t


def _chunk_text(text, size=1600):
    if len(text) <= size:
        return [text]
    chunks = []
    cur = ""
    for para in text.split("\n"):
        if len(cur) + len(para) + 1 > size and cur:
            chunks.append(cur)
            cur = para
        else:
            cur = cur + "\n" + para if cur else para
    if cur:
        chunks.append(cur)
    return chunks


def _qq_send_one(token, openid, text):
    for msg_type, content in ((2, text), (0, _markdown_to_plain(text))):
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


def qq_send(token, openid, markdown_text):
    for chunk in _chunk_text(markdown_text):
        if not _qq_send_one(token, openid, chunk):
            return False
    return True


# ---------- 文案 ----------
def _clip(s, maxlen=900):
    s = (s or "").strip()
    if len(s) <= maxlen:
        return s
    return s[:maxlen].rstrip() + "……（详见原文链接）"


def build_message(rel, oth, stamp, mode):
    head = "## JLU通知 · 手动更新（最近12小时）" if mode == "manual" else f"## JLU通知 · {stamp}"
    lines = [head]
    if rel:
        lines.append("")
        lines.append(f"### 🔔 与你相关 {len(rel)} 条")
        for n in rel:
            lines.append("")
            lines.append(f"**{n['title']}**")
            lines.append(f"- 关联：{n.get('why', '')}")
            lines.append(f"- 日期：{n.get('date', '')}")
            ft = _clip(n.get("fulltext") or n.get("summary") or "", 2500)
            if ft:
                lines.append(f"- 全文：{ft}")
            lines.append(f"- 原文：{n['url']}")
    if oth:
        cats = {}
        for n in oth:
            c = n.get("cat") or "其他"
            cats.setdefault(c, []).append(n)
        lines.append("")
        lines.append(f"### 📋 其他通知简报 {len(oth)} 条")
        for c, items in cats.items():
            lines.append(f"**{c}**（{len(items)}）")
            for n in items:
                brief = _clip(n.get("brief") or n.get("title") or "", 120)
                lines.append(f"- {brief}")
        lines.append("")
        lines.append("（完整清单见仓库 data/notices）")
    return "\n".join(lines)


# ---------- 清洗 ----------
def clean_inbox(batches):
    os.makedirs(NOTICES, exist_ok=True)
    for path, stamp, ts, notices in batches:
        name = os.path.splitext(os.path.basename(path))[0]
        if not stamp:
            stamp = name
        dest = os.path.join(NOTICES, f"{stamp}.json")
        with open(dest, "w", encoding="utf-8") as f:
            json.dump({"stamp": stamp, "ts": ts, "notices": notices}, f, ensure_ascii=False, indent=2)
        try:
            os.remove(path)
        except OSError as e:
            print(f"[warn] 删除 inbox 失败 {path}: {e}", file=sys.stderr)
        print(f"[info] 已清洗 inbox -> {os.path.relpath(dest, REPO)}")


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
    batches = []
    all_notices = []
    for p in inbox_files:
        try:
            parsed = parse_inbox_file(p)
            batches.append((p, parsed["stamp"], parsed["ts"], parsed["notices"]))
            all_notices.extend(parsed["notices"])
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
            n["brief"] = r.get("brief", "")
            oth.append(n)
    covered = {str(r.get("id")) for r in result.get("relevant", []) + result.get("others", [])}
    for i, n in idx.items():
        if i not in covered:
            n["cat"] = "未分类"
            n["brief"] = n["title"]
            oth.append(n)

    # 抓学院详情正文（OA 已由路由器抓好）
    for n in new:
        fetch_chem_fulltext(n)

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
        clean_inbox(batches)
        print(f"[info] auto：已更新 seen（相关 {len(rel)}，其余 {len(oth)}）")
    else:
        print(f"[info] manual：不更新 seen、不清洗 inbox（相关 {len(rel)}，其余 {len(oth)}）")


if __name__ == "__main__":
    main()

