"""
cf-mail: Zero-cost disposable email service
powered by Cloudflare Email Routing + Workers + KV

Usage:
    from cf_mail import CloudflareMail

    mail = CloudflareMail(
        domain="example.com",
        api_url="https://your-worker.workers.dev",
        auth_key="your-secret-key",
    )

    email, token = mail.create_email()
    # ... use email to register on a website ...
    code = mail.wait_for_code(token, timeout=120)
"""

from cf_mail.client import CloudflareMail

__version__ = "0.1.0"
__all__ = ["CloudflareMail"]
