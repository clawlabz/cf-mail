# cf-mail

Zero-cost disposable email service powered by **Cloudflare Email Routing + Workers + KV**.

Generate unlimited email addresses on your domain, automatically receive and extract verification codes/links — perfect for batch registration, automated testing, and CI/CD pipelines.

## Features

- **Zero cost** — Uses Cloudflare free tier (100K Workers requests/day, 1K KV writes/day)
- **No third-party API** — Only needs a domain + Cloudflare account
- **Unlimited addresses** — `random@yourdomain.com`, no mailbox creation needed
- **Auto-extract** — Verification codes (4-8 digits) and verification links
- **Raw email access** — Full email content for custom parsing
- **Thread-safe** — Built for concurrent batch operations
- **One-click setup** — Auto-configure Cloudflare via API

## Quick Start

### 1. Install

```bash
pip install cf-mail
```

### 2. Setup (Auto)

```bash
python -m cf_mail.setup
```

You'll need:
- A **domain** with DNS on Cloudflare
- **Cloudflare API Token** (create at https://dash.cloudflare.com/profile/api-tokens)
  - Permissions: `Zone:DNS:Edit`, `Zone:Email Routing:Edit`, `Account:Workers Scripts:Edit`, `Account:Workers KV Storage:Edit`
- **Account ID** and **Zone ID** (found on your domain's overview page in Cloudflare Dashboard)

The setup wizard will automatically:
1. Create KV namespace
2. Configure DNS records (MX + SPF)
3. Generate auth key
4. Deploy the Worker
5. Configure Email Routing catch-all

### 3. Use

```python
from cf_mail import CloudflareMail

mail = CloudflareMail(
    domain="yourdomain.com",
    api_url="https://email-receiver.xxx.workers.dev",
    auth_key="your-secret-key",
)

# Generate a random email
email, token = mail.create_email()
print(f"Email: {email}")  # e.g. a8kx2mf@yourdomain.com

# ... use this email to register on a website ...

# Wait for verification code
code = mail.wait_for_code(token, timeout=120)
print(f"Code: {code}")  # e.g. "482913"

# Or wait for verification link
link = mail.wait_for_link(token, timeout=120)
print(f"Link: {link}")  # e.g. "https://example.com/verify?token=..."
```

## Manual Setup

If you prefer to configure manually instead of using the auto-setup:

### Step 1: Create KV Namespace

Cloudflare Dashboard → **Storage & Databases** → **KV** → **Create namespace**

Name: `EMAIL_KV`, note the Namespace ID.

### Step 2: DNS Records

Dashboard → Your domain → **DNS** → **Records**, add:

| Type | Name | Content | Priority |
|------|------|---------|----------|
| MX | `@` | `route1.mx.cloudflare.net` | 10 |
| MX | `@` | `route2.mx.cloudflare.net` | 20 |
| MX | `@` | `route3.mx.cloudflare.net` | 30 |
| TXT | `@` | `v=spf1 include:_spf.mx.cloudflare.net ~all` | - |

> ⚠️ **Warning**: This replaces existing MX records. If you have existing email (e.g., Google Workspace, QQ Mail), see [Preserving Existing Email](#preserving-existing-email).

### Step 3: Generate Auth Key

```bash
openssl rand -hex 32
```

### Step 4: Deploy Worker

```bash
cd worker
npm install

# Edit wrangler.toml with your KV ID, auth key, and domain
npx wrangler login
npx wrangler deploy
```

### Step 5: Configure Email Routing

Dashboard → Your domain → **Email** → **Email Routing**:

1. Enable Email Routing
2. **Routing Rules** → **Catch-all** → Edit
3. Action: **Send to a Worker** → Select `email-receiver`
4. Save

### Step 6: Test

```bash
# Send a test email to test@yourdomain.com with "123456" in the body

# Query the Worker
curl "https://email-receiver.xxx.workers.dev/code?email=test" \
  -H "X-Auth-Key: your-auth-key"

# Expected: {"found":true,"code":"123456",...}
```

## Preserving Existing Email

If your domain already has email service (Gmail, QQ Mail, etc.), you need to add forwarding rules **before** or **after** enabling Email Routing:

Dashboard → **Email** → **Email Routing** → **Routing Rules** → **Create Address**

| Custom Address | Action | Destination |
|----------------|--------|-------------|
| `admin@yourdomain.com` | Forward to | `your-real@email.com` |
| `info@yourdomain.com` | Forward to | `your-real@email.com` |

Custom address rules have higher priority than catch-all, so your existing addresses will be forwarded normally while all other addresses go to the Worker.

You can also add forwarding rules via the setup tool:

```python
from cf_mail.setup import add_forwarding_rule

add_forwarding_rule(
    api_token="your-cf-token",
    zone_id="your-zone-id",
    source_email="admin@yourdomain.com",
    destination_email="your-real@email.com",
)
```

## API Reference

### `CloudflareMail(domain, api_url, auth_key, **kwargs)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `domain` | str | required | Email domain |
| `api_url` | str | required | Worker URL |
| `auth_key` | str | required | Auth key |
| `proxy` | str | `""` | HTTP proxy |
| `prefix_length` | tuple | `(8, 13)` | Random prefix length range |
| `verify_ssl` | bool | `False` | Verify SSL certificates |
| `request_timeout` | int | `10` | API request timeout (seconds) |

### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `create_email(prefix=None)` | `(email, token)` | Generate random email |
| `get_code(token)` | `EmailResult` | Query verification code (single request) |
| `wait_for_code(token, timeout=120)` | `str \| None` | Poll for verification code |
| `get_link(token)` | `EmailResult` | Query verification link (single request) |
| `wait_for_link(token, timeout=120)` | `str \| None` | Poll for verification link |
| `get_raw(token)` | `EmailResult` | Get raw email content |
| `wait_for_email(token, timeout=120)` | `EmailResult` | Wait for any email |
| `health_check()` | `dict` | Check Worker health |

### Worker API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /code?email=<prefix>` | Query verification code |
| `GET /link?email=<prefix>` | Query verification link |
| `GET /raw?email=<prefix>` | Get raw email content |
| `GET /health` | Health check |

All endpoints require `X-Auth-Key` header or `?key=` parameter.

## Free Tier Limits

| Resource | Free Limit | Approx. Capacity |
|----------|------------|-------------------|
| Workers Requests | 100,000/day | — |
| KV Writes | 1,000/day | ~300 registrations/day |
| KV Reads | 100,000/day | — |

For higher volume, upgrade to Workers Paid ($5/month) for unlimited KV operations.

## License

MIT
