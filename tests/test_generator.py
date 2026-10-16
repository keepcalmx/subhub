"""generator / converters 单元测试：策略组、地区分组、节点处理、星标置顶、多格式转换"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import converters  # noqa: E402
import generator  # noqa: E402

DEFAULT_SETTINGS = {
    "node_prefix_airport": "1", "region_groups": "1",
    "urltest_interval": "300", "urltest_tolerance": "50",
    "lb_strategy": "consistent-hashing",
    "test_url": "http://www.gstatic.com/generate_204",
    "node_filter_regex": "", "node_rename_regex": "", "node_rename_to": "",
    "custom_rules": "", "pinned_nodes": "[]",
}


def settings(**over):
    s = copy.deepcopy(DEFAULT_SETTINGS)
    s.update(over)
    return s


SUB_A = [(1, "机场A", [
    {"name": "香港01", "type": "ss", "server": "1.1.1.1", "port": 443, "cipher": "aes-128-gcm", "password": "x"},
    {"name": "日本01", "type": "vmess", "server": "2.2.2.2", "port": 443, "uuid": "u", "alterId": 0},
])]

SUB_B = [(2, "机场B", [
    {"name": "香港01", "type": "trojan", "server": "3.3.3.3", "port": 443, "password": "y"},
    {"name": "官网", "type": "ss", "server": "4.4.4.4", "port": 443, "cipher": "aes-128-gcm", "password": "z"},
])]


class TestGenerator(unittest.TestCase):
    def test_groups_and_prefix(self):
        cfg = generator.build_clash_config(SUB_A + SUB_B, settings())
        names = [g["name"] for g in cfg["proxy-groups"]]
        self.assertIn("节点选择", names)
        self.assertIn("地区选择", names)
        self.assertIn("香港", names)
        self.assertIn("日本", names)
        proxy_names = [p["name"] for p in cfg["proxies"]]
        self.assertTrue(all(n.startswith("[机场") for n in proxy_names))
        # 跨机场重名自动加序号
        self.assertEqual(len(proxy_names), len(set(proxy_names)))
        # 默认全自动切换：节点选择第一项是自动选择
        select = cfg["proxy-groups"][0]
        self.assertEqual(select["type"], "select")
        self.assertEqual(select["proxies"][0], "自动选择")
        # MATCH 指向存在的组
        match = cfg["rules"][-1]
        self.assertEqual(match, "MATCH,节点选择")

    def test_filter_and_rename(self):
        s = settings(node_filter_regex="官网", node_rename_regex="香港", node_rename_to="HK", node_prefix_airport="0")
        cfg = generator.build_clash_config(SUB_A + SUB_B, s)
        names = [p["name"] for p in cfg["proxies"]]
        self.assertNotIn("官网", names)
        self.assertIn("HK01", names)

    def test_pinned_first(self):
        s = settings(pinned_nodes='[{"sub_id": 2, "name": "香港01"}]', node_prefix_airport="0")
        cfg = generator.build_clash_config(SUB_A + SUB_B, s)
        self.assertEqual(cfg["proxies"][0]["name"], "香港01")
        # 置顶的是机场B的香港节点
        self.assertEqual(cfg["proxies"][0]["server"], "3.3.3.3")

    def test_custom_rules(self):
        s = settings(custom_rules="DOMAIN-SUFFIX,example.com,DIRECT\nMATCH,节点选择")
        cfg = generator.build_clash_config(SUB_A, s)
        self.assertEqual(cfg["rules"][0], "DOMAIN-SUFFIX,example.com,DIRECT")

    def test_region_groups_off(self):
        cfg = generator.build_clash_config(SUB_A, settings(region_groups="0"))
        names = [g["name"] for g in cfg["proxy-groups"]]
        self.assertNotIn("地区选择", names)
        self.assertNotIn("香港", names)  # 关闭后不建独立地区组


class TestConverters(unittest.TestCase):
    def test_v2ray_links(self):
        proxies = generator.apply_node_policies(SUB_A + SUB_B, settings(node_prefix_airport="0"))
        b64, skipped = converters.build_v2ray_base64(proxies)
        import base64 as _b64
        links = _b64.b64decode(b64).decode().splitlines()
        self.assertEqual(len(links), 4)
        self.assertEqual(skipped, 0)

    def test_singbox(self):
        cfg, skipped = converters.build_singbox_config(SUB_A, settings())
        types = {ob["type"] for ob in cfg["outbounds"]}
        self.assertIn("selector", types)
        self.assertIn("urltest", types)
        self.assertEqual(cfg["route"]["final"], "节点选择")


if __name__ == "__main__":
    unittest.main()
