# SubHub · 机场订阅聚合平台

聚合多个机场订阅，统一输出一份 Clash/Mihomo 配置，含 url-test / fallback / load-balance 策略组（自动切换），并提供 Web 管理页面与定时检查。

## 功能

- **订阅聚合**：支持 Clash YAML 订阅与 Base64 分享链接（ss / vmess / trojan 自动转换为 Clash 节点）
- **定时检查**：APScheduler 按设定间隔（默认 30 分钟）抓取各机场订阅
  - 流量信息：解析 `subscription-userinfo` 响应头（已用 / 总量 / 到期时间）
  - 节点状态：对每个节点 server:port 做 TCP 探测（并发 100，超时 5s），记录存活与延迟
- **聚合订阅地址**：`/api/subscribe/{token}`，输出带以下策略组的完整配置：
  - 🚀 节点选择（select，默认指向自动测速组 → 全自动切换）
  - 自动选择（url-test，300s 测速，容差 50ms）
  - 🔯 故障转移（fallback）
  - 负载均衡（load-balance，consistent-hashing）
  - 规则：广告拦截 + 国内直连 + 其余走代理
- **Web 管理页**：订阅增删改/启停、流量进度条、节点存活列表、检查间隔与 Token 管理

## 技术栈

FastAPI + SQLite(aiosqlite) + APScheduler + httpx + PyYAML；前端 Vue3（CDN 单文件，浅色液态玻璃风）

## 运行

```bash
cd sub-aggregator
python -m venv .venv
# Windows: .venv\Scripts\activate   Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8899 --app-dir backend
```

访问 `http://<host>:8899` 进入管理页。

## 使用

1. 管理页添加各机场订阅链接（建议使用 Clash 格式链接；Base64 分享链接也可）
2. 添加后自动抓取检查；也可点「检查」手动触发
3. 复制页面顶部的**聚合订阅地址**，导入 Clash Verge / Mihomo 等客户端
4. 客户端内「节点选择」组默认选中 自动选择（url-test），全自动切换；也可手动切到故障转移 / 负载均衡组

## 部署注意

- 数据库文件位于 `backend/data/aggregator.db`，注意备份
- 公网部署建议置于 Nginx 反代之后，并自行加 Basic Auth / IP 白名单（当前管理页无鉴权，仅适合内网/本机使用）
- 聚合地址中的 Token 可在设置中重新生成，旧地址立即失效
- 部分机场要求特定 UA 才返回 Clash 格式，本服务抓取时已携带 `clash-verge` UA
