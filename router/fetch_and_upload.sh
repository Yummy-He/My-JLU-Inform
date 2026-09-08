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

# ===== 需你填写 =====
GH_TOKEN=""
GH_REPO="Yummy-He/My-JLU-Inform"
# ===================
[ -f "$WORK/gh_token.txt" ] && GH_TOKEN=$(cat "$WORK/gh_token.txt")

UA="Mozilla/5.0 (Linux; mipsel) NotifyBot/1.0"
BASE="https://chem.jlu.edu.cn/xwtz"

# 抓学院：首页 + 动态解析「下页」抓第2页
fetch_list() {
  # $1=栏目相对路径  $2=输出前缀
  curl -s -m 30 -A "$UA" -o "$TMP/${2}_p1.htm" "$BASE/$1"
  next=$(grep -o 'class="p_next p_fun"><a href="[^"]*"' "$TMP/${2}_p1.htm" \
         | head -1 | sed -n 's/.*href="\([^"]*\)".*/\1/p')
  if [ -n "$next" ]; then
    curl -s -m 30 -A "$UA" -o "$TMP/${2}_p2.htm" "$BASE/$next"
  else
    : > "$TMP/${2}_p2.htm"
  fi
}
fetch_list "tzgg.htm"     chem
fetch_list "tzgg/bks.htm" bks
fetch_list "tzgg/yjs.htm" yjs

# 抓 OA 内网首页（无需登录，30 条，含置顶）
curl -s -m 30 -k -A "$UA" --max-filesize 2097152 \
  -c "$TMP/oa_cookie.txt" -b "$TMP/oa_cookie.txt" \
  -o "$TMP/oa.htm" \
  "https://oa.jlu.edu.cn/defaultroot/PortalInformation!jldxList.action?channelId=179577"

# jq 打包
OUT="$WORK/out/$STAMP.json"
jq -n \
  --arg stamp "$STAMP" \
  --rawfile chem1 "$TMP/chem_p1.htm" --rawfile chem2 "$TMP/chem_p2.htm" \
  --rawfile bks1  "$TMP/bks_p1.htm"  --rawfile bks2  "$TMP/bks_p2.htm" \
  --rawfile yjs1  "$TMP/yjs_p1.htm"  --rawfile yjs2  "$TMP/yjs_p2.htm" \
  --rawfile oa    "$TMP/oa.htm" \
  '{stamp:$stamp, ts:(now|strftime("%Y-%m-%dT%H:%M:%S%z")),
    pages:{chem1:$chem1, chem2:$chem2, bks1:$bks1, bks2:$bks2,
           yjs1:$yjs1, yjs2:$yjs2, oa:$oa}}' > "$OUT"

# GitHub Contents API 上传（新文件 PUT 无需 sha）
B64=$(openssl base64 -A -in "$OUT")
HTTP=$(curl -s -o /dev/null -w "%{http_code}" -m 60 -X PUT \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$GH_REPO/contents/data/inbox/$STAMP.json" \
  -d "{\"message\":\"inbox $STAMP\",\"content\":\"$B64\"}")

if [ "$HTTP" = "201" ] || [ "$HTTP" = "200" ]; then
  echo "[ok] upload $STAMP"
else
  cp "$OUT" "$WORK/fail/$STAMP.json"
  echo "[fail] upload $STAMP http=$HTTP (已存 fail/ 可补传)"
fi
