#!/usr/bin/env python3
"""
Sync kiro-cli credentials to AWS Secrets Manager.

Usage:
    # 默认：从本地 kiro-cli SQLite 读取 credentials，写入 Secrets Manager
    python3 scripts/sync-kiro-credentials.py

    # 指定 DB 路径
    python3 scripts/sync-kiro-credentials.py --db-path /path/to/data.sqlite3

    # 指定 secret name 和 region
    python3 scripts/sync-kiro-credentials.py --secret-name kiro-gateway/config --region us-east-1

    # Dry run（只打印，不写入）
    python3 scripts/sync-kiro-credentials.py --dry-run

Prerequisites:
    1. kiro-cli 已登录: kiro-cli login
    2. AWS credentials 已配置，有 secretsmanager:PutSecretValue 权限
    3. Secrets Manager secret 已通过 terraform apply 创建
"""

import argparse
import json
import os
import platform
import secrets
import sqlite3
import string
import sys

try:
    import boto3
except ImportError:
    print("ERROR: boto3 not installed. Run: pip install boto3")
    sys.exit(1)


# kiro-cli SQLite DB 默认路径（按平台）
def get_default_db_path() -> str:
    system = platform.system()
    home = os.path.expanduser("~")

    candidates = []
    if system == "Darwin":
        candidates = [
            os.path.join(home, "Library", "Application Support", "kiro-cli", "data.sqlite3"),
            os.path.join(home, ".local", "share", "kiro-cli", "data.sqlite3"),
        ]
    elif system == "Linux":
        candidates = [
            os.path.join(home, ".local", "share", "kiro-cli", "data.sqlite3"),
        ]
    else:
        candidates = [
            os.path.join(home, ".local", "share", "kiro-cli", "data.sqlite3"),
        ]

    for path in candidates:
        if os.path.exists(path):
            return path

    return candidates[0]  # 返回第一个候选路径（让后续报错更明确）


