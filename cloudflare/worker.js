/**
 * QQ 手动触发监听器（Cloudflare Worker）
 *
 * 部署：Cloudflare Workers，绑定 secrets：
 *   GH_TOKEN       GitHub fine-grained PAT（Contents 写）
 *   QQ_APP_ID / QQ_APP_SECRET
 *
 * 收到用户私聊「更新」→ 写 GitHub data/trigger/<ts>.json → 回复 QQ。
 * 后续由路由器轮询该 trigger 文件，完成抓取+触发 Action。
 */
const REPO = "Yummy-He/My-JLU-Inform";
const GH_API = `https://api.github.com/repos/${REPO}`;

async function qqToken(env) {
  const r = await fetch("https://api.bot.qq.com/app/getAppAccessToken", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ appId: env.QQ_APP_ID, clientSecret: env.QQ_APP_SECRET }),
  });
  const j = await r.json();
  return j.access_token;
}

async function qqReply(env, token, openid, text) {
  await fetch(`https://api.bot.qq.com/v2/users/${openid}/messages`, {
    method: "POST",
    headers: {
      "Authorization": `QQBot ${token}`,
      "Content-Type": "application/json; charset=utf-8",
    },
    body: JSON.stringify({ msg_type: 0, content: text }),
  });
}

async function writeTrigger(env, ts) {
  const body = JSON.stringify({ ts });
  const b64 = btoa(unescape(encodeURIComponent(body)));
  const name = `trigger_${Date.now()}.json`;
  const r = await fetch(`${GH_API}/contents/data/trigger/${name}`, {
    method: "PUT",
    headers: {
      "Authorization": `token ${env.GH_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message: `manual trigger ${ts}`, content: b64 }),
  });
  return r.ok;
}

export default {
  async fetch(request, env) {
    if (request.method === "GET") {
      return new Response("ok", { status: 200 });
    }
    if (request.method !== "POST") {
      return new Response("method not allowed", { status: 405 });
    }
    let body;
    try {
      body = await request.json();
    } catch (e) {
      return new Response("bad json", { status: 400 });
    }

    const op = body.op;
    const t = body.t;
    const d = body.d || {};

    // 鉴权/心跳等非事件消息直接忽略
    if (op !== 0 || !t) {
      return new Response("ok", { status: 200 });
    }

    if (t === "C2C_MESSAGE_CREATE") {
      const content = (d.content || "").trim();
      const openid = (d.author && d.author.user_openid) || "";
      if (/更新|刷新|推送/.test(content)) {
        const ts = new Date().toISOString();
        let ok = false;
        try {
          ok = await writeTrigger(env, ts);
        } catch (e) {
          ok = false;
        }
        let token;
        try {
          token = await qqToken(env);
          await qqReply(env, token, openid,
            ok ? "✅ 已收到更新请求，约 3~5 分钟后推送最近 12 小时通知"
               : "❌ 触发失败，请稍后重试");
        } catch (e) {
          // 回复失败不阻断
        }
        return new Response(ok ? "triggered" : "trigger_failed", { status: 200 });
      }
      return new Response("ignored", { status: 200 });
    }

    return new Response("ok", { status: 200 });
  },
};
