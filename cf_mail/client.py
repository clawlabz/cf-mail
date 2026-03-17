"""
CloudflareMail — 零成本一次性邮箱客户端

基于 Cloudflare Email Routing + Workers + KV，
提供程序化的邮箱创建和验证码/链接获取能力。

Features:
    - 无限生成随机邮箱地址（无需 API 调用）
    - 自动接收邮件并提取验证码或验证链接
    - 支持自定义验证码正则
    - 支持获取完整邮件原文
    - 线程安全
    - 支持代理
"""

from __future__ import annotations

import random
import string
import time
from dataclasses import dataclass, field
from typing import List, Optional

import requests


# ─── 默认验证码正则 ───

DEFAULT_CODE_PATTERNS = [
    r"Verification code:?\s*(\d{6})",
    r"verification code is:?\s*(\d{4,8})",
    r"code is\s*(\d{4,8})",
    r"code:?\s*(\d{4,8})",
    r"代码为[:：]?\s*(\d{4,8})",
    r"验证码[:：]?\s*(\d{4,8})",
    r">\s*(\d{4,8})\s*<",
    r"(?<![#&])\b(\d{6})\b",
]

DEFAULT_LINK_PATTERNS = [
    r'href=["\']?(https?://[^\s"\'<>]+(?:verify|confirm|activate|validate|token)[^\s"\'<>]*)',
    r'(https?://[^\s"\'<>]+(?:verify|confirm|activate|validate|token)[^\s"\'<>]*)',
]


@dataclass
class EmailResult:
    """邮件查询结果"""

    found: bool
    code: Optional[str] = None
    link: Optional[str] = None
    from_addr: Optional[str] = None
    to_addr: Optional[str] = None
    subject: Optional[str] = None
    body_preview: Optional[str] = None
    timestamp: Optional[int] = None


