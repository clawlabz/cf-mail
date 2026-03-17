"""
cf-mail 基本用法示例
"""

from cf_mail import CloudflareMail


def main():
    # 初始化客户端
    mail = CloudflareMail(
        domain="example.com",
        api_url="https://email-receiver.xxx.workers.dev",
        auth_key="your-secret-key",
    )

    # 健康检查
    print("健康检查:", mail.health_check())

    # ─── 场景 1: 获取验证码 ───

    email, token = mail.create_email()
    print(f"邮箱: {email}")

    # ... 在这里用 email 注册某个网站 ...

    # 等待验证码（最多 120 秒）
    code = mail.wait_for_code(
        token,
        timeout=120,
        on_poll=lambda elapsed, total: print(f"  等待中... {elapsed}s/{total}s"),
    )

    if code:
        print(f"验证码: {code}")
    else:
        print("超时，未收到验证码")

    # ─── 场景 2: 获取验证链接 ───

    email2, token2 = mail.create_email()
    print(f"\n邮箱: {email2}")

    # ... 在这里用 email2 注册某个需要点击链接验证的网站 ...

    link = mail.wait_for_link(token2, timeout=120)

    if link:
        print(f"验证链接: {link}")
    else:
        print("超时，未收到验证链接")

    # ─── 场景 3: 获取原始邮件 ───

    email3, token3 = mail.create_email()
    print(f"\n邮箱: {email3}")

    # ... 发送邮件到 email3 ...

    result = mail.wait_for_email(token3, timeout=60)
    if result.found:
        print(f"发件人: {result.from_addr}")
        print(f"主题: {result.subject}")
        print(f"内容: {result.body_preview[:200]}")

    # ─── 场景 4: 自定义前缀 ───

    email4, token4 = mail.create_email(prefix="test-user-001")
    print(f"\n自定义邮箱: {email4}")  # test-user-001@example.com


if __name__ == "__main__":
    main()
