"""parser 单元测试：各种订阅格式与分享链接变体"""
import base64
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from parser import parse_ss, parse_subscription, parse_trojan, parse_vmess  # noqa: E402


def b64(s):
    return base64.b64encode(s.encode()).decode()


class TestSS(unittest.TestCase):
    def test_sip002(self):
        userinfo = base64.urlsafe_b64encode(b"aes-256-gcm:pass123").decode().rstrip("=")
        p = parse_ss(f"ss://{userinfo}@1.2.3.4:8388#%E9%A6%99%E6%B8%AF01")
        self.assertEqual(p["type"], "ss")
        self.assertEqual(p["cipher"], "aes-256-gcm")
        self.assertEqual(p["password"], "pass123")
        self.assertEqual(p["server"], "1.2.3.4")
        self.assertEqual(p["port"], 8388)
        self.assertEqual(p["name"], "香港01")

    def test_full_base64(self):
        body = base64.urlsafe_b64encode(b"chacha20-ietf-poly1305:pw@5.6.7.8:443").decode().rstrip("=")
        p = parse_ss(f"ss://{body}")
        self.assertEqual(p["cipher"], "chacha20-ietf-poly1305")
        self.assertEqual(p["port"], 443)


class TestVmess(unittest.TestCase):
    def test_ws_tls(self):
        payload = {"v": "2", "ps": "日本01", "add": "jp.example.com", "port": "443",
                   "id": "uuid-1234", "aid": "0", "scy": "auto", "net": "ws",
                   "path": "/ws", "host": "cdn.example.com", "tls": "tls"}
        p = parse_vmess("vmess://" + b64(json.dumps(payload)))
        self.assertEqual(p["name"], "日本01")
        self.assertEqual(p["port"], 443)
        self.assertTrue(p["tls"])
        self.assertEqual(p["network"], "ws")
        self.assertEqual(p["ws-opts"]["path"], "/ws")
        self.assertEqual(p["ws-opts"]["headers"]["Host"], "cdn.example.com")


class TestTrojan(unittest.TestCase):
    def test_basic(self):
        p = parse_trojan("trojan://secret@tr.example.com:443?sni=tr.example.com#%E7%BE%8E%E5%9B%BD")
        self.assertEqual(p["type"], "trojan")
        self.assertEqual(p["password"], "secret")
        self.assertEqual(p["sni"], "tr.example.com")
        self.assertEqual(p["name"], "美国")


class TestParseSubscription(unittest.TestCase):
    def test_clash_yaml(self):
        text = """
proxies:
  - name: node1
    type: ss
    server: 1.1.1.1
    port: 443
    cipher: aes-128-gcm
    password: x
"""
        proxies = parse_subscription(text)
        self.assertEqual(len(proxies), 1)
        self.assertEqual(proxies[0]["name"], "node1")

    def test_base64_links(self):
        links = "ss://" + base64.urlsafe_b64encode(b"aes-128-gcm:pw").decode().rstrip("=") + "@1.1.1.1:443#A\n"
        links += "trojan://pw@2.2.2.2:443#B\n"
        text = b64(links)
        proxies = parse_subscription(text)
        self.assertEqual(len(proxies), 2)
        self.assertEqual({p["type"] for p in proxies}, {"ss", "trojan"})

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_subscription("这不是订阅内容")


if __name__ == "__main__":
    unittest.main()
