"""多格式输出：Clash proxies → v2ray 分享链接 / sing-box 配置"""
import base64
import json
from urllib.parse import quote


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _b64url_nopad(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


# ---------- Clash → 分享链接 ----------

def clash_to_share_links(proxies):
    """返回 (links, skipped)：不支持的协议类型计入 skipped"""
    links, skipped = [], 0
    for p in proxies:
        t = p.get("type")
        try:
            if t == "ss":
                userinfo = _b64url_nopad(f"{p['cipher']}:{p['password']}")
                links.append(f"ss://{userinfo}@{p['server']}:{p['port']}#{quote(p['name'])}")
            elif t == "vmess":
                payload = {
                    "v": "2", "ps": p["name"], "add": p["server"], "port": str(p["port"]),
                    "id": p.get("uuid", ""), "aid": str(p.get("alterId", 0)),
                    "scy": p.get("cipher", "auto"), "net": p.get("network", "tcp"),
                    "type": "none", "tls": "tls" if p.get("tls") else "",
                }
                ws = p.get("ws-opts") or {}
                payload["path"] = ws.get("path", "/")
                payload["host"] = (ws.get("headers") or {}).get("Host", "")
                links.append("vmess://" + _b64(json.dumps(payload, ensure_ascii=False)))
            elif t == "trojan":
                q = f"?sni={quote(p.get('sni') or p['server'])}"
                if p.get("skip-cert-verify"):
                    q += "&allowInsecure=1"
                links.append(f"trojan://{quote(p.get('password', ''))}@{p['server']}:{p['port']}{q}#{quote(p['name'])}")
            elif t == "hysteria2":
                q = f"?sni={quote(p.get('sni') or p['server'])}"
                if p.get("skip-cert-verify"):
                    q += "&insecure=1"
                obfs = p.get("obfs")
                if obfs:
                    q += f"&obfs={obfs}&obfs-password={quote(p.get('obfs-password', ''))}"
                links.append(f"hysteria2://{quote(str(p.get('password', '')))}@{p['server']}:{p['port']}{q}#{quote(p['name'])}")
            else:
                skipped += 1
        except Exception:
            skipped += 1
    return links, skipped


def build_v2ray_base64(proxies):
    links, skipped = clash_to_share_links(proxies)
    return base64.b64encode("\n".join(links).encode()).decode(), skipped


# ---------- Clash → sing-box ----------

def _sb_tls(p, default_sni=None):
    tls = p.get("tls")
    sni = p.get("sni") or p.get("servername") or default_sni or p.get("server")
    if not tls and p.get("type") not in ("trojan", "hysteria2", "anytls"):
        return None
    out = {"enabled": True, "server_name": sni}
    if p.get("skip-cert-verify"):
        out["insecure"] = True
    if p.get("alpn"):
        out["alpn"] = p["alpn"] if isinstance(p["alpn"], list) else [p["alpn"]]
    return out


def _sb_ws(p):
    ws = p.get("ws-opts") or {}
    out = {"type": "ws"}
    if ws.get("path"):
        out["path"] = ws["path"]
    headers = ws.get("headers") or {}
    if headers.get("Host"):
        out["headers"] = {"Host": headers["Host"]}
    if ws.get("max-early-data"):
        out["max_early_data"] = ws["max-early-data"]
        out["early_data_header_name"] = ws.get("early-data-header-name", "Sec-WebSocket-Protocol")
    return out


def _proxy_to_outbound(p):
    t = p.get("type")
    name, server, port = p["name"], p["server"], int(p["port"])
    if t == "ss":
        out = {"type": "ss", "tag": name, "server": server, "server_port": port,
               "method": p.get("cipher"), "password": p.get("password", "")}
    elif t == "vmess":
        out = {"type": "vmess", "tag": name, "server": server, "server_port": port,
               "uuid": p.get("uuid", ""), "security": p.get("cipher", "auto"),
               "alter_id": int(p.get("alterId", 0) or 0)}
        if p.get("network") == "ws":
            out["transport"] = _sb_ws(p)
        tls = _sb_tls(p)
        if tls:
            out["tls"] = tls
    elif t == "trojan":
        out = {"type": "trojan", "tag": name, "server": server, "server_port": port,
               "password": p.get("password", ""), "tls": _sb_tls(p)}
    elif t == "hysteria2":
        out = {"type": "hysteria2", "tag": name, "server": server, "server_port": port,
               "password": str(p.get("password", p.get("auth", ""))), "tls": _sb_tls(p)}
        if p.get("obfs") == "salamander":
            out["obfs"] = {"type": "salamander", "password": p.get("obfs-password", "")}
    elif t == "anytls":
        out = {"type": "anytls", "tag": name, "server": server, "server_port": port,
               "password": p.get("password", ""), "tls": _sb_tls(p)}
    else:
        return None
    if p.get("udp"):
        out["udp_enabled"] = True
    return out


def build_singbox_config(proxy_lists, settings):
    """sing-box 仅支持 selector / urltest 两种出站组，策略组自动降级映射"""
    import generator as gen
    proxies = gen.apply_node_policies(proxy_lists, settings)
    names = [p["name"] for p in proxies]

    outbounds, skipped = [], 0
    for p in proxies:
        ob = _proxy_to_outbound(p)
        if ob:
            outbounds.append(ob)
        else:
            skipped += 1
    usable = [ob["tag"] for ob in outbounds]

    group_outbounds = []
    if usable:
        group_outbounds.append({"type": "urltest", "tag": gen.GROUP_URLTEST, "outbounds": usable,
                                "url": settings.get("test_url") or gen.TEST_URL_DEFAULT,
                                "interval": f"{settings.get('urltest_interval') or 300}s"})
        selector = {"type": "selector", "tag": gen.GROUP_SELECT,
                    "outbounds": [gen.GROUP_URLTEST] + usable + ["direct"],
                    "default": gen.GROUP_URLTEST}
    else:
        selector = {"type": "selector", "tag": gen.GROUP_SELECT, "outbounds": ["direct"]}

    return {
        "log": {"level": "warn", "timestamp": True},
        "outbounds": [selector] + group_outbounds + outbounds + [
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
            {"type": "dns", "tag": "dns-out"},
        ],
        "route": {
            "rules": [
                {"protocol": "dns", "outbound": "dns-out"},
                {"domain_suffix": [".cn"], "outbound": "direct"},
                {"ip_is_private": True, "outbound": "direct"},
            ],
            "final": gen.GROUP_SELECT,
            "auto_detect_interface": True,
        },
    }, skipped
