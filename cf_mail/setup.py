"""
Cloudflare 自动配置工具

通过 Cloudflare API 自动完成：
1. 创建 KV Namespace
2. 添加 DNS 记录（MX + TXT）
3. 部署 Email Worker
4. 配置 Email Routing

需要 Cloudflare API Token，权限要求：
- Zone: DNS Edit, Email Routing Edit
- Account: Workers Scripts Edit, Workers KV Storage Edit
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


CF_API = "https://api.cloudflare.com/client/v4"


@dataclass
class CloudflareSetup:
    """
    Cloudflare 自动配置

    Args:
        api_token: Cloudflare API Token
        zone_id: Zone ID（在 Cloudflare Dashboard 域名概述页右下角）
        account_id: Account ID（同上）
        domain: 邮箱域名，如 "example.com"
    """

    api_token: str
    zone_id: str
    account_id: str
    domain: str

    def __post_init__(self):
        self._headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    # ─── API 请求 ───

    def _api(self, method: str, url: str, **kwargs) -> dict:
        resp = requests.request(
            method, url, headers=self._headers, timeout=30, **kwargs
        )
        data = resp.json()
        if not data.get("success", False):
            errors = data.get("errors", [])
            raise Exception(f"Cloudflare API error: {errors}")
        return data

    # ─── 1. KV Namespace ───

    def create_kv_namespace(self, name: str = "EMAIL_KV") -> str:
        """创建 KV Namespace，返回 Namespace ID"""
        print(f"[1/5] 创建 KV Namespace: {name}")
        try:
            data = self._api(
                "POST",
                f"{CF_API}/accounts/{self.account_id}/storage/kv/namespaces",
                json={"title": name},
            )
            ns_id = data["result"]["id"]
            print(f"  ✓ Namespace ID: {ns_id}")
            return ns_id
        except Exception as e:
            if "already exists" in str(e).lower() or "10014" in str(e):
                print(f"  → 已存在，查找现有 Namespace...")
                return self._find_kv_namespace(name)
            raise

    def _find_kv_namespace(self, name: str) -> str:
        data = self._api(
            "GET",
            f"{CF_API}/accounts/{self.account_id}/storage/kv/namespaces",
        )
        for ns in data.get("result", []):
            if ns["title"] == name:
                print(f"  ✓ 找到: {ns['id']}")
                return ns["id"]
        raise Exception(f"KV Namespace '{name}' not found")

    # ─── 2. DNS 记录 ───

    def setup_dns(self) -> None:
        """添加 Email Routing 所需的 MX 和 TXT 记录"""
        print(f"[2/5] 配置 DNS 记录: {self.domain}")

        mx_records = [
            ("route1.mx.cloudflare.net", 10),
            ("route2.mx.cloudflare.net", 20),
            ("route3.mx.cloudflare.net", 30),
        ]

        for mx_host, priority in mx_records:
            self._ensure_dns_record("MX", self.domain, mx_host, priority=priority)

        spf = "v=spf1 include:_spf.mx.cloudflare.net ~all"
        self._ensure_dns_record("TXT", self.domain, spf)

        print("  ✓ DNS 记录已配置")

    def _ensure_dns_record(
        self, rtype: str, name: str, content: str, priority: int = 0
    ) -> None:
        # 检查是否已存在
        params = {"type": rtype, "name": name}
        data = self._api(
            "GET",
            f"{CF_API}/zones/{self.zone_id}/dns_records",
            params=params,
        )
        for record in data.get("result", []):
            if record["content"] == content:
                print(f"  → {rtype} {content} 已存在，跳过")
                return

        # 创建
        payload = {"type": rtype, "name": name, "content": content, "ttl": 1}
        if rtype == "MX":
            payload["priority"] = priority
        self._api(
            "POST",
            f"{CF_API}/zones/{self.zone_id}/dns_records",
            json=payload,
        )
        print(f"  + {rtype} {content}")

    # ─── 3. 生成 Auth Key ───

    @staticmethod
    def generate_auth_key() -> str:
        """生成随机鉴权密钥"""
        key = secrets.token_hex(32)
        print(f"[3/5] 生成 Auth Key: {key[:16]}...")
        return key

    # ─── 4. 部署 Worker ───

    def deploy_worker(
        self, kv_namespace_id: str, auth_key: str, worker_dir: Optional[str] = None
    ) -> str:
        """
        使用 wrangler 部署 Worker

        Args:
            kv_namespace_id: KV Namespace ID
            auth_key: 鉴权密钥
            worker_dir: Worker 源码目录，默认使用内置的

        Returns:
            Worker URL
        """
        print("[4/5] 部署 Email Worker")

        if worker_dir is None:
            worker_dir = str(Path(__file__).parent.parent / "worker")

        if not os.path.isdir(worker_dir):
            raise FileNotFoundError(f"Worker 目录不存在: {worker_dir}")

        # 写入 wrangler.toml
        wrangler_path = os.path.join(worker_dir, "wrangler.toml")
        wrangler_content = f"""name = "email-receiver"
main = "src/worker.js"
compatibility_date = "2024-09-01"

[[kv_namespaces]]
binding = "EMAIL_KV"
id = "{kv_namespace_id}"

