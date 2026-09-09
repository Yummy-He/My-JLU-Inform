#!/bin/sh
# 路由器轮询手动触发标志（每 3 分钟）
# 部署：/media/AiCard_01/notify/check_trigger.sh
# cron：*/3 * * * * /media/AiCard_01/notify/check_trigger.sh >/dev/null 2>&1
set -u
export PATH=/usr/sbin:/usr/bin:/bin:/sbin

WORK=/media/AiCard_01/notify
GH_TOKEN=""
[ -f "$WORK/gh_token.txt" ] && GH_TOKEN=$(cat "$WORK/gh_token.txt")
[ -z "$GH_TOKEN" ] && exit 0

GH_REPO="Yummy-He/My-JLU-Inform"
API="https://api.github.com/repos/$GH_REPO"
AUTH="Authorization: token $GH_TOKEN"
HDR="Accept: application/vnd.github+json"

# 1) 列出 trigger 目录
LIST=$(curl -s -m 30 -H "$AUTH" -H "$HDR" "$API/contents/data/trigger")
# 判断是否为数组且有文件
NAME=$(echo "$LIST" | jq -r 'if type=="array" and length>0 then .[0].name else empty end' 2>/dev/null)
[ -z "$NAME" ] && exit 0

SHA=$(echo "$LIST" | jq -r '.[0].sha' 2>/dev/null)
CONTENT=$(curl -s -m 30 -H "$AUTH" -H "$HDR" "$API/contents/data/trigger/$NAME" | jq -r '.content' 2>/dev/null)
TS=$(echo "$CONTENT" | base64 -d 2>/dev/null | jq -r '.ts' 2>/dev/null)
[ -z "$TS" ] && exit 0
OPENID=$(echo "$CONTENT" | base64 -d 2>/dev/null | jq -r '.openid // ""' 2>/dev/null)

echo "[trigger] 发现手动触发 $TS，开始抓取..."

# 2) 抓取上传（复用现有脚本；手动触发不再额外派发 auto，避免重复推送）
"$WORK/fetch_and_upload.sh" --no-dispatch

# 3) 触发 workflow（manual 模式 + 触发时刻）
curl -s -m 30 -X POST -H "$AUTH" -H "$HDR" \
  "$API/actions/workflows/digest.yml/dispatches" \
  -d "{\"ref\":\"main\",\"inputs\":{\"mode\":\"manual\",\"trigger_ts\":\"$TS\",\"target_openid\":\"$OPENID\"}}" \
  -o /dev/null

# 4) 删除 trigger 文件
curl -s -m 30 -X DELETE -H "$AUTH" -H "$HDR" \
  "$API/contents/data/trigger/$NAME" \
  -d "{\"message\":\"done\",\"sha\":\"$SHA\"}" -o /dev/null

echo "[trigger] 已完成抓取+触发，清除标志"