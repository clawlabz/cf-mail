/**
 * cf-mail Worker — 通用邮件接收 + 验证码/链接提取
 *
 * 入口：
 *   email()  — Cloudflare Email Routing 触发
 *   fetch()  — HTTP API 供客户端查询
 *
 * API 端点：
 *   GET /code?email=<prefix>   — 查询验证码
 *   GET /link?email=<prefix>   — 查询验证链接
 *   GET /raw?email=<prefix>    — 查看原始邮件
 *   GET /health                — 健康检查
 *
 * KV 存储结构：
 *   code:<prefix>  — 验证码 JSON，300s TTL
 *   link:<prefix>  — 验证链接 JSON，300s TTL
 *   raw:<prefix>   — 原始邮件 JSON，300s TTL
 */

// ─── 验证码提取 ───

const CODE_PATTERNS = [
  /Verification code:?\s*(\d{6})/i,
  /verification code is:?\s*(\d{4,8})/i,
  /code is\s*(\d{4,8})/i,
  /Your code:?\s*(\d{4,8})/i,
  /code:?\s*(\d{4,8})/i,
  />\s*(\d{4,8})\s*</,
  /\b(\d{6})\b/,
];

const SKIP_CODES = new Set(["177010", "100000", "000000", "123456"]);

function extractCode(text) {
  for (const pattern of CODE_PATTERNS) {
    const match = text.match(pattern);
    if (match && !SKIP_CODES.has(match[1])) {
      return match[1];
    }
  }
  return null;
}

// ─── 验证链接提取 ───

const LINK_KEYWORDS = [
  "verify", "confirm", "activate", "validate",
  "verification", "confirmation", "token=", "code=",
];

function extractLink(text) {
  // 匹配 href 中的链接
  const hrefPattern = /href=["']?(https?:\/\/[^\s"'<>]+)/gi;
  let match;
  while ((match = hrefPattern.exec(text)) !== null) {
    const url = match[1];
    if (LINK_KEYWORDS.some(kw => url.toLowerCase().includes(kw))) {
      return url;
    }
  }

  // 匹配纯文本中的链接
  const urlPattern = /(https?:\/\/[^\s"'<>]+)/gi;
  while ((match = urlPattern.exec(text)) !== null) {
    const url = match[1];
    if (LINK_KEYWORDS.some(kw => url.toLowerCase().includes(kw))) {
      return url;
    }
  }

  return null;
}

// ─── 邮件主题提取 ───

function extractSubject(rawEmail) {
  const match = rawEmail.match(/^Subject:\s*(.+)$/mi);
  return match ? match[1].trim() : "";
}

// ─── Email 入口 ───

async function handleEmail(message, env) {
  const to = (message.to || "").toLowerCase();
  const from = message.from || "";
  const localPart = to.split("@")[0];

  if (!localPart) return;

  try {
    const rawEmail = await new Response(message.raw).text();
    const subject = extractSubject(rawEmail);
    const code = extractCode(rawEmail);
    const link = extractLink(rawEmail);
    const timestamp = Date.now();

    // 存验证码
    if (code) {
      await env.EMAIL_KV.put(
        `code:${localPart}`,
        JSON.stringify({ code, from, to, subject, timestamp }),
        { expirationTtl: 300 }
      );
      console.log(`[CODE] ${to} -> ${code}`);
    }

    // 存验证链接
    if (link) {
      await env.EMAIL_KV.put(
        `link:${localPart}`,
        JSON.stringify({ link, from, to, subject, timestamp }),
        { expirationTtl: 300 }
      );
      console.log(`[LINK] ${to} -> ${link.substring(0, 80)}...`);
    }

    // 始终存原始邮件（用于调试和自定义解析）
    await env.EMAIL_KV.put(
      `raw:${localPart}`,
      JSON.stringify({
        from,
        to,
        subject,
        bodyPreview: rawEmail.slice(0, 4000),
        hasCode: !!code,
        hasLink: !!link,
        timestamp,
      }),
      { expirationTtl: 300 }
    );

    if (!code && !link) {
      console.log(`[RAW] ${to} -> no code/link found (subject: ${subject})`);
    }
  } catch (err) {
    console.error(`[ERR] ${to}: ${err.message}`);
  }
}

// ─── HTTP API ───

async function handleFetch(request, env) {
  const url = new URL(request.url);

  // CORS
  if (request.method === "OPTIONS") {
    return new Response(null, {
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "X-Auth-Key, Content-Type",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
      },
    });
  }

  // 鉴权
  const authKey =
    request.headers.get("X-Auth-Key") || url.searchParams.get("key");
  if (authKey !== env.AUTH_KEY) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const cors = { "Access-Control-Allow-Origin": "*" };

  // GET /code?email=<prefix>
  if (url.pathname === "/code") {
    return handleKVQuery(env, "code", url, cors);
  }

  // GET /link?email=<prefix>
  if (url.pathname === "/link") {
    return handleKVQuery(env, "link", url, cors);
  }

  // GET /raw?email=<prefix>
  if (url.pathname === "/raw") {
    return handleKVQuery(env, "raw", url, cors);
  }

  // GET /health
  if (url.pathname === "/health") {
    return Response.json(
      {
        ok: true,
        domain: env.EMAIL_DOMAIN,
        time: new Date().toISOString(),
        version: "0.1.0",
      },
      { headers: cors }
    );
  }

  return Response.json({ error: "Not Found" }, { status: 404, headers: cors });
}

async function handleKVQuery(env, prefix, url, cors) {
  const email = (url.searchParams.get("email") || "").toLowerCase().trim();
  if (!email) {
    return Response.json(
      { error: "Missing email param" },
      { status: 400, headers: cors }
    );
  }

  const data = await env.EMAIL_KV.get(`${prefix}:${email}`);
  if (!data) {
    return Response.json({ found: false }, { headers: cors });
  }

  return Response.json({ found: true, ...JSON.parse(data) }, { headers: cors });
}

// ─── 导出 ───

export default {
  email: handleEmail,
  fetch: handleFetch,
};
