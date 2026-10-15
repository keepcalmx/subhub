"""订阅内容解析：支持 Clash YAML 与 Base64 分享链接（ss/vmess/trojan）"""
import base64
import json
from urllib.parse import parse_qs, unquote, urlparse

import yaml


def b64decode_pad(s: str) -> bytes:
    s = s.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * (-len(s) % 4))


def parse_subscription(text: str):
    """解析订阅文本，返回 Clash proxies 列表"""
    text = text.strip()

    # 1) Clash YAML
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict) and isinstance(data.get("proxies"), list) and data["proxies"]:
            return [p for p in data["proxies"] if isinstance(p, dict) and p.get("name")]
    except yaml.YAMLError:
        pass

    # 2) Base64 编码的分享链接
    try:
        decoded = b64decode_pad(text).decode("utf-8", "ignore")
    except Exception:
        decoded = ""

    for t in (text, decoded):
        if "://" in t:
            proxies = parse_share_links(t)
            if proxies:
                return proxies

    raise ValueError("无法识别的订阅格式（支持 Clash YAML / Base64 分享链接）")


def parse_share_links(text: str):
    proxies = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            if line.startswith("ss://"):
                p = parse_ss(line)
            elif line.startswith("vmess://"):
                p = parse_vmess(line)
            elif line.startswith("trojan://"):
                p = parse_trojan(line)
            else:
                continue
            if p and p.get("server") and p.get("port"):
                proxies.append(p)
        except Exception:
            continue
    return proxies


def parse_ss(link: str):
    body = link[5:]
    name = None
    if "#" in body:
        body, frag = body.split("#", 1)
        name = unquote(frag)
    if "?" in body:
        body = body.split("?", 1)[0]

    if "@" in body:  # SIP002: ss://base64(method:pass)@host:port
        userinfo, hostport = body.rsplit("@", 1)
        try:
            method_pass = b64decode_pad(userinfo).decode()
        except Exception:
            method_pass = unquote(userinfo)
        method, password = method_pass.split(":", 1)
        host, port = hostport.rsplit(":", 1)
    else:  # 全整体 base64: ss://base64(method:pass@host:port)
        decoded = b64decode_pad(body).decode()
        method_pass, hostport = decoded.rsplit("@", 1)
        method, password = method_pass.split(":", 1)
        host, port = hostport.rsplit(":", 1)

    return {
        "name": name or f"{host}:{port}",
        "type": "ss",
        "server": host,
        "port": int(port),
        "cipher": method,
        "password": password,
        "udp": True,
    }


def parse_vmess(link: str):
    payload = json.loads(b64decode_pad(link[8:]).decode("utf-8", "ignore"))
    proxy = {
        "name": payload.get("ps") or f"{payload.get('add')}:{payload.get('port')}",
        "type": "vmess",
        "server": str(payload.get("add", "")),
        "port": int(payload.get("port") or 0),
        "uuid": payload.get("id"),
        "alterId": int(payload.get("aid") or 0),
        "cipher": payload.get("scy") or "auto",
        "tls": payload.get("tls") in ("tls", True, "true"),
        "udp": True,
    }
    if payload.get("net") == "ws":
        proxy["network"] = "ws"
        ws_opts = {}
        if payload.get("path"):
            ws_opts["path"] = payload["path"]
        if payload.get("host"):
            ws_opts["headers"] = {"Host": payload["host"]}
        if ws_opts:
            proxy["ws-opts"] = ws_opts
    return proxy


def parse_trojan(link: str):
    u = urlparse(link)
    q = parse_qs(u.query)
    return {
        "name": unquote(u.fragment) or f"{u.hostname}:{u.port}",
        "type": "trojan",
        "server": u.hostname,
        "port": int(u.port or 443),
        "password": unquote(u.username or ""),
        "sni": q.get("sni", [u.hostname])[0],
        "udp": True,
    }
