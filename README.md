# SubHub · 机场订阅聚合平台

聚合多个机场订阅，统一输出 Clash / sing-box / v2ray 配置，含 url-test / fallback / load-balance 策略组（自动切换）与地区智能分组，提供 Web 管理页、定时检查、真实测速与流量告警。

## 功能

### 订阅聚合
- 支持 Clash YAML 订阅与 Base64 分享链接（ss / vmess / trojan 自动转换为 Clash 节点）
- 节点处理：机场名前缀、正则过滤（剔除官网/到期/倍率节点）、正则重命名
- 多格式输出 `GET /api/subscribe/{token}`：
  - `?target=clash`（默认）：完整 Clash/Mihomo 配置
  - `?target=singbox`：sing-box JSON（selector + urltest）
  - `?target=v2ray`：base64 分享链接（ss / vmess / trojan / hysteria2；anytls 无标准 URI 会跳过）

### 策略组（全自动切换）
- 节点选择（select，默认指向自动选择 → 全自动切换）
- 自动选择（url-test）/ 故障转移（fallback）/ 负载均衡（load-balance）
- **地区智能分组**：按节点名自动识别香港/台湾/日本/美国/新加坡等 30 个地区，各建 url-test 组 + 地区选择组
- 测速间隔、容差、负载策略、自定义规则均可在设置页配置
- 组名纯中文（OpenClash 兼容，不用 emoji）

### 定时检查（APScheduler，默认 30 分钟）
- 流量：解析 `subscription-userinfo` 头（已用 / 总量 / 到期）
- 节点延迟两种模式：
  - **TCP 握手**（默认）：轻量连通性检测
  - **mihomo 真实测速**（推荐）：把节点推给本地 mihomo 实例做真实 URL 测速，失败自动回退 TCP
- **节点历史**：每次检查记录延迟/存活（保留 30 天），管理页可查看单节点 48h 延迟走势

### 告警通知（按天去重）
- 触发条件：剩余流量 < 10%、7 天内到期、订阅抓取失败
- 通道：Bark / Server酱 / Telegram / 通用 Webhook

### Web 管理页
- 订阅增删改/启停、流量进度条、节点存活列表与延迟走势图
- 检查间隔、策略组参数、节点处理规则、通知渠道、Token 管理
- 浅色液态玻璃风，Vue3 单文件无构建

## 技术栈

FastAPI + SQLite(aiosqlite, WAL) + APScheduler + httpx + PyYAML；前端 Vue3（CDN 单文件）

## 运行

```bash
cd sub-aggregator
python -m venv .venv
# Windows: .venv\Scripts\activate   Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8899 --app-dir backend
```

访问 `http://<host>:8899` 进入管理页。

## 启用 mihomo 真实测速（可选，推荐）

1. 部署一个专用 mihomo 实例（本机或同网服务器）：
```bash
mkdir -p ~/mihomo-test && cd ~/mihomo-test
# 下载对应平台的 mihomo：https://github.com/MetaCubeX/mihomo/releases
# 注意老 CPU（无 AVX 指令集，如 N5105）需用 compatible 版本
cat > config.yaml <<'EOF'
mixed-port: 17890
external-controller: 127.0.0.1:9097
secret: "换成随机字符串"
mode: rule
log-level: warning
proxies: []
EOF
./mihomo -d .
```
2. SubHub 设置页：检测模式选「mihomo 真实测速」，填 API 地址与 Secret

说明：测速时 SubHub 会把当前所有节点推给该 mihomo 实例并逐个测 URL 延迟，请勿把该实例同时用作日常代理。

## 使用

1. 管理页添加各机场订阅链接（Clash 格式或 Base64 分享链接）
2. 复制聚合订阅地址（可选 Clash / sing-box / v2ray 格式），导入客户端
3. 客户端内「节点选择」组默认选中 自动选择（url-test），全自动切换；也可切到故障转移 / 负载均衡 / 地区选择组

## 部署

### Docker（推荐）

```bash
git clone https://github.com/keepcalmx/subhub.git && cd subhub
docker compose up -d --build     # 一键起 SubHub(8900) + mihomo 测速实例
docker compose logs -f subhub
```

- 数据持久化：`backend/data/aggregator.db` 通过 bind mount 保留在宿主机
- 聚合地址：`http://<host>:8900/api/subscribe/{token}`（Token 在管理页设置中查看）
- 启用真实测速：设置页「检测模式」选 mihomo，API 地址填 `http://mihomo:9097`，Secret 见 `deploy/mihomo/config.yaml`（默认 `subhub-delay-test`，建议修改）
- mihomo 镜像优先使用 `deploy/mihomo/` 目录下已下载的二进制（离线环境），否则构建时从 GitHub 下载 compatible 版本

### systemd（无需 Docker）

`deploy/deploy.sh` 一键部署（用户级 systemd，无需 root），服务单元 `deploy/subhub.service`。

### 通用注意

- 数据库位于 `backend/data/aggregator.db`（含订阅 token，**严禁提交到公开仓库**，已在 .gitignore 排除）
- 公网部署务必加 Nginx 反代 + 认证（当前管理页无鉴权）
- 抓取走系统代理：设环境变量 `SUBHUB_PROXY=http://127.0.0.1:7890`（默认直连）
