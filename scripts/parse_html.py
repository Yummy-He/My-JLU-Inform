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

    source: chem / bks / yjs（用于去重与来源标记）
    返回: [{id(url), title, url, date, summary, org:"", source}]
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select("ul.list-text li[id^='line_']"):
        a = li.select_one("a.tit")
        if not a or not a.get("href"):
            continue
        href = a["href"]
        # 从相对路径里提取 /info/xxx/yyy.htm，拼绝对 URL（对 ../info 与 ../../info 均适用）
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
            "id": url,                          # 学院以 url 作为去重 id
            "title": a.get_text(strip=True),
            "url": url,
            "date": date,
            "summary": summary,
            "org": "",
            "source": source,
        })
    return items


def _oa_abs_date(raw, fetched_date):
    """把 OA 的「今天/昨天」时间换算为绝对日期 YYYY-MM-DD。"""
    s = raw.replace("\xa0", " ").replace("&nbsp;", " ").strip()
    if s.startswith("今天"):
        return fetched_date
    if s.startswith("昨天"):
        try:
            d = datetime.strptime(fetched_date, "%Y-%m-%d") - timedelta(days=1)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            return fetched_date
    return s


def parse_oa(html, fetched_date):
    """解析学校 OA 列表页 HTML（无需登录）。

    fetched_date: 抓取日期 YYYY-MM-DD（用于换算今天/昨天）
    返回: [{id(数字字符串), title, url, date, summary:"", org, source:"oa"}]
    """
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
        date = _oa_abs_date(raw_time, fetched_date)

        items.append({
            "id": oid,                          # OA 以数字 id 去重
            "title": title,
            "url": f"{OA_BASE}/PortalInformation!getInformation.action?id={oid}&channelId=179577",
            "date": date,
            "summary": "",                      # OA 列表无摘要
            "org": org,
            "source": "oa",
        })
    return items
