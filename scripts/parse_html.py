# -*- coding: utf-8 -*-
"""HTML 解析：化学学院通知 + 学校 OA 通知。"""
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin
from bs4 import BeautifulSoup

CHEM_BASE = "https://chem.jlu.edu.cn"
OA_BASE = "https://oa.jlu.edu.cn/defaultroot"


def parse_chem(html, source):
    """解析化学学院列表页 HTML。

    source: chem / bks / yjs
    返回: [{id(url), title, url, date, dt(None), summary, org, source}]
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("ul.list-text li[id^='line_']"):
        a = li.select_one("a.tit")
        if not a or not a.get("href"):
            continue
        href = a["href"]
        m = re.search(r"/info/\d+/\d+\.htm", href)
        if m:
            url = CHEM_BASE + m.group(0)
        elif href.startswith("http"):
            url = href
        else:
            url = urljoin(CHEM_BASE + "/", href)

        day = li.select_one(".day")
        year = li.select_one(".year")
        abst = li.select_one(".abst")
        date = ""
        if day and year:
            date = f"{year.get_text(strip=True)}-{day.get_text(strip=True)}"
        summary = ""
        if abst:
            summary = re.sub(r"\s+", " ", abst.get_text(" ", strip=True)).strip()

        items.append({
            "id": url,
            "title": a.get_text(strip=True),
            "url": url,
            "date": date,
            "dt": None,                          # 学院无精确时间
            "summary": summary,
            "org": "",
            "source": source,
        })
    return items


def _oa_datetime(raw, fetched_date):
    """把 OA 的「今天/昨天 HH:MM」换成完整时间，返回 (date, dt)。"""
    s = raw.replace("\xa0", " ").replace("&nbsp;", " ").strip()
    m = re.match(r"今天\s+(\d{1,2}:\d{2})", s)
    if m:
        return fetched_date, f"{fetched_date} {m.group(1)}"
    m = re.match(r"昨天\s+(\d{1,2}:\d{2})", s)
    if m:
        try:
            d = datetime.strptime(fetched_date, "%Y-%m-%d") - timedelta(days=1)
            ds = d.strftime("%Y-%m-%d")
        except ValueError:
            ds = fetched_date
        return ds, f"{ds} {m.group(1)}"
    # 已是 2026-09-03 这类具体日期，无精确时间
    return s, None


def parse_oa(html, fetched_date):
    """解析学校 OA 列表页 HTML（无需登录）。"""
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for div in soup.select("div.li.rel"):
        a = div.select_one("a.font14")
        if not a:
            continue
        m = re.search(r"id=(\d+)", a.get("href", ""))
        if not m:
            continue
        oid = m.group(1)
        title = a.get_text(" ", strip=True).replace("[置顶]", "").strip()

        org = ""
        ca = div.select_one("a.column")
        if ca:
            org = ca.get_text(strip=True)

        time_sp = div.select_one("span.time")
        raw_time = time_sp.get_text(" ", strip=True) if time_sp else ""
        date, dt = _oa_datetime(raw_time, fetched_date)

        items.append({
            "id": oid,
            "title": title,
            "url": f"{OA_BASE}/PortalInformation!getInformation.action?id={oid}&channelId=179577",
            "date": date,
            "dt": dt,                            # OA 有精确时间（今天/昨天）
            "summary": "",
            "org": org,
            "source": "oa",
        })
    return items
