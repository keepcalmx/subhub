#!/usr/bin/env bash
# SubHub 服务器端部署脚本（用户级 systemd，无需 sudo）
# 部署目录：~/subhub，端口：8900
set -e
APP_DIR="$HOME/subhub"

if [ ! -d "$APP_DIR/backend" ]; then
    echo "错误：请先将项目解压到 $APP_DIR（backend/ 在其下）"
    exit 1
fi

cd "$APP_DIR/backend"

# 1) Python 虚拟环境 + 依赖
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r ../requirements.txt
echo "[1/3] 依赖安装完成"

# 2) 用户级 systemd 服务
mkdir -p ~/.config/systemd/user
cp "$APP_DIR/deploy/subhub.service" ~/.config/systemd/user/subhub.service
systemctl --user daemon-reload
systemctl --user enable --now subhub
echo "[2/3] systemd 用户服务已启动并设为自启"

# 3) linger（开机不登录也运行；需要时会有提示）
loginctl enable-linger "$USER" 2>/dev/null \
    && echo "      linger 已开启（开机自动运行）" \
    || echo "      提示：执行 sudo loginctl enable-linger $USER 可实现开机自动运行"

# 4) 健康检查
sleep 3
if curl -sf http://127.0.0.1:8900/api/dashboard > /dev/null; then
    echo "[3/3] 部署成功：http://<服务器IP>:8900"
else
    echo "[3/3] 警告：服务未响应，日志："
    journalctl --user -u subhub -n 30 --no-pager || true
    exit 1
fi
