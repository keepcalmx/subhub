# 复用 python:3.12-slim 作为基础（体积略大但含 CA 证书，且国内镜像源易拉取）
FROM python:3.12-slim

ARG MIHOMO_VERSION=v1.19.32
ENV MIHOMO_VERSION=${MIHOMO_VERSION}

COPY . /tmp/ctx

# 构建上下文同目录若存在已下载的 mihomo 二进制（离线/内网场景推荐），直接使用；
# 否则从 GitHub 下载 compatible 版本（兼容无 AVX 指令集的老 CPU，如 N5105）
RUN set -e; \
    if [ -f /tmp/ctx/mihomo ]; then \
      echo "[mihomo] 使用本地二进制"; \
      mv /tmp/ctx/mihomo /usr/local/bin/mihomo; \
    else \
      echo "[mihomo] 从 GitHub 下载 ${MIHOMO_VERSION}"; \
      python /tmp/ctx/get_mihomo.py; \
    fi; \
    chmod +x /usr/local/bin/mihomo; \
    rm -rf /tmp/ctx

EXPOSE 9097

CMD ["/usr/local/bin/mihomo", "-d", "/root/.config/mihomo"]
