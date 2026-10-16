"""聚合配置生成：可配置策略组、地区自动分组、节点过滤/重命名"""
import re

import yaml

import regions

TEST_URL_DEFAULT = "http://www.gstatic.com/generate_204"

GROUP_SELECT = "节点选择"
GROUP_URLTEST = "自动选择"
GROUP_FALLBACK = "故障转移"
GROUP_LB = "负载均衡"
GROUP_REGION = "地区选择"

DEFAULT_RULES = [
    "DOMAIN-SUFFIX,local,DIRECT",
    "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
    "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
    "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
    "GEOSITE,category-ads-all,REJECT",
    "GEOSITE,cn,DIRECT",
    "GEOIP,private,DIRECT,no-resolve",
    "GEOIP,CN,DIRECT,no-resolve",
    f"MATCH,{GROUP_SELECT}",
]


def dedupe_proxies(proxies):
    """扁平化去重（跨机场重名自动加序号），保持顺序"""
    seen = set()
    out = []
    for p in proxies:
        name = str(p.get("name", ""))
        if not name:
            continue
        if name in seen:
            i = 2
            while f"{name} {i}" in seen:
                i += 1
            name = f"{name} {i}"
            p = dict(p)
            p["name"] = name
        seen.add(name)
        out.append(p)
    return out


def transform_name(name, sub_name, settings):
    """单节点名称处理（过滤 / 重命名 / 机场前缀），返回 None 表示被过滤"""
    if settings.get("node_filter_regex"):
        try:
            if re.search(settings["node_filter_regex"], name):
                return None
        except re.error:
            pass
    if settings.get("node_rename_regex"):
        try:
            name = re.sub(settings["node_rename_regex"], settings.get("node_rename_to") or "", name)
        except re.error:
            pass
    if str(settings.get("node_prefix_airport", "1")) == "1":
        name = f"[{sub_name}] {name}"
    return name


def _pinned_keys(settings):
    """返回置顶节点 key 集合：(sub_id, raw_name)"""
    import json
    try:
        items = json.loads(settings.get("pinned_nodes") or "[]")
    except (ValueError, TypeError):
        return []
    order = []
    for it in items:
        if isinstance(it, dict) and "sub_id" in it and "name" in it:
            order.append((it["sub_id"], it["name"]))
    return order


def apply_node_policies(proxy_lists, settings):
    """节点过滤 / 重命名 / 机场前缀 / 星标置顶。
    proxy_lists: [(sub_id, sub_name, proxies_list)]，返回处理后的扁平 proxies 列表（置顶节点在前）"""
    pin_order = _pinned_keys(settings)
    pinned_rank = {k: i for i, k in enumerate(pin_order)}
    normal, pinned = [], []
    for sub_id, sub_name, plist in proxy_lists:
        for p in plist:
            p = dict(p)
            name = str(p.get("name", ""))
            if not name:
                continue
            new_name = transform_name(name, sub_name, settings)
            if new_name is None:
                continue
            p["name"] = new_name
            if (sub_id, name) in pinned_rank:
                p["_pin"] = pinned_rank[(sub_id, name)]
                pinned.append(p)
            else:
                normal.append(p)
    pinned.sort(key=lambda x: x["_pin"])
    for p in pinned:
        p.pop("_pin", None)
    return dedupe_proxies(pinned + normal)


def _parse_rules(settings):
    custom = (settings.get("custom_rules") or "").strip()
    if custom:
        rules = [ln.strip() for ln in custom.splitlines() if ln.strip()]
        if rules:
            return rules
    return list(DEFAULT_RULES)


def build_clash_config(proxy_lists, settings):
    """proxy_lists: [(sub_name, proxies_list)]"""
    proxies = apply_node_policies(proxy_lists, settings)
    names = [p["name"] for p in proxies]

    test_url = settings.get("test_url") or TEST_URL_DEFAULT
    interval = int(settings.get("urltest_interval") or 300)
    tolerance = int(settings.get("urltest_tolerance") or 50)
    lb_strategy = settings.get("lb_strategy") or "consistent-hashing"

    if not proxies:
        groups = [{"name": GROUP_SELECT, "type": "select", "proxies": ["DIRECT"]}]
    else:
        members = [GROUP_URLTEST, GROUP_FALLBACK, GROUP_LB]
        groups = []

        # 地区自动分组（OpenClash 安全：组名纯中文）
        if str(settings.get("region_groups", "1")) == "1":
            region_map = {}
            for n in names:
                r = regions.detect(n)
                if r:
                    region_map.setdefault(r, []).append(n)
            for r in sorted(region_map):
                groups.append({
                    "name": r, "type": "url-test", "url": test_url,
                    "interval": interval, "tolerance": tolerance, "lazy": True,
                    "proxies": region_map[r],
                })
            if region_map:
                members.append(GROUP_REGION)
                groups.append({
                    "name": GROUP_REGION, "type": "select",
                    "proxies": sorted(region_map.keys()),
                })

        # 主选择组：默认选中自动选择（url-test）→ 全自动切换
        groups.insert(0, {
            "name": GROUP_SELECT, "type": "select",
            "proxies": members + names + ["DIRECT"],
        })
        groups += [
            {"name": GROUP_URLTEST, "type": "url-test", "url": test_url,
             "interval": interval, "tolerance": tolerance, "lazy": True, "proxies": names},
            {"name": GROUP_FALLBACK, "type": "fallback", "url": test_url,
             "interval": interval, "lazy": True, "proxies": names},
            {"name": GROUP_LB, "type": "load-balance", "strategy": lb_strategy,
             "url": test_url, "interval": interval, "lazy": True, "proxies": names},
        ]

    return {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "unified-delay": True,
        "external-controller": "127.0.0.1:9090",
        "dns": {
            "enable": True,
            "enhanced-mode": "fake-ip",
            "nameserver": ["223.5.5.5", "119.29.29.29"],
            "fallback": ["8.8.8.8", "1.1.1.1"],
        },
        "proxies": proxies,
        "proxy-groups": groups,
        "rules": _parse_rules(settings),
    }


def dump_yaml(cfg) -> str:
    class NoAliasDumper(yaml.SafeDumper):
        def ignore_aliases(self, data):
            return True

    return yaml.dump(cfg, Dumper=NoAliasDumper, allow_unicode=True,
                     sort_keys=False, default_flow_style=False, width=4096)
