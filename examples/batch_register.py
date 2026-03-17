"""
cf-mail 批量注册示例

演示如何用 cf-mail 配合多线程进行批量网站注册
"""

import concurrent.futures
import threading

from cf_mail import CloudflareMail


def register_one(mail: CloudflareMail, idx: int, total: int):
    """单个注册任务"""
    email, token = mail.create_email()
    print(f"[{idx}/{total}] 邮箱: {email}")

    # === 在这里执行注册逻辑 ===
    # requests.post("https://example.com/register", json={
    #     "email": email,
    #     "password": "xxx",
    # })

    # 等待验证码
    code = mail.wait_for_code(token, timeout=120)
    if not code:
        print(f"[{idx}/{total}] 超时")
        return False

    print(f"[{idx}/{total}] 验证码: {code}")

    # === 在这里提交验证码 ===
    # requests.post("https://example.com/verify", json={
    #     "email": email,
    #     "code": code,
    # })

    print(f"[{idx}/{total}] 注册成功!")
    return True


def main():
    mail = CloudflareMail(
        domain="example.com",
        api_url="https://email-receiver.xxx.workers.dev",
        auth_key="your-secret-key",
    )

    total = 10
    workers = 3
    success = 0
    fail = 0
    lock = threading.Lock()

    def task(idx):
        nonlocal success, fail
        try:
            ok = register_one(mail, idx, total)
            with lock:
                if ok:
                    success += 1
                else:
                    fail += 1
        except Exception as e:
            print(f"[{idx}] 异常: {e}")
            with lock:
                fail += 1

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        executor.map(task, range(1, total + 1))

    print(f"\n完成: 成功={success}, 失败={fail}, 总计={total}")


if __name__ == "__main__":
    main()
