#!/bin/sh
# 路由器抓取 + 上传脚本（POSIX sh）
# 部署位置：/media/AiCard_01/notify/fetch_and_upload.sh（TF 卡，持久）
# cron：31 12 * * * 和 1 19 * * *（Padavan 本地 CST）
set -u

export PATH=/usr/sbin:/usr/bin:/bin:/sbin   # curl/jq 在 /usr/sbin

WORK=/media/AiCard_01/notify
TMP="$WORK/tmp"
STAMP=$(date +%Y%m%d_%H%M)
mkdir -p "$TMP" "$WORK/out" "$WORK/fail"

GH_REPO="Yummy-He/My-JLU-Inform"
GH_TOKEN=""
[ -f "$WORK/gh_token.txt" ] && GH_TOKEN=$(cat "$WORK/gh_token.txt")

UA="Mozilla/5.0 (Linux; mipsel) NotifyBot/1.0"

# 抓学院：首页 + 动态解析「下页」抓第2页
fetch_list() {
  # $1=首页完整URL  $2=输出前缀
  curl -s -m 30 -A "$UA" -o "$TMP/${2}_p1.htm" "$1"
  next=$(grep -o 'class="p_next p_fun"><a href="[^"]*"' "$TMP/${2}_p1.htm" \
         | head -1 | sed -n 's/.*href="\([^"]*\)".*/\1/p')
  if [ -n "$next" ]; then
    d=$(dirname "$1")
    curl -s -m 30 -A "$UA" -o "$TMP/${2}_p2.htm" "$d/$next"
  else
    : > "$TMP/${2}_p2.htm"
  fi
}
fetch_list "https://chem.jlu.edu.cn/xwtz/tzgg.htm"     chem
fetch_list "https://chem.jlu.edu.cn/xwtz/tzgg/bks.htm" bks
fetch_list "https://chem.jlu.edu.cn/xwtz/tzgg/yjs.htm" yjs

# 抓 OA 内网首页（无需登录，30 条，含置顶）
curl -s -m 30 -k -A "$UA" --max-filesize 2097152 \
  -c "$TMP/oa_cookie.txt" -b "$TMP/oa_cookie.txt" \
  -o "$TMP/oa.htm" \
  "https://oa.jlu.edu.cn/defaultroot/PortalInformation!jldxList.action?channelId=179577"

# 抓 OA 每条详情页（正文全文，供 Action 使用；OA 仅内网可访问，必须由路由器抓）
jq -n '{}' > "$TMP/oa_details.json"
grep -o 'getInformation\.action?id=[0-9]*&channelId=179577' "$TMP/oa.htm" \
  | sed 's/.*id=\([0-9]*\).*/\1/' | sort -u > "$TMP/oa_ids.txt"
while read -r oid; do
  [ -z "$oid" ] && continue
  curl -s -m 25 -k -A "$UA" -o "$TMP/oa_detail_$oid.htm" \
    "https://oa.jlu.edu.cn/defaultroot/PortalInformation!getInformation.action?id=$oid&channelId=179577"
  if jq --arg id "$oid" --rawfile h "$TMP/oa_detail_$oid.htm" '. + {($id): $h}' \
       "$TMP/oa_details.json" > "$TMP/oa_details.tmp" 2>/dev/null; then
    mv "$TMP/oa_details.tmp" "$TMP/oa_details.json"
  fi
done < "$TMP/oa_ids.txt"

# jq 打包（--rawfile 读文件，避免长字符串作为命令行参数）
OUT="$WORK/out/$STAMP.json"
TS=$(date +"%Y-%m-%dT%H:%M:%S%z")
jq -n \
  --arg stamp "$STAMP" \
  --arg ts "$TS" \
  --rawfile chem1 "$TMP/chem_p1.htm" --rawfile chem2 "$TMP/chem_p2.htm" \
  --rawfile bks1  "$TMP/bks_p1.htm"  --rawfile bks2  "$TMP/bks_p2.htm" \
  --rawfile yjs1  "$TMP/yjs_p1.htm"  --rawfile yjs2  "$TMP/yjs_p2.htm" \
  --rawfile oa    "$TMP/oa.htm" \
  '{stamp:$stamp, ts:$ts,
    pages:{chem1:$chem1, chem2:$chem2, bks1:$bks1, bks2:$bks2,
           yjs1:$yjs1, yjs2:$yjs2, oa:$oa}}' > "$OUT"

# 合并 OA 详情正文
jq -s '.[0] * {oa_details: (.[1] // {})}' "$OUT" "$TMP/oa_details.json" > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"

# 上传：base64 与 body 都走文件，避免命令行参数超限
openssl base64 -A -in "$OUT" > "$WORK/b64.txt"
jq -n --arg msg "inbox $STAMP" --rawfile c "$WORK/b64.txt" '{message:$msg, content:$c}' > "$WORK/body.json"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -m 120 -X PUT \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -d @"$WORK/body.json" \
  "https://api.github.com/repos/$GH_REPO/contents/data/inbox/$STAMP.json")

if [ "$HTTP" = "201" ] || [ "$HTTP" = "200" ]; then
  echo "[ok] upload $STAMP"
else
  cp "$OUT" "$WORK/fail/$STAMP.json"
  echo "[fail] upload $STAMP http=$HTTP (已存 fail/ 可补传)"
fi

# 清理旧文件，避免 TF 卡被占满：out 保留 7 天，fail 保留 30 天
find "$WORK/out" -name '*.json' -mtime +7 -delete 2>/dev/null
find "$WORK/fail" -name '*.json' -mtime +30 -delete 2>/dev/null
# 清理可能残留的过期 OA 详情临时文件
find "$TMP" -name 'oa_detail_*.htm' -mtime +7 -delete 2>/dev/null

