/**
 * QQ 手动触发监听器（Cloudflare Worker）
 *
 * Secrets：GH_TOKEN、QQ_APP_ID、QQ_APP_SECRET
 *
 * 流程：
 *  - QQ 配置回调时发 op=13 验证 → 用 QQ_APP_SECRET 做 Ed25519 签名回包
 *  - 用户私聊「更新」→ 写 GitHub data/trigger/<ts>.json → 回复 QQ
 *
 * 注意：Cloudflare Workers 不支持 raw Ed25519 私钥 import，
 *       因此这里用纯 JS 实现 Ed25519（仅用 WebCrypto 做 SHA-512），
 *       已通过 QQ 官方示例与 RFC 8032 测试向量验证。
 */
const REPO = "Yummy-He/My-JLU-Inform";
const GH_API = `https://api.github.com/repos/${REPO}`;

/* ---------------- Ed25519（纯 JS） ---------------- */
const ED_P = (1n << 255n) - 19n;
const ED_L = (1n << 252n) + 27742317777372353535851937790883648493n;
const ED_D = 37095705934669439343138083508754565189542113879843219016388785533085940283555n;
const ED_By = 46316835694926478169428394003475163141307993866256225615783033603165251855960n;
const ED_Bx = 15112221349535400772501151409588531511454012693041857206046113283949847762202n;

function edPow(base, exp, mod) {
  let r = 1n;
  base %= mod;
  while (exp > 0n) {
    if (exp & 1n) r = (r * base) % mod;
    base = (base * base) % mod;
    exp >>= 1n;
  }
  return r;
}
function edInv(a) { return edPow(a, ED_P - 2n, ED_P); }
const edMod = (a) => { a %= ED_P; return a < 0n ? a + ED_P : a; };

function edAdd(p, q) {
  const [X1, Y1, Z1, T1] = p;
  const [X2, Y2, Z2, T2] = q;
  const A = edMod((Y1 - X1) * (Y2 - X2));
  const B = edMod((Y1 + X1) * (Y2 + X2));
  const C = edMod(T1 * 2n * ED_D * T2);
  const Dd = edMod(Z1 * 2n * Z2);
  const E = edMod(B - A);
  const F = edMod(Dd - C);
  const G = edMod(Dd + C);
  const H = edMod(B + A);
  return [edMod(E * F), edMod(G * H), edMod(F * G), edMod(E * H)];
}
function edDouble(p) {
  const [X1, Y1, Z1] = p;
  const A = edMod(X1 * X1);
  const B = edMod(Y1 * Y1);
  const C = edMod(2n * Z1 * Z1);
  const H = edMod(A + B);
  const E = edMod(H - (X1 + Y1) * (X1 + Y1));
  const G = edMod(A - B);
  const F = edMod(C + G);
  return [edMod(E * F), edMod(G * H), edMod(F * G), edMod(E * H)];
}
function edScalarMul(p, k) {
  let r = [0n, 1n, 1n, 0n];
  let q = p;
  while (k > 0n) {
    if (k & 1n) r = edAdd(r, q);
    q = edDouble(q);
    k >>= 1n;
  }
  return r;
}
const ED_BASE = [ED_Bx, ED_By, 1n, edMod(ED_Bx * ED_By)];

function edEncodePoint(p) {
  const [X, Y, Z] = p;
  const zi = edInv(Z);
  const x = edMod(X * zi);
  const y = edMod(Y * zi);
  const out = new Uint8Array(32);
  let yv = y;
  for (let i = 0; i < 32; i++) {
    out[i] = Number(yv & 255n);
    yv >>= 8n;
  }
  if (x & 1n) out[31] |= 128;
  return out;
}
function edLeInt(bytes) {
  let r = 0n;
  for (let i = 0; i < bytes.length; i++) r |= BigInt(bytes[i]) << (8n * BigInt(i));
  return r;
}
function toHex(bytes) {
  return Array.from(bytes).map((b) => b.toString(16).padStart(2, "0")).join("");
}
async function sha512(data) {
  return new Uint8Array(await crypto.subtle.digest("SHA-512", data));
}

// seed：QQ 官方算法，secret 重复到 >=32 字节后截前 32 字节
function buildSeed(secret) {
  let seed = secret;
  while (seed.length < 32) seed += seed;
  return seed.slice(0, 32);
}

async function ed25519Sign(secret, msgStr) {
  const seedBytes = new TextEncoder().encode(buildSeed(secret));
  const h = await sha512(seedBytes);
  const a = new Uint8Array(32);
  for (let i = 0; i < 32; i++) a[i] = h[i];
  a[0] &= 248;
  a[31] &= 127;
  a[31] |= 64;
  const aInt = edLeInt(a);
  const prefix = h.slice(32);
  const Aenc = edEncodePoint(edScalarMul(ED_BASE, aInt));

  const msg = new TextEncoder().encode(msgStr);
  const rbuf = new Uint8Array(32 + msg.length);
  rbuf.set(prefix, 0);
  rbuf.set(msg, 32);
  const r = edLeInt(await sha512(rbuf)) % ED_L;

  const Renc = edEncodePoint(edScalarMul(ED_BASE, r));
  const kb = new Uint8Array(64 + msg.length);
  kb.set(Renc, 0);
  kb.set(Aenc, 32);
  kb.set(msg, 64);
  const k = edLeInt(await sha512(kb)) % ED_L;
  const S = (r + k * aInt) % ED_L;

  const sig = new Uint8Array(64);
  sig.set(Renc, 0);
  let Sv = S;
  for (let i = 0; i < 32; i++) {
    sig[32 + i] = Number(Sv & 255n);
    Sv >>= 8n;
  }
  return toHex(sig);
}
/* ---------------- Ed25519 end ---------------- */

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
      Authorization: `QQBot ${token}`,
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
      Authorization: `token ${env.GH_TOKEN}`,
      Accept: "application/vnd.github+json",
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