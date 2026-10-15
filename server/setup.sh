#!/usr/bin/env bash
# zt-homelab 一键部署脚本（单台服务器：moon + controller + 授权台）
# 依赖: Ubuntu/Debian + Docker + curl
# 用法: sudo bash setup.sh
set -euo pipefail

echo "🌐 ZeroTier Homelab 一键部署"
echo "=========================================="

# ── 配置（可用环境变量覆盖）──
ZT_HOME="${ZT_HOME:-/opt/zt-ctrl}"
ZT_UDP_PORT="${ZT_UDP_PORT:-9993}"
ZT_ADMIN_PORT="${ZT_ADMIN_PORT:-3444}"
NETWORK_NAME="${NETWORK_NAME:-homelab}"
NETWORK_CIDR="${NETWORK_CIDR:-172.22.0.0/24}"
NETWORK_POOL_START="${NETWORK_POOL_START:-172.22.0.10}"
NETWORK_POOL_END="${NETWORK_POOL_END:-172.22.0.100}"
MTU="${MTU:-1300}"

# ── 前置检查 ──
if [[ $EUID -ne 0 ]]; then echo "❌ 请用 sudo 运行"; exit 1; fi
if ! command -v docker &>/dev/null; then
  echo "📦 安装 Docker..."
  curl -fsSL https://get.docker.com | sh
fi

# ── 1. 部署控制器容器（ZeroTier 1.14.2，最后的自由版 controller）──
echo "📤 拉取控制器镜像..."
if ! docker pull keynetworks/ztncui:latest 2>/dev/null; then
  echo "⚠️  国内网络拉取失败？请配置镜像加速后重试，或参考 README 的离线导入方案"
  exit 1
fi

mkdir -p "$ZT_HOME"
echo "🚀 启动控制器（UDP $ZT_UDP_PORT + 管理 $ZT_ADMIN_PORT）..."
docker run -d --name zt-controller --restart unless-stopped \
  -p ${ZT_UDP_PORT}:9993 -p ${ZT_UDP_PORT}:9993/udp \
  -v "$ZT_HOME":/var/lib/zerotier-one \
  keynetworks/ztncui:latest

sleep 8

# ── 2. 读取控制器身份，创建网络 ──
CTRL_ADDR=$(docker exec zt-controller head -c10 /var/lib/zerotier-one/identity.public)
echo "🆔 控制器地址: $CTRL_ADDR"
NWID="${CTRL_ADDR}$(openssl rand -hex 3 | cut -c1-6)"

docker exec zt-controller sh -c "cat > /var/lib/zerotier-one/controller.d/network/${NWID}.json" <<EOF
{
  "id": "$NWID",
  "nwid": "$NWID",
  "objtype": "network",
  "name": "$NETWORK_NAME",
  "private": true,
  "enableBroadcast": true,
  "mtu": $MTU,
  "v4AssignMode": {"zt": true},
  "ipAssignmentPools": [{"network": "$NETWORK_CIDR", "start": "$NETWORK_POOL_START", "end": "$NETWORK_POOL_END"}],
  "routes": [{"target": "$NETWORK_CIDR", "via": null}],
  "rules": [{"type": "ACTION_ACCEPT"}],
  "creationTime": $(date +%s)000,
  "lastModified": $(date +%s)000
}
EOF
docker restart zt-controller >/dev/null
sleep 8

echo "🌐 网络已创建: $NWID ($NETWORK_NAME, $NETWORK_CIDR, MTU $MTU)"

# ── 3. moon（同一进程兼当根服务器）──
echo "🌙 生成 moon 定义..."
MOON_JSON=$(docker exec zt-controller cat /var/lib/zerotier-one/identity.public)
# 注意: moon 的 stableEndpoints 需要本机公网 IP
PUB_IP=$(curl -s -m 8 ifconfig.me || curl -s -m 8 ip.sb)
echo "{\"worldType\":\"moon\",\"id\":\"${CTRL_ADDR}0001\",\"revision\":1,\"roots\":[{\"identity\":\"$MOON_JSON\",\"stableEndpoints\":[\"$PUB_IP/$ZT_UDP_PORT\"]}],\"signingKeys\":[\"\$(docker exec zt-controller cat /var/lib/zerotier-one/identity.secret | cut -d: -f4)\"]}" > /tmp/moon-req.json
docker cp /tmp/moon-req.json zt-controller:/tmp/ && \
  docker exec zt-controller sh -c "cd /var/lib/zerotier-one && zerotier-idtool genmoon /tmp/moon-req.json && mkdir -p moons.d && cp 000000*.moon moons.d/" || \
  echo "⚠️ moon 生成失败（不影响控制器功能，可手动执行）"
docker restart zt-controller >/dev/null

# ── 4. 授权台 ──
echo "🖥️  部署授权台 zt-admin..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/zt-admin.py" "$ZT_HOME/zt-admin.py"

cat > /etc/systemd/system/zt-admin.service <<EOF
[Unit]
Description=ZeroTier Homelab Admin
After=docker.service

[Service]
Environment=ZT_NETWORK_ID=$NWID
Environment=ZT_HOME=$ZT_HOME
Environment=ZT_CONTROLLER_TRANSPORT=docker
Environment=ZT_CONTROLLER_CONTAINER=zt-controller
ExecStart=/usr/bin/python3 $ZT_HOME/zt-admin.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload && systemctl enable --now zt-admin

# ── 5. 输出 ──
MOON_FILE=$(ls "$ZT_HOME"/moons.d/*.moon 2>/dev/null | head -1)
echo ""
echo "=========================================="
echo "✅ 部署完成！"
echo ""
echo "  网络名称: $NETWORK_NAME"
echo "  网络 ID:  $NWID"
echo "  网段:     $NETWORK_CIDR (MTU $MTU)"
echo "  Moon:     $PUB_IP:$ZT_UDP_PORT/udp"
echo "  Moon 文件: ${MOON_FILE:-$ZT_HOME/moons.d/} (分发给客户端 orbit)"
echo "  授权台:   http://127.0.0.1:$ZT_ADMIN_PORT (SSH隧道访问: ssh -L $ZT_ADMIN_PORT:127.0.0.1:$ZT_ADMIN_PORT server)"
echo ""
echo "⚠️⚠️ 云安全组必须放行 UDP $ZT_UDP_PORT（不是 TCP！）"
echo "   ZeroTier 是纯 UDP 协议。开 TCP 没有任何效果——"
echo "   这是最常见的第一个坑：症状是 join 请求石沉大海、peers 延迟 -1。"
echo "   注意：『修改』已有规则会让原端口失效，务必『新增』一条 UDP 规则。"
echo "   验证方法（Mac/Linux 客户端）：echo t | nc -u -w1 $PUB_IP $ZT_UDP_PORT"
echo "   同时在服务器 tcpdump -ni eth0 udp port $ZT_UDP_PORT 看包是否到达。"
echo ""
echo "客户端接入:"
echo "  1. zerotier-cli orbit <moon地址> <moon地址>"
echo "  2. zerotier-cli join $NWID"
echo "  3. 授权台点「授权」"