# 从 SQLite 提取 credentials
def extract_credentials(db_path: str) -> dict:
    if not os.path.exists(db_path):
        print(f"ERROR: SQLite DB not found: {db_path}")
        print("Please run 'kiro-cli login' first.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)

    # 提取 token（优先 kirocli，fallback codewhisperer）
    token_keys = ["kirocli:odic:token", "kirocli:social:token", "codewhisperer:odic:token"]
    token_data = None
    for key in token_keys:
        row = conn.execute("SELECT value FROM auth_kv WHERE key = ?", (key,)).fetchone()
        if row:
            token_data = json.loads(row[0])
            print(f"  Found token: {key}")
            break

    if not token_data or not token_data.get("refresh_token"):
        print("ERROR: No valid refresh token found in kiro-cli DB.")
        print("Please run 'kiro-cli login' first.")
        sys.exit(1)

    # 提取 device registration（client_id + client_secret）
    device_keys = ["kirocli:odic:device-registration", "codewhisperer:odic:device-registration"]
    device_data = None
    for key in device_keys:
        row = conn.execute("SELECT value FROM auth_kv WHERE key = ?", (key,)).fetchone()
        if row:
            device_data = json.loads(row[0])
            print(f"  Found device registration: {key}")
            break

    conn.close()

    credentials = {
        "KIRO_REFRESH_TOKEN": token_data["refresh_token"],
    }

    if device_data:
        credentials["KIRO_CLIENT_ID"] = device_data.get("client_id", "")
        credentials["KIRO_CLIENT_SECRET"] = device_data.get("client_secret", "")

    return credentials


# 生成安全的 PROXY_API_KEY
def generate_proxy_api_key(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return "sk-kiro-" + "".join(secrets.choice(alphabet) for _ in range(length))


# 写入 Secrets Manager
def update_secret(secret_name: str, region: str, secret_data: dict, dry_run: bool = False):
    if dry_run:
        safe_data = {}
        for k, v in secret_data.items():
            if v and len(v) > 20:
                safe_data[k] = v[:15] + "..." + v[-5:]
            else:
                safe_data[k] = v
        print(f"\n[DRY RUN] Would write to secret: {secret_name}")
        print(json.dumps(safe_data, indent=2))
        return

    client = boto3.client("secretsmanager", region_name=region)

    # 检查是否已有值，合并而非覆盖（保留已有的 PROXY_API_KEY）
    try:
        existing = client.get_secret_value(SecretId=secret_name)
        existing_data = json.loads(existing["SecretString"])
        # 保留已有的 PROXY_API_KEY（如果用户手动设置过）
        if existing_data.get("KIRO_PROXY_API_KEY") and existing_data["KIRO_PROXY_API_KEY"] != "CHANGE_ME":
            secret_data["KIRO_PROXY_API_KEY"] = existing_data["KIRO_PROXY_API_KEY"]
            print("  Preserved existing KIRO_PROXY_API_KEY")
    except client.exceptions.ResourceNotFoundException:
        # Secret 不存在，先创建
        print(f"  Secret {secret_name} not found, creating...")
        client.create_secret(
            Name=secret_name,
            Description="Kiro Gateway secrets (refresh token, proxy API key)",
            SecretString=json.dumps(secret_data),
        )
        print(f"  Created secret: {secret_name}")
        return

    client.put_secret_value(
        SecretId=secret_name,
        SecretString=json.dumps(secret_data),
    )
    print(f"  Updated secret: {secret_name}")


def main():
    parser = argparse.ArgumentParser(description="Sync kiro-cli credentials to AWS Secrets Manager")
    parser.add_argument("--db-path", default=None, help="Path to kiro-cli SQLite DB")
    parser.add_argument("--secret-name", default="kiro-gateway/config", help="Secrets Manager secret name")
    parser.add_argument("--region", default="us-east-1", help="AWS region")
    parser.add_argument("--dry-run", action="store_true", help="Print credentials without writing")
    args = parser.parse_args()

    db_path = args.db_path or get_default_db_path()

    print(f"=== Sync Kiro Credentials to Secrets Manager ===\n")
    print(f"  DB path:     {db_path}")
    print(f"  Secret name: {args.secret_name}")
    print(f"  Region:      {args.region}")
    print()

    # Step 1: 从 kiro-cli 提取 credentials
    print("[1/3] Extracting credentials from kiro-cli...")
    credentials = extract_credentials(db_path)
    print(f"  refresh_token: {credentials['KIRO_REFRESH_TOKEN'][:30]}...")
    if credentials.get("KIRO_CLIENT_ID"):
        print(f"  client_id:     {credentials['KIRO_CLIENT_ID'][:20]}...")
    print()

    # Step 2: 生成 PROXY_API_KEY
    print("[2/3] Generating PROXY_API_KEY...")
    credentials["KIRO_PROXY_API_KEY"] = generate_proxy_api_key()
    print(f"  proxy_api_key: {credentials['KIRO_PROXY_API_KEY'][:20]}...")
    print()

    # Step 3: 写入 Secrets Manager
    print(f"[3/3] Writing to Secrets Manager ({args.secret_name})...")
    update_secret(args.secret_name, args.region, credentials, dry_run=args.dry_run)
    print()

    print("=== Done ===")
    if not args.dry_run:
        print(f"\nNext steps:")
        print(f"  1. Deploy kiro-gateway:  kubectl apply -f k8s/11-kiro-gateway-external-secret.yaml")
        print(f"  2. Wait for ESO sync:    kubectl get externalsecret -n litellm")
        print(f"  3. Deploy kiro-gateway:  kubectl apply -f k8s/10-kiro-gateway-deployment.yaml")
        print(f"  4. Update LiteLLM:       kubectl apply -f k8s/02-configmap.yaml")
        print(f"  5. Restart LiteLLM:      kubectl rollout restart deployment/litellm -n litellm")
        print(f"\nTo re-sync after kiro-cli re-login:")
        print(f"  python3 scripts/sync-kiro-credentials.py")


if __name__ == "__main__":
    main()
