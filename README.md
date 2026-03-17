# cf-mail

Unlimited free disposable emails with auto verification code extraction.

Built on Cloudflare Email Routing + Workers. Pluggable storage backends — start free with KV, scale with Supabase/Redis.

```python
from cf_mail import CloudflareMail

mail = CloudflareMail(domain="yourdomain.com", api_url="https://...", auth_key="...")

email, token = mail.create_email()       # → r7kx2mf@yourdomain.com
code = mail.wait_for_code(token)          # → "482913"
```

## How It Works

```
Your Script                  Cloudflare (free tier)              Website
    │                              │                                │
    │  1. mail.create_email()      │                                │
    │     → random@yourdomain.com  │                                │
    │                              │                                │
    │  2. Register with email  ──────────────────────────────────►  │
    │                              │   3. Website sends OTP email   │
    │                              │ ◄──────────────────────────────│
    │                              │                                │
    │                       4. Email Worker receives mail           │
    │                          extracts code → stores in backend    │
    │                              │                                │
    │  5. mail.wait_for_code() ──► │                                │
    │  6. returns "482913"    ◄──  │                                │
```

**Cloudflare Email Routing** catches all mail → **Worker** extracts codes/links → stores in **your chosen backend** → your script polls the API.

## What You Need

- A **domain** with DNS on Cloudflare (cheap domains start at ~$1/year)
- A **Cloudflare account** (free)

That's it. No API keys to buy, no mailbox to maintain.

## Setup

### Option A: Auto Setup (Recommended)

```bash
pip install cf-mail
python -m cf_mail.setup
```

The wizard asks for your Cloudflare credentials and configures everything automatically:

1. Creates KV storage namespace
2. Adds DNS records (MX + SPF)
3. Generates a secret auth key
4. Deploys the Worker
5. Configures email routing

**Required Cloudflare API Token permissions:**
- Zone: DNS Edit, Email Routing Edit
- Account: Workers Scripts Edit, Workers KV Storage Edit

Create a token at: https://dash.cloudflare.com/profile/api-tokens

You'll also need your **Account ID** and **Zone ID** — both are on your domain's overview page in Cloudflare Dashboard (right sidebar, bottom).

### Option B: Manual Setup

<details>
<summary>Click to expand step-by-step guide</summary>

#### 1. Create KV Namespace

Cloudflare Dashboard → **Storage & Databases** → **KV** → **Create namespace**

Name it `EMAIL_KV`, note the **Namespace ID**.

#### 2. Add DNS Records

Dashboard → your domain → **DNS** → **Records**:

| Type | Name | Content | Priority |
|------|------|---------|----------|
| MX | `@` | `route1.mx.cloudflare.net` | 10 |
| MX | `@` | `route2.mx.cloudflare.net` | 20 |
| MX | `@` | `route3.mx.cloudflare.net` | 30 |
| TXT | `@` | `v=spf1 include:_spf.mx.cloudflare.net ~all` | - |