@dataclass
class CloudflareMail:
    """
    Cloudflare Email 客户端

    Args:
        domain: 邮箱域名，如 "example.com"
        api_url: Worker API 地址，如 "https://email-receiver.xxx.workers.dev"
        auth_key: Worker 鉴权密钥
        proxy: 代理地址（可选），如 "http://127.0.0.1:7890"
        prefix_length: 随机邮箱前缀长度范围 (min, max)
        verify_ssl: 是否验证 SSL 证书
        request_timeout: API 请求超时秒数
    """

    domain: str
    api_url: str
    auth_key: str
    proxy: str = ""
    prefix_length: tuple = (8, 13)
    verify_ssl: bool = False
    request_timeout: int = 10
    _session: Optional[requests.Session] = field(default=None, repr=False)

    def __post_init__(self):
        self.api_url = self.api_url.rstrip("/")
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.verify = self.verify_ssl
        session.headers.update({"X-Auth-Key": self.auth_key})
        if self.proxy:
            p = self.proxy if "://" in self.proxy else f"http://{self.proxy}"
            session.proxies = {"http": p, "https": p}
        return session

    # ─── 邮箱创建 ───

    def create_email(self, prefix: Optional[str] = None) -> tuple[str, str]:
        """
        生成随机邮箱地址（纯本地，无 API 调用）

        Args:
            prefix: 自定义前缀，不传则随机生成

        Returns:
            (email, token) — email 用于注册，token 用于查询验证码
        """
        if prefix is None:
            chars = string.ascii_lowercase + string.digits
            length = random.randint(*self.prefix_length)
            prefix = "".join(random.choice(chars) for _ in range(length))
        email = f"{prefix}@{self.domain}"
        return email, prefix

    # ─── 验证码查询 ───

    def get_code(self, token: str) -> EmailResult:
        """
        查询验证码（单次请求）

        Args:
            token: create_email() 返回的 token（邮箱前缀）

        Returns:
            EmailResult
        """
        try:
            resp = self._session.get(
                f"{self.api_url}/code",
                params={"email": token.lower()},
                timeout=self.request_timeout,
            )
            data = resp.json()
            if data.get("found"):
                return EmailResult(
                    found=True,
                    code=data.get("code"),
                    from_addr=data.get("from"),
                    to_addr=data.get("to"),
                    timestamp=data.get("timestamp"),
                )
        except Exception:
            pass
        return EmailResult(found=False)

    def wait_for_code(
        self,
        token: str,
        timeout: int = 120,
        poll_interval: float = 3.0,
        on_poll: Optional[callable] = None,
    ) -> Optional[str]:
        """
        轮询等待验证码

        Args:
            token: create_email() 返回的 token
            timeout: 最大等待秒数
            poll_interval: 轮询间隔秒数
            on_poll: 每次轮询回调 fn(elapsed_sec, timeout_sec)

        Returns:
            验证码字符串，超时返回 None
        """
        start = time.time()
        while time.time() - start < timeout:
            result = self.get_code(token)
            if result.found and result.code:
                return result.code
            if on_poll:
                on_poll(int(time.time() - start), timeout)
            time.sleep(poll_interval)
        return None

    # ─── 验证链接查询 ───

    def get_link(self, token: str) -> EmailResult:
        """
        查询验证链接（单次请求）

        Args:
            token: create_email() 返回的 token

        Returns:
            EmailResult
        """
        try:
            resp = self._session.get(
                f"{self.api_url}/link",
                params={"email": token.lower()},
                timeout=self.request_timeout,
            )
            data = resp.json()
            if data.get("found"):
                return EmailResult(
                    found=True,
                    link=data.get("link"),
                    from_addr=data.get("from"),
                    to_addr=data.get("to"),
                    timestamp=data.get("timestamp"),
                )
        except Exception:
            pass
        return EmailResult(found=False)

    def wait_for_link(
        self,
        token: str,
        timeout: int = 120,
        poll_interval: float = 3.0,
        on_poll: Optional[callable] = None,
    ) -> Optional[str]:
        """
        轮询等待验证链接

        Args:
            token: create_email() 返回的 token
            timeout: 最大等待秒数
            poll_interval: 轮询间隔秒数
            on_poll: 每次轮询回调

        Returns:
            链接字符串，超时返回 None
        """
        start = time.time()
        while time.time() - start < timeout:
            result = self.get_link(token)
            if result.found and result.link:
                return result.link
            if on_poll:
                on_poll(int(time.time() - start), timeout)
            time.sleep(poll_interval)
        return None

    # ─── 原始邮件查询 ───

    def get_raw(self, token: str) -> EmailResult:
        """
        获取原始邮件内容（调试用）

        Args:
            token: create_email() 返回的 token

        Returns:
            EmailResult（body_preview 包含邮件原文片段）
        """
        try:
            resp = self._session.get(
                f"{self.api_url}/raw",
                params={"email": token.lower()},
                timeout=self.request_timeout,
            )
            data = resp.json()
            if data.get("found"):
                return EmailResult(
                    found=True,
                    from_addr=data.get("from"),
                    to_addr=data.get("to"),
                    subject=data.get("subject"),
                    body_preview=data.get("bodyPreview"),
                    timestamp=data.get("timestamp"),
                )
        except Exception:
            pass
        return EmailResult(found=False)

    def wait_for_email(
        self,
        token: str,
        timeout: int = 120,
        poll_interval: float = 3.0,
    ) -> EmailResult:
        """
        等待任意邮件到达（不关心验证码/链接，只要有邮件就返回）

        Returns:
            EmailResult
        """
        start = time.time()
        while time.time() - start < timeout:
            result = self.get_raw(token)
            if result.found:
                return result
            time.sleep(poll_interval)
        return EmailResult(found=False)

    # ─── 健康检查 ───

    def health_check(self) -> dict:
        """检查 Worker 是否正常运行"""
        try:
            resp = self._session.get(
                f"{self.api_url}/health",
                timeout=self.request_timeout,
            )
            return resp.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}
