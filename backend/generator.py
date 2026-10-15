"""聚合配置生成：fallback / url-test / load-balance 策略组，自动切换"""
import yaml

TEST_URL = "http://www.gstatic.com/generate_204"

GROUP_SELECT = "节点选择"
GROUP_URLTEST = "自动选择"
GROUP_FALLBACK = "故障转移"
GROUP_LB = "负载均衡"


def _dedupe(proxies):
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


def build_clash_config(proxy_lists):
    """proxy_lists: 每个机场一份 proxies 列表"""
    proxies = _dedupe([p for plist in proxy_lists for p in plist])
    names = [p["name"] for p in proxies]

    if proxies:
        groups = [
            {
                "name": GROUP_SELECT,
                "type": "select",
                # 自动切换：默认选中 url-test 组
                "proxies": [GROUP_URLTEST, GROUP_FALLBACK, GROUP_LB] + names + ["DIRECT"],
            },
            {
                "name": GROUP_URLTEST,
                "type": "url-test",
                "url": TEST_URL,
                "interval": 300,
                "tolerance": 50,
                "lazy": True,
                "proxies": names,
            },
            {
                "name": GROUP_FALLBACK,
                "type": "fallback",
                "url": TEST_URL,
                "interval": 300,
                "lazy": True,
                "proxies": names,
            },
            {
                "name": GROUP_LB,
                "type": "load-balance",
                "strategy": "consistent-hashing",
                "url": TEST_URL,
                "interval": 300,
                "lazy": True,
                "proxies": names,
            },
        ]
    else:
        groups = [{"name": GROUP_SELECT, "type": "select", "proxies": ["DIRECT"]}]

    rules = [
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
        "rules": rules,
    }


def dump_yaml(cfg) -> str:
    class NoAliasDumper(yaml.SafeDumper):
        def ignore_aliases(self, data):
            return True

    return yaml.dump(cfg, Dumper=NoAliasDumper, allow_unicode=True,
                     sort_keys=False, default_flow_style=False, width=4096)
