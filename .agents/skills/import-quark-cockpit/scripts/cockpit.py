"""Validate cockpit exports and import them into a workbuddy2api-panel pool."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REQUIRED_FIELDS = ("uid", "access_token", "refresh_token")
COCKPIT_NAME = re.compile(r"^cockpit-[0-9a-f-]+\.json$")


def read_accounts(path: Path) -> list[dict]:
    """Read one seller export without importing any other local module."""
    if path.stat().st_size == 0:
        raise ValueError("文件为空（0 字节），请重新下载")
    with path.open(encoding="utf-8-sig") as stream:
        value = json.load(stream)
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or not value:
        raise ValueError("顶层必须是非空 JSON 数组")
    if not all(isinstance(account, dict) for account in value):
        raise ValueError("数组中的每个账号都必须是对象")
    for account in value:
        missing = [key for key in REQUIRED_FIELDS if not isinstance(account.get(key), str) or not account[key].strip()]
        if missing:
            raise ValueError("账号缺少必要字段: " + ", ".join(missing))
    return value


def load_files(paths: list[Path]) -> list[dict]:
    accounts = []
    seen = set()
    for path in paths:
        if not path.is_file():
            raise ValueError(f"文件不存在: {path}")
        for account in read_accounts(path):
            uid = account["uid"].strip()
            if uid in seen:
                raise ValueError(f"uid 重复，未导入: {uid}")
            seen.add(uid)
            accounts.append(account)
    return accounts


def multipart_body(accounts: list[dict]) -> tuple[bytes, str]:
    boundary = "----wb2api-cockpit-" + os.urandom(12).hex()
    payload = json.dumps(accounts, ensure_ascii=False).encode()
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="cockpit-import.json"\r\n'
        "Content-Type: application/json\r\n\r\n"
    ).encode() + payload + f"\r\n--{boundary}--\r\n".encode()
    return body, boundary


def read_api_key(config_path: Path) -> str:
    with config_path.open(encoding="utf-8") as stream:
        key = json.load(stream).get("api_key")
    if not isinstance(key, str) or not key:
        raise ValueError(f"无法从 {config_path} 读取 api_key")
    return key


def request_json(url: str, *, key: str, body: bytes | None = None, boundary: str | None = None) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    method = "GET"
    if body is not None:
        method = "POST"
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        headers["Content-Length"] = str(len(body))
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        try:
            detail = json.loads(error.read())
        except (ValueError, UnicodeDecodeError):
            detail = {"error": "上游返回非 JSON 错误响应"}
        raise RuntimeError(f"网关返回 HTTP {error.code}: {json.dumps(detail, ensure_ascii=False)}") from error
    except URLError as error:
        raise RuntimeError(f"无法连接网关: {error.reason}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="已下载的 cockpit JSON")
    parser.add_argument("--url", default=os.environ.get("WB2API_URL", "http://127.0.0.1:7863"))
    parser.add_argument("--config", type=Path, help="网关 config.json；默认使用 WB2API_CONFIG 或自动查找")
    parser.add_argument("--dry-run", action="store_true", help="只校验，不访问网关、不导入")
    args = parser.parse_args()

    try:
        accounts = load_files(args.files)
        duplicates = [uid for uid, count in Counter(a["uid"] for a in accounts).items() if count > 1]
        if duplicates:
            raise ValueError("uid 重复: " + ", ".join(duplicates))
        if args.dry_run:
            print(json.dumps({"dry_run": True, "valid_accounts": len(accounts), "uids": [a["uid"] for a in accounts]}, ensure_ascii=False))
            return 0

        config = args.config
        if config is None:
            configured = os.environ.get("WB2API_CONFIG")
            if configured:
                config = Path(configured)
            else:
                candidates = [
                    Path.cwd() / "config.json",
                    Path.home() / "project/workbuddy2api-panel/config.json",
                ]
                config = next((candidate for candidate in candidates if candidate.is_file()), None)
        if config is None or not config.is_file():
            raise ValueError("未找到网关 config.json，请使用 --config 指定")
        key = read_api_key(config)
        base_url = args.url.rstrip("/")
        body, boundary = multipart_body(accounts)
        _, result = request_json(f"{base_url}/panel/api/import/cockpit", key=key, body=body, boundary=boundary)
        print(json.dumps({"import": result}, ensure_ascii=False))
        _, status = request_json(f"{base_url}/status", key=key)
        pool_accounts = status.get("accounts", [])
        pool_summary = status.get("summary", status)
        print(json.dumps({
            "pool": {key: pool_summary.get(key) for key in ("total", "healthy", "cooling", "disabled")},
            "accounts": [{"uid": a.get("uid"), "nickname": a.get("nickname"), "credits": a.get("credits"), "cooling": a.get("cooling"), "disabled": a.get("disabled")} for a in pool_accounts],
        }, ensure_ascii=False))
        return 0 if result.get("ok") and result.get("imported") == len(accounts) and not result.get("skipped") else 1
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"错误: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