[vars]
AUTH_KEY = "{auth_key}"
EMAIL_DOMAIN = "{self.domain}"
"""
        with open(wrangler_path, "w") as f:
            f.write(wrangler_content)

        # npm install
        subprocess.run(
            ["npm", "install"],
            cwd=worker_dir,
            capture_output=True,
            check=True,
        )

        # wrangler deploy
        result = subprocess.run(
            ["npx", "wrangler", "deploy"],
            cwd=worker_dir,
            capture_output=True,
            text=True,
            env={**os.environ, "CLOUDFLARE_API_TOKEN": self.api_token},
        )

        if result.returncode != 0:
            print(f"  ✗ 部署失败: {result.stderr}")
            raise Exception(f"Worker deploy failed: {result.stderr}")

        # 从输出提取 URL
        worker_url = ""
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("https://") and ".workers.dev" in line:
                worker_url = line
                break

        if not worker_url:
            worker_url = f"https://email-receiver.{self.account_id[:8]}.workers.dev"

        print(f"  ✓ Worker 已部署: {worker_url}")
        return worker_url

    # ─── 5. 启用 Email Routing ───

    def setup_email_routing(self) -> None:
        """启用 Email Routing 并配置 Catch-all → Worker"""
        print(f"[5/5] 配置 Email Routing: {self.domain}")

        # 启用 Email Routing
        try:
            self._api(
                "PUT",
                f"{CF_API}/zones/{self.zone_id}/email/routing/enable",
                json={"enabled": True},
            )
            print("  ✓ Email Routing 已启用")
        except Exception:
            print("  → Email Routing 可能已启用，继续...")

        # 配置 Catch-all → Worker
        try:
            catch_all = {
                "enabled": True,
                "actions": [{"type": "worker", "value": ["email-receiver"]}],
                "matchers": [{"type": "all"}],
            }
            self._api(
                "PUT",
                f"{CF_API}/zones/{self.zone_id}/email/routing/rules/catch_all",
                json=catch_all,
            )
            print("  ✓ Catch-all → email-receiver Worker")
        except Exception as e:
            print(f"  ⚠ Catch-all 配置失败（可手动配置）: {e}")

    # ─── 一键安装 ───

    def run_full_setup(self) -> dict:
        """
        一键完成全部配置

        Returns:
            {
                "domain": str,
                "api_url": str,
                "auth_key": str,
                "kv_namespace_id": str,
            }
        """
        print(f"\n{'='*50}")
        print(f"  cf-mail 自动配置: {self.domain}")
        print(f"{'='*50}\n")

        kv_id = self.create_kv_namespace()
        self.setup_dns()
        auth_key = self.generate_auth_key()
        worker_url = self.deploy_worker(kv_id, auth_key)
        self.setup_email_routing()

        config = {
            "domain": self.domain,
            "api_url": worker_url,
            "auth_key": auth_key,
            "kv_namespace_id": kv_id,
        }

        print(f"\n{'='*50}")
        print("  配置完成！")
        print(f"{'='*50}")
        print(f"\n将以下内容添加到你的项目配置中:\n")
        print(json.dumps(config, indent=2))
        print(f"\nPython 用法:")
        print(f'  from cf_mail import CloudflareMail')
        print(f'  mail = CloudflareMail(')
        print(f'      domain="{self.domain}",')
        print(f'      api_url="{worker_url}",')
        print(f'      auth_key="{auth_key}",')
        print(f'  )')

        # 保存配置文件
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "cf_mail_config.json"
        )
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"\n配置已保存到: {config_path}")

        return config


def add_forwarding_rule(
    api_token: str,
    zone_id: str,
    source_email: str,
    destination_email: str,
) -> None:
    """
    添加邮件转发规则（保护现有邮箱）

    Args:
        api_token: Cloudflare API Token
        zone_id: Zone ID
        source_email: 源地址，如 "admin@example.com"
        destination_email: 目标地址，如 "xxx@qq.com"
    """
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "actions": [{"type": "forward", "value": [destination_email]}],
        "enabled": True,
        "matchers": [{"field": "to", "type": "literal", "value": source_email}],
        "name": f"Forward {source_email}",
    }
    resp = requests.post(
        f"{CF_API}/zones/{zone_id}/email/routing/rules",
        headers=headers,
        json=payload,
        timeout=30,
    )
    data = resp.json()
    if data.get("success"):
        print(f"✓ 转发规则已添加: {source_email} → {destination_email}")
    else:
        print(f"✗ 添加失败: {data.get('errors', [])}")


# ─── CLI 入口 ───

def main():
    """命令行一键安装"""
    print("cf-mail 自动配置向导\n")

    api_token = input("Cloudflare API Token: ").strip()
    account_id = input("Account ID: ").strip()
    zone_id = input("Zone ID: ").strip()
    domain = input("邮箱域名 (如 example.com): ").strip()

    if not all([api_token, account_id, zone_id, domain]):
        print("错误: 所有字段都不能为空")
        sys.exit(1)

    setup = CloudflareSetup(
        api_token=api_token,
        zone_id=zone_id,
        account_id=account_id,
        domain=domain,
    )
    setup.run_full_setup()

    # 询问是否添加转发规则
    print("\n是否添加邮件转发规则（保护现有邮箱）？")
    while True:
        source = input("源地址 (如 admin@example.com，直接回车跳过): ").strip()
        if not source:
            break
        dest = input("转发到: ").strip()
        if dest:
            add_forwarding_rule(api_token, zone_id, source, dest)


if __name__ == "__main__":
    main()
