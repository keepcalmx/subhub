"""构建镜像时下载 mihomo（compatible 版本，兼容无 AVX 的老 CPU）"""
import gzip
import os
import shutil
import urllib.request

VERSION = os.environ.get("MIHOMO_VERSION", "v1.19.32")
URL = (
    f"https://github.com/MetaCubeX/mihomo/releases/download/{VERSION}"
    f"/mihomo-linux-amd64-compatible-{VERSION}.gz"
)

print(f"[mihomo] 下载 {URL}")
req = urllib.request.Request(URL, headers={"User-Agent": "curl/8.4.0"})
with urllib.request.urlopen(req, timeout=180) as resp, gzip.open(resp, "rb") as gz:
    with open("/usr/local/bin/mihomo", "wb") as out:
        shutil.copyfileobj(gz, out)
print("[mihomo] 下载完成")
