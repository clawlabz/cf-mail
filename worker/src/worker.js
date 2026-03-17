/**
 * cf-mail Worker — 通用邮件接收 + 验证码/链接提取
 *
 * 支持多种存储后端（通过 STORAGE_BACKEND 环境变量切换）：
 *   - "kv"       — Cloudflare Workers KV（默认，免费 1000 写/天）
 *   - "supabase" — Supabase PostgreSQL（免费额度大，基本无限制）
 *   - "upstash"  — Upstash Redis（免费 10000 命令/天）
 *   - "custom"   — 自定义 HTTP API
 *
 * API 端点（不变）：
 *   GET /code?email=<prefix>   — 查询验证码
 *   GET /link?email=<prefix>   — 查询验证链接
 *   GET /raw?email=<prefix>    — 查看原始邮件
 *   GET /health                — 健康检查
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
  const hrefPattern = /href=["']?(https?:\/\/[^\s"'<>]+)/gi;
  let match;
  while ((match = hrefPattern.exec(text)) !== null) {
    const url = match[1];
    if (LINK_KEYWORDS.some((kw) => url.toLowerCase().includes(kw))) {
      return url;
    }
  }
  const urlPattern = /(https?:\/\/[^\s"'<>]+)/gi;
  while ((match = urlPattern.exec(text)) !== null) {
    const url = match[1];
    if (LINK_KEYWORDS.some((kw) => url.toLowerCase().includes(kw))) {
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

// ══════════════════════════════════════════════════════════════
// 存储抽象层
// ══════════════════════════════════════════════════════════════

function getStorage(env) {
  const backend = (env.STORAGE_BACKEND || "kv").toLowerCase();
  switch (backend) {
    case "supabase":
      return new SupabaseStorage(env);
    case "upstash":
      return new UpstashStorage(env);
    case "custom":
      return new CustomStorage(env);
    default:
      return new KVStorage(env);
  }
}

// ─── KV 存储（默认） ───

class KVStorage {
  constructor(env) {
    this.kv = env.EMAIL_KV;
  }
  async put(key, value, ttl = 300) {
    await this.kv.put(key, JSON.stringify(value), { expirationTtl: ttl });
  }
  async get(key) {
    const data = await this.kv.get(key);
    return data ? JSON.parse(data) : null;
  }
}

// ─── Supabase 存储 ───

class SupabaseStorage {
  constructor(env) {
    this.url = (env.SUPABASE_URL || "").replace(/\/$/, "");
    this.key = env.SUPABASE_ANON_KEY || "";
    this.table = env.SUPABASE_TABLE || "cf_mail_store";
  }

  _headers() {
    return {
      apikey: this.key,
      Authorization: `Bearer ${this.key}`,
      "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates",
    };
  }

  async put(key, value, ttl = 300) {
    const expiresAt = new Date(Date.now() + ttl * 1000).toISOString();
    await fetch(`${this.url}/rest/v1/${this.table}`, {
      method: "POST",
      headers: this._headers(),
      body: JSON.stringify({
        key,
        value: JSON.stringify(value),
        expires_at: expiresAt,
      }),
    });
  }

  async get(key) {
    const now = new Date().toISOString();
    const resp = await fetch(
      `${this.url}/rest/v1/${this.table}?key=eq.${encodeURIComponent(key)}&expires_at=gt.${now}&select=value&limit=1`,
      { headers: this._headers() }
    );
    const rows = await resp.json();
    if (Array.isArray(rows) && rows.length > 0) {
      try {
        return JSON.parse(rows[0].value);
      } catch {
        return null;
      }
    }
    return null;
  }
}

// ─── Upstash Redis 存储 ───

class UpstashStorage {
  constructor(env) {
    this.url = (env.UPSTASH_URL || "").replace(/\/$/, "");
    this.token = env.UPSTASH_TOKEN || "";
  }

  async _cmd(args) {
    const resp = await fetch(`${this.url}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(args),
    });
    return resp.json();
  }

  async put(key, value, ttl = 300) {
    await this._cmd(["SET", key, JSON.stringify(value), "EX", ttl]);
  }

  async get(key) {
    const result = await this._cmd(["GET", key]);
    if (result && result.result) {
      try {
        return JSON.parse(result.result);
      } catch {
        return null;
      }
    }
    return null;
  }
}

// ─── 自定义 HTTP API 存储 ───

class CustomStorage {
  constructor(env) {
    this.url = (env.CUSTOM_STORAGE_URL || "").replace(/\/$/, "");
    this.authHeader = env.CUSTOM_STORAGE_AUTH || "";
  }

  _headers() {
    const h = { "Content-Type": "application/json" };
    if (this.authHeader) h["Authorization"] = this.authHeader;
    return h;
  }

  async put(key, value, ttl = 300) {
    await fetch(`${this.url}/put`, {
      method: "POST",
      headers: this._headers(),
      body: JSON.stringify({ key, value, ttl }),
    });
  }

  async get(key) {
    const resp = await fetch(
      `${this.url}/get?key=${encodeURIComponent(key)}`,
      { headers: this._headers() }
    );
    const data = await resp.json();
    return data && data.value ? data.value : null;
  }
}

// ══════════════════════════════════════════════════════════════
// Email 入口
// ══════════════════════════════════════════════════════════════

async function handleEmail(message, env) {
  const to = (message.to || "").toLowerCase();
  const from = message.from || "";
  const localPart = to.split("@")[0];

  if (!localPart) return;

  const store = getStorage(env);

  try {
    const rawEmail = await new Response(message.raw).text();
    const subject = extractSubject(rawEmail);
    const code = extractCode(rawEmail);
    const link = extractLink(rawEmail);
    const timestamp = Date.now();

    if (code) {
      await store.put(`code:${localPart}`, { code, from, to, subject, timestamp });
      console.log(`[CODE] ${to} -> ${code}`);
    }

    if (link) {
      await store.put(`link:${localPart}`, { link, from, to, subject, timestamp });
      console.log(`[LINK] ${to} -> ${link.substring(0, 80)}...`);
    }

    await store.put(`raw:${localPart}`, {
      from,
      to,
      subject,
      bodyPreview: rawEmail.slice(0, 4000),
      hasCode: !!code,
      hasLink: !!link,
      timestamp,
    });

    if (!code && !link) {
      console.log(`[RAW] ${to} -> no code/link found (subject: ${subject})`);
    }
  } catch (err) {
    console.error(`[ERR] ${to}: ${err.message}`);
  }
}

// ══════════════════════════════════════════════════════════════
// HTTP API
// ══════════════════════════════════════════════════════════════

async function handleFetch(request, env) {
  const url = new URL(request.url);

  if (request.method === "OPTIONS") {
    return new Response(null, {
      headers: {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "X-Auth-Key, Content-Type",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
      },
    });
  }

  const authKey =
    request.headers.get("X-Auth-Key") || url.searchParams.get("key");
  if (authKey !== env.AUTH_KEY) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const cors = { "Access-Control-Allow-Origin": "*" };
  const store = getStorage(env);

  if (url.pathname === "/code") {
    return handleQuery(store, "code", url, cors);
  }
  if (url.pathname === "/link") {
    return handleQuery(store, "link", url, cors);
  }
  if (url.pathname === "/raw") {
    return handleQuery(store, "raw", url, cors);
  }

  if (url.pathname === "/health") {
    return Response.json(
      {
        ok: true,
        domain: env.EMAIL_DOMAIN,
        storage: (env.STORAGE_BACKEND || "kv").toLowerCase(),
        time: new Date().toISOString(),
        version: "0.2.0",
      },
      { headers: cors }
    );
  }

  return Response.json({ error: "Not Found" }, { status: 404, headers: cors });
}

async function handleQuery(store, prefix, url, cors) {
  const email = (url.searchParams.get("email") || "").toLowerCase().trim();
  if (!email) {
    return Response.json(
      { error: "Missing email param" },
      { status: 400, headers: cors }
    );
  }

  const data = await store.get(`${prefix}:${email}`);
  if (!data) {
    return Response.json({ found: false }, { headers: cors });
  }

  return Response.json({ found: true, ...data }, { headers: cors });
}

// ─── 导出 ───

export default {
  email: handleEmail,
  fetch: handleFetch,
};
