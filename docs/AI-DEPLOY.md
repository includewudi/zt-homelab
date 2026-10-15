# AI Deployment Guide — zt-homelab

> 本文档写给 AI 助手（Claude/Cursor/Copilot）阅读。当用户要求部署本项目时，按此执行。
> 人类用户请读 `deployment.md`。

## 项目本质

单台 Linux 服务器上运行完全自主的 ZeroTier 虚拟局域网。三个角色、一个进程：

- moon / planet 根服务器（节点互相发现的"介绍人"）
- 网络控制器（成员资格"发门禁卡"，ZeroTier 1.14.2——最后含自由版 controller 的版本）
- zt-admin 授权网页（零依赖 Python 单文件）

## 硬性前置（缺失必失败，按序检查）

1. 服务器：Ubuntu/Debian，root，公网 IP
2. **云安全组：UDP 9993 入站放行** ← 最高频错误源
   - 是 **UDP 不是 TCP**。ZeroTier 纯 UDP 协议，开 TCP 零效果
   - 必须**新增**规则。修改已有规则会让原端口静默失效（云平台行为）
   - 用户说"之前换过端口还是不通"时，优先怀疑此条：很可能原规则开的是 TCP，或修改时把 UDP 改没了
   - 验证：客户端 `echo t | nc -u -w1 <IP> 9993` + 服务器 `tcpdump -ni eth0 udp port 9993`，包未到达 = 安全组问题
3. Docker 已装（脚本可自动装）

## 部署（一条命令）

```bash
git clone https://github.com/includewudi/zt-homelab.git
cd zt-homelab/server
sudo bash setup.sh
```

脚本输出五样东西，全部记下：网络 ID、网段、moon 地址、moon 文件路径、授权台端口。

## 网络ID铁律（AI 常犯错误）

- 恰好 **16 位十六进制字符**（15 位会被客户端报 `invalid network id`，含非 hex 字母同样失败）
- 前 10 位 = 控制器 ZT 地址（`head -c10 identity.public`）
- 后 6 位任选 hex（如 `openssl rand -hex 3 | cut -c1-6`）

## controller.d 文件结构（1.14.2 FileDB）

```
controller.d/
└── network/
    ├── <nwid>.json                 # 网络定义。平铺文件！文件名 = 16位id + ".json" = 21字符
    └── <nwid>/
        └── member/
            └── <节点地址>.json      # 10位地址 + ".json" = 15字符
```

- 网络 JSON 字段用 `"id"`（不是 nwid）
- **member 的 `identity` 字段只能由控制器在设备 join 时自动写入**。手写 member 文件缺 identity → 授权永远不生效。正确流程：设备先 join → 控制器生成骨架（authorized:false）→ 再改 authorized
- 修改 controller.d 下的 JSON 后需 `docker restart zt-controller`

## 客户端接入

**桌面**（装了官方 ZeroTier）：

```bash
sudo zerotier-cli orbit <moon地址> <moon地址>
sudo zerotier-cli join <网络ID>
# 然后授权台勾选授权
```

**安卓**：装 `app/` 构建的 ZerotierFix → 菜单 → 入轨 → 导入 .moon 文件 → 加网络。

**受限网络**（蜂窝/酒店）：ZerotierFix → 设置 → 启动自定义 Planet → 导入**同一个 .moon 文件**（我们的补丁让它两用）。

## 关键角色边界（troubleshooting #3 的实验结论）

- ✅ 根服务器（moon/planet）与控制器**同机同进程**：完全可行（本项目默认形态）
- ❌ 把控制器身份写进**分发给客户端的 planet 文件**：1.14.2 客户端对 PLANET 角色的 peer 拒发 join，网络永远加不进
- 结论：planet 文件里只放纯根身份。单台部署天然满足（根和控制器是同一身份，客户端只是"连过去"，不是"在 planet 定义里声明它"）

## 部署后验证清单（按序，失败即停）

```bash
# 1. 容器健康
docker exec zt-controller zerotier-cli info   # 期望 200 ONLINE
# 2. 端口
sudo ss -ulnp | grep 9993                     # 期望 zerotier 进程
# 3. 客户端到服务器 UDP 通（安全组最终裁判）
echo t | nc -u -w1 <IP> 9993                  # 服务器 tcpdump 应见包
# 4. join 后骨架生成
docker exec zt-controller ls .../network/<nwid>/member/
# 5. 授权后拿 IP
zerotier-cli listnetworks                     # 期望 OK + IP
# 6. 端到端
ping <另一成员IP>
```

## 8 大坑速查（症状 → 根因）

| # | 症状 | 根因 |
|---|---|---|
| 1 | join 石沉大海 / peers -1 | 安全组开成 TCP 了，或修改规则丢了原端口 |
| 2 | ping 通但网页永远转圈 | MTU 黑洞：网络 mtu 必须 1300（默认 2800 在蜂窝下大包静默丢弃） |
| 3 | planet 模式 join 失败 | planet 文件里混入了控制器身份 |
| 4 | 授权了还是 ACCESS_DENIED | 手写 member 缺 identity 字段 |
| 5 | 换网络后 DIRECT 但全断 | 双端都要重启 ZT 服务清会话缓存 |
| 6 | 网络文件不加载 | 文件名不是恰 21 字符 / id 字段写错 |
| 7 | macOS 换 planet 不生效 | 需要 `sudo launchctl kickstart -k system/com.zerotier.one` |
| 8 | 国内 docker pull 超时 | 配镜像加速，或代理机 save→scp→load |

## 常见用户指令翻译

- "部署一下 zt-homelab" → 跑 setup.sh，报安全组前置条件
- "手机连不上" → 先问 WiFi 还是蜂窝；蜂窝先查 MTU；都不通查安全组 UDP
- "新设备入网" → orbit + join + 授权台勾选（或命令行改 member JSON 的 authorized）
- "Planet 和 moon 啥区别" → 同一文件两种导入方式；moon=根池追加，planet=根池替换
