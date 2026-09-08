/**
 * QQ 手动触发监听器（Cloudflare Worker）
 *
 * Secrets：GH_TOKEN、QQ_APP_ID、QQ_APP_SECRET
 *
 * 流程：
 *  - QQ 配置回调时发 op=13 验证 → 用 QQ_APP_SECRET 做 Ed25519 签名回包
 *  - 用户私聊「更新」→ 写 GitHub data/trigger/<ts>.json → 回复 QQ
 */
const REPO = "Yummy-He/My-JLU-Inform";
const GH_API = `https://api.github.com/repos/${REPO}`;

// 与 QQ 官方 Go 示例一致：secret 重复到 >=32 字节再截前 32 字节作为 seed
function buildSeed(secret) {
  let seed = secret;
  while (seed.length < 32) seed += seed;
  return seed.slice(0, 32);
}

async function ed25519Sign(secret, dataStr) {
  const seed = buildSeed(secret);
  const seedBytes = new TextEncoder().encode(seed);
  const key = await crypto.subtle.importKey(
    "raw", seedBytes, { name: "Ed25519" }, false, ["sign"]);
  const msg = new TextEncoder().encode(dataStr);
  const sig = await crypto.subtle.sign({ name: "Ed25519" }, key, msg);
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0")).join("");
}

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
    if (request.method !== "POST") {
      return new Response("ok", { status: 200 });
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

    // 回调地址验证：op=13，签名 event_ts + plain_token 后回包
    if (op === 13) {
      const plain_token = d.plain_token || "";
      const event_ts = d.event_ts || "";
      const signature = await ed25519Sign(env.QQ_APP_SECRET, event_ts + plain_token);
      return Response.json({ plain_token, signature });
    }

    if (op === 0 && t === "C2C_MESSAGE_CREATE") {
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
        try {
          const token = await qqToken(env);
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