> **Already using email on this domain?** See [Preserving Existing Email](#preserving-existing-email) below.

#### 3. Generate Auth Key

```bash
openssl rand -hex 32
```

#### 4. Deploy Worker

```bash
cd worker
npm install
```

Edit `wrangler.toml`:
```toml
[[kv_namespaces]]
binding = "EMAIL_KV"
id = "your-namespace-id-here"

[vars]
AUTH_KEY = "your-generated-key-here"
EMAIL_DOMAIN = "yourdomain.com"
```

```bash
npx wrangler login
npx wrangler deploy
```

Note the Worker URL from the output (e.g. `https://email-receiver.xxx.workers.dev`).

#### 5. Enable Email Routing

Dashboard → your domain → **Email** → **Email Routing**:

1. Enable Email Routing
2. Go to **Routing Rules** tab
3. Edit **Catch-all** → Action: **Send to a Worker** → select `email-receiver`
4. Save

#### 6. Test

Send an email containing "654321" to `test@yourdomain.com`, then:

```bash
curl "https://email-receiver.xxx.workers.dev/code?email=test" \
  -H "X-Auth-Key: your-key"
# → {"found":true,"code":"654321",...}
```

</details>

## Usage

### Get Verification Code

```python
from cf_mail import CloudflareMail

mail = CloudflareMail(
    domain="yourdomain.com",
    api_url="https://email-receiver.xxx.workers.dev",
    auth_key="your-secret-key",
)

email, token = mail.create_email()
# → ("a8kx2mf@yourdomain.com", "a8kx2mf")

# ... register on a website with this email ...

code = mail.wait_for_code(token, timeout=120)
# → "482913"
```

### Get Verification Link

```python
email, token = mail.create_email()
# ... register on a website that sends a verification link ...

link = mail.wait_for_link(token, timeout=120)
# → "https://example.com/verify?token=abc123"
```

### Get Raw Email Content

```python
email, token = mail.create_email()
# ... trigger an email ...

result = mail.wait_for_email(token, timeout=60)
if result.found:
    print(result.subject)       # Email subject
    print(result.from_addr)     # Sender
    print(result.body_preview)  # First 4000 chars of raw email
```

### Custom Email Prefix

```python
email, token = mail.create_email(prefix="john-doe-123")
# → ("john-doe-123@yourdomain.com", "john-doe-123")
```

### Batch Registration (Multi-threaded)

```python
import concurrent.futures
from cf_mail import CloudflareMail

mail = CloudflareMail(domain="yourdomain.com", api_url="...", auth_key="...")

def register_one(i):
    email, token = mail.create_email()
    # ... register logic ...
    code = mail.wait_for_code(token, timeout=120)
    return code is not None

with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
    results = list(pool.map(register_one, range(100)))

print(f"Success: {sum(results)}/{len(results)}")
```

### Progress Callback

```python
code = mail.wait_for_code(
    token,
    timeout=120,
    poll_interval=3,
    on_poll=lambda elapsed, total: print(f"Waiting... {elapsed}s/{total}s"),
)
```

## Storage Backends

The Worker supports 4 pluggable storage backends. Switch by setting `STORAGE_BACKEND` in `wrangler.toml`:

| Backend | Env Var | Free Limit | Best For |
|---------|---------|------------|----------|
| **KV** (default) | `STORAGE_BACKEND=kv` | 1,000 writes/day (~300 registrations) | Getting started, low volume |
| **Supabase** | `STORAGE_BACKEND=supabase` | 500MB DB, unlimited API calls | High volume, recommended |
| **Upstash Redis** | `STORAGE_BACKEND=upstash` | 10,000 commands/day | If you already use Upstash |
| **Custom HTTP** | `STORAGE_BACKEND=custom` | Your server's limit | Full control |

### Switching to Supabase (Recommended for High Volume)

1. Create a table in Supabase SQL Editor (run `worker/supabase_schema.sql`):

```sql
create table if not exists cf_mail_store (
  key        text primary key,
  value      text not null,
  expires_at timestamptz not null default (now() + interval '5 minutes')
);
create index if not exists idx_cf_mail_expires on cf_mail_store (expires_at);
alter table cf_mail_store enable row level security;
create policy "Allow anon insert" on cf_mail_store for insert to anon with check (true);
create policy "Allow anon select" on cf_mail_store for select to anon using (true);
```

2. Update `wrangler.toml`:

```toml
[vars]
STORAGE_BACKEND = "supabase"
SUPABASE_URL = "https://xxxxx.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIs..."
SUPABASE_TABLE = "cf_mail_store"
```

3. Deploy: `npx wrangler deploy`

No changes needed in your Python code — the Worker API stays the same.

### Switching to Upstash Redis

```toml
[vars]
STORAGE_BACKEND = "upstash"
UPSTASH_URL = "https://xxxxx.upstash.io"
UPSTASH_TOKEN = "xxxxx"
```

### Switching to Custom HTTP API

Your server needs two endpoints:

- `POST /put` — body: `{"key": "code:abc", "value": {...}, "ttl": 300}`
- `GET /get?key=code:abc` — response: `{"value": {...}}`

```toml
[vars]
STORAGE_BACKEND = "custom"
CUSTOM_STORAGE_URL = "https://your-api.example.com"
CUSTOM_STORAGE_AUTH = "Bearer your-token"
```

## Preserving Existing Email

If your domain already has email (Gmail, QQ Mail, Outlook, etc.), enabling Email Routing will replace the existing MX records. **Your existing email will stop working** unless you add forwarding rules.

**Fix:** Add custom address rules for each address you use. These have higher priority than the catch-all, so your real emails get forwarded normally.

Dashboard → **Email** → **Email Routing** → **Routing Rules** → **Create Address**:

| Custom Address | Action | Destination |
|----------------|--------|-------------|
| `admin@yourdomain.com` | Forward to | `admin@gmail.com` |
| `support@yourdomain.com` | Forward to | `support@gmail.com` |

Or via code:

```python
from cf_mail.setup import add_forwarding_rule

add_forwarding_rule(
    api_token="your-cf-api-token",
    zone_id="your-zone-id",
    source_email="admin@yourdomain.com",
    destination_email="admin@gmail.com",
)
```

## API Reference

### `CloudflareMail(domain, api_url, auth_key, **options)`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `proxy` | `str` | `""` | HTTP proxy, e.g. `http://127.0.0.1:7890` |
| `prefix_length` | `tuple` | `(8, 13)` | Random prefix length range |
| `request_timeout` | `int` | `10` | API timeout in seconds |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `create_email(prefix?)` | `(email, token)` | Generate email address (local, no API call) |
| `wait_for_code(token, timeout?)` | `str` or `None` | Wait for verification code |
| `wait_for_link(token, timeout?)` | `str` or `None` | Wait for verification link |
| `wait_for_email(token, timeout?)` | `EmailResult` | Wait for any email |
| `get_code(token)` | `EmailResult` | Single query for code |
| `get_link(token)` | `EmailResult` | Single query for link |
| `get_raw(token)` | `EmailResult` | Get raw email content |
| `health_check()` | `dict` | Check if Worker is running |

### Worker Endpoints

All require `X-Auth-Key` header or `?key=` query param.

| Endpoint | Response |
|----------|----------|
| `GET /code?email=prefix` | `{"found": true, "code": "123456", ...}` |
| `GET /link?email=prefix` | `{"found": true, "link": "https://...", ...}` |
| `GET /raw?email=prefix` | `{"found": true, "subject": "...", "bodyPreview": "...", ...}` |
| `GET /health` | `{"ok": true, "domain": "...", ...}` |

## Limits

| Resource | Free Limit | Bottleneck? |
|----------|-----------|-------------|
| Email Routing | Unlimited | No |
| Workers Requests | 100,000/day | No |
| KV Writes | 1,000/day | **Yes (~300 reg/day)** |
| Supabase DB | 500MB, unlimited API | No |
| Upstash Redis | 10,000 cmds/day | ~3,000 reg/day |

**KV is the only backend with a tight limit.** Switch to Supabase for effectively unlimited free registrations.

## License

MIT
