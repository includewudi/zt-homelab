#!/usr/bin/env python3
"""Small ZeroTier controller UI using only the Python standard library."""

import ipaddress
import json
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


NWID = os.environ.get("ZT_NETWORK_ID", "${NWID}")
CONTROLLER_URL = os.environ.get("ZT_CONTROLLER_URL", "http://127.0.0.1:9993").rstrip("/")
TOKEN_FILE = os.environ.get("ZT_TOKEN_FILE", "/opt/zt-ctrl/authtoken.secret")
CONTROLLER_TRANSPORT = os.environ.get("ZT_CONTROLLER_TRANSPORT", "docker")
CONTROLLER_CONTAINER = os.environ.get("ZT_CONTROLLER_CONTAINER", "ztncui")
CONTAINER_TOKEN_FILE = os.environ.get("ZT_CONTAINER_TOKEN_FILE", "/var/lib/zerotier-one/authtoken.secret")
NAMES_FILE = os.environ.get("ZT_NAMES_FILE", "/opt/zt-ctrl/device-names.json")
LISTEN_HOST = os.environ.get("ZT_ADMIN_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("ZT_ADMIN_PORT", "3444"))
REQUEST_TIMEOUT = float(os.environ.get("ZT_CONTROLLER_TIMEOUT", "4"))
MEMBER_ID_RE = re.compile(r"^[0-9a-fA-F]{10}$")
MAX_BODY = 64 * 1024
MUTATION_LOCK = threading.RLock()

KNOWN_NAMES = {}  # 设备备注从 NAMES_FILE 加载


class ControllerError(RuntimeError):
    pass


CONTAINER_HTTP_CLIENT = r"""
import json, sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
p = json.load(sys.stdin)
try:
    with open(p["token_file"], encoding="utf-8") as f:
        token = f.read().strip()
    body = None if p["data"] is None else json.dumps(p["data"]).encode()
    headers = {"X-ZT1-Auth": token, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = Request(p["url"] + p["path"], data=body, headers=headers, method=p["method"])
    with urlopen(req, timeout=p["timeout"]) as response:
        raw = response.read().decode("utf-8", "replace")
    print(json.dumps({"ok": True, "body": raw}))
except HTTPError as e:
    print(json.dumps({"ok": False, "error": "HTTP %s" % e.code, "detail": e.read().decode("utf-8", "replace")[:300]}))
except Exception as e:
    print(json.dumps({"ok": False, "error": type(e).__name__}))
"""


def load_names():
    try:
        with open(NAMES_FILE, encoding="utf-8") as source:
            names = json.load(source)
        if isinstance(names, dict):
            KNOWN_NAMES.update({str(k): str(v) for k, v in names.items()})
    except (FileNotFoundError, OSError, ValueError):
        pass


def save_names():
    directory = os.path.dirname(NAMES_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(NAMES_FILE, "w", encoding="utf-8") as target:
        json.dump(KNOWN_NAMES, target, ensure_ascii=False, indent=2)


def _member_path(member_id=""):
    suffix = f"/{member_id}" if member_id else ""
    return f"/controller/network/{NWID}/member{suffix}"


def _network_path():
    return f"/controller/network/{NWID}"


def _validate_member_id(member_id):
    if not MEMBER_ID_RE.fullmatch(member_id):
        raise ValueError("无效的设备 ID")
    return member_id.lower()


def _decode_controller_body(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise ControllerError("控制器返回了无效 JSON") from exc


def _controller_request_docker(method, path, data):
    payload = json.dumps({
        "method": method,
        "path": path,
        "data": data,
        "url": CONTROLLER_URL,
        "token_file": CONTAINER_TOKEN_FILE,
        "timeout": REQUEST_TIMEOUT,
    })
    try:
        result = subprocess.run(
            ["docker", "exec", "-i", CONTROLLER_CONTAINER, "python3", "-c", CONTAINER_HTTP_CLIENT],
            input=payload,
            capture_output=True,
            text=True,
            timeout=REQUEST_TIMEOUT + 3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ControllerError("无法通过容器连接 ZeroTier 控制器") from exc
    if result.returncode != 0:
        raise ControllerError("ZeroTier 控制器容器调用失败")
    try:
        envelope = json.loads(result.stdout)
    except ValueError as exc:
        raise ControllerError("控制器容器返回了无效响应") from exc
    if not envelope.get("ok"):
        detail = envelope.get("detail") or envelope.get("error") or "未知错误"
        raise ControllerError(f"控制器请求失败：{detail}")
    return _decode_controller_body(envelope.get("body", ""))


def _controller_request_direct(method, path, data):
    try:
        with open(TOKEN_FILE, encoding="utf-8") as token_file:
            token = token_file.read().strip()
    except OSError as exc:
        raise ControllerError("无法读取控制器认证文件") from exc
    if not token:
        raise ControllerError("控制器认证文件为空")

    body = None if data is None else json.dumps(data).encode("utf-8")
    headers = {"X-ZT1-Auth": token, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(CONTROLLER_URL + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        suffix = f"：{detail}" if detail else ""
        raise ControllerError(f"控制器返回 HTTP {exc.code}{suffix}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ControllerError("无法连接 ZeroTier 控制器") from exc
    return _decode_controller_body(raw)


def controller_request(method, path, data=None):
    if CONTROLLER_TRANSPORT == "docker":
        return _controller_request_docker(method, path, data)
    if CONTROLLER_TRANSPORT == "direct":
        return _controller_request_direct(method, path, data)
    raise ControllerError("未知的控制器连接方式")


def get_member(member_id):
    member_id = _validate_member_id(member_id)
    member = controller_request("GET", _member_path(member_id))
    if not isinstance(member, dict):
        raise ControllerError("控制器返回了无效设备数据")
    return member


def _ipv4_assignments(member):
    result = []
    for value in member.get("ipAssignments") or []:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version == 4:
            result.append(str(address))
    return result


def member_view(member):
    member_id = str(member.get("id") or member.get("address") or "")
    ipv4 = _ipv4_assignments(member)
    return {
        "id": member_id,
        "authorized": bool(member.get("authorized", False)),
        "ip": ipv4[0] if ipv4 else "",
        "ipAssignments": member.get("ipAssignments") or [],
        "autoAssign": not bool(member.get("noAutoAssignIps", False)),
        "name": KNOWN_NAMES.get(member_id, ""),
        "lastSeen": member.get("lastSeenTime", 0),
        "ts": member.get("creationTime", 0),
    }


def list_members():
    revisions = controller_request("GET", _member_path())
    if not isinstance(revisions, dict):
        raise ControllerError("控制器成员列表格式无效")
    members = []
    for member_id in sorted(revisions):
        members.append(member_view(get_member(member_id)))
    return members


def _set_auth_locked(member_id, authorized):
    member_id = _validate_member_id(member_id)
    if type(authorized) is not bool:
        raise ValueError("authorized 必须是布尔值")
    controller_request("POST", _member_path(member_id), {"authorized": authorized})
    confirmed = member_view(get_member(member_id))
    if confirmed["authorized"] is not authorized:
        raise ControllerError("控制器未保存授权状态")
    return confirmed


def set_auth(member_id, authorized):
    with MUTATION_LOCK:
        return _set_auth_locked(member_id, authorized)


def network_ipv4_routes():
    network = controller_request("GET", _network_path())
    if not isinstance(network, dict):
        raise ControllerError("控制器网络配置格式无效")
    routes = network.get("routes")
    if routes is None and isinstance(network.get("config"), dict):
        routes = network["config"].get("routes")
    result = []
    for route in routes or []:
        if not isinstance(route, dict) or route.get("via") not in (None, ""):
            continue
        try:
            subnet = ipaddress.ip_network(route.get("target", ""), strict=False)
        except ValueError:
            continue
        if subnet.version == 4:
            result.append(subnet)
    if not result:
        raise ControllerError("网络没有可用的 IPv4 直连路由")
    return result


def _validate_ipv4(value, routes):
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ValueError("请输入有效的 IPv4 地址") from exc
    if address.version != 4:
        raise ValueError("请输入 IPv4 地址")
    matching_route = next((route for route in routes if address in route), None)
    if matching_route is None:
        allowed = "、".join(str(route) for route in routes)
        raise ValueError(f"IP 必须属于直连路由：{allowed}")
    if address in (matching_route.network_address, matching_route.broadcast_address):
        raise ValueError("不能使用网段地址或广播地址")
    if address.is_unspecified or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved:
        raise ValueError("不能使用本地或保留地址")
    return address


def _set_ip_locked(member_id, value):
    member_id = _validate_member_id(member_id)
    if not isinstance(value, str):
        raise ValueError("ip 必须是字符串")
    member = get_member(member_id)
    original_authorized = bool(member.get("authorized", False))
    retained = []
    for assignment in member.get("ipAssignments") or []:
        try:
            if ipaddress.ip_address(assignment).version != 4:
                retained.append(assignment)
        except ValueError:
            retained.append(assignment)

    value = value.strip()
    if value:
        address = _validate_ipv4(value, network_ipv4_routes())
        revisions = controller_request("GET", _member_path())
        if not isinstance(revisions, dict):
            raise ControllerError("控制器成员列表格式无效")
        for other_id in revisions:
            if other_id.lower() == member_id:
                continue
            if str(address) in _ipv4_assignments(get_member(other_id)):
                raise ValueError(f"IP {address} 已被设备 {other_id} 使用")
        retained.append(str(address))
        update = {"ipAssignments": retained, "noAutoAssignIps": True}
    else:
        update = {"ipAssignments": retained, "noAutoAssignIps": False}

    controller_request("POST", _member_path(member_id), update)
    confirmed = member_view(get_member(member_id))
    if confirmed["authorized"] is not original_authorized:
        raise ControllerError("控制器意外改变了授权状态")
    if value:
        if confirmed["ip"] != str(address) or confirmed["autoAssign"]:
            raise ControllerError("控制器未保存手动 IP")
    elif not confirmed["autoAssign"]:
        raise ControllerError("控制器未恢复自动分配 IP")
    return confirmed


def set_ip(member_id, value):
    with MUTATION_LOCK:
        return _set_ip_locked(member_id, value)


def _kick_locked(member_id):
    member_id = _validate_member_id(member_id)
    controller_request("DELETE", _member_path(member_id))
    revisions = controller_request("GET", _member_path())
    if not isinstance(revisions, dict):
        raise ControllerError("控制器成员列表格式无效")
    if member_id in {value.lower() for value in revisions}:
        raise ControllerError("控制器未删除该设备")


def kick(member_id):
    with MUTATION_LOCK:
        return _kick_locked(member_id)


PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>wudi-net 授权台</title>
<style>
body{font-family:-apple-system,sans-serif;background:#111827;color:#e5e7eb;max-width:760px;margin:40px auto;padding:0 16px}h1{font-size:20px;color:#60a5fa}.card{background:#1f2937;border-radius:12px;padding:16px;margin:10px 0;display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:10px}.dot{width:10px;height:10px;border-radius:50%}.on{background:#34d399}.off{background:#f87171}.mono{font-family:monospace;color:#93c5fd;font-size:14px}.meta{color:#9ca3af;font-size:12px}button{border:0;border-radius:8px;padding:8px 12px;font-size:13px;cursor:pointer}.b-on{background:#059669;color:#fff}.b-off{background:#7f1d1d;color:#fecaca}.b-kick{background:#374151;color:#fca5a5}.fields{grid-column:2/4;display:flex;gap:8px;flex-wrap:wrap}input{background:#111827;border:1px solid #374151;color:#e5e7eb;border-radius:8px;padding:7px 10px;font-size:13px;width:130px}.new{background:#1f2937;border-radius:12px;padding:16px;margin:10px 0;border:1px dashed #374151}.error{background:#7f1d1d;color:#fecaca;padding:10px;border-radius:8px;margin:10px 0}.hint{color:#9ca3af;font-size:12px}
</style></head><body><h1>🌐 wudi-net 设备授权台</h1><div id="error"></div><div id="app">加载中…</div><div class="new">➕ 新设备：<span class="mono">${NWID}</span>（加入后将在列表出现）</div>
<script>
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));let busy=false,mutationError='';
function error(message=''){document.getElementById('error').innerHTML=message?`<div class="error">${esc(message)}</div>`:''}
async function api(url,options){const response=await fetch(url,options);let data={};try{data=await response.json()}catch(_e){}if(!response.ok)throw new Error(data.error||`请求失败 (${response.status})`);return data}
async function load(force=false){if(busy||(!force&&document.activeElement&&document.activeElement.matches('#app input')))return;busy=true;try{const ms=await api('/api/members');document.getElementById('app').innerHTML=ms.map(m=>`<div class="card"><span class="dot ${m.authorized?'on':'off'}"></span><div><span class="mono">${esc(m.id)}</span><div class="meta">${m.autoAssign?'自动分配':'手动 IP'}</div></div><div><button class="${m.authorized?'b-off':'b-on'}" onclick="toggle('${m.id}',${!m.authorized})">${m.authorized?'撤销授权':'授权'}</button> <button class="b-kick" onclick="removeMember('${m.id}')">踢出</button></div><div class="fields"><input value="${esc(m.name)}" placeholder="备注名" onchange="renameMember('${m.id}',this.value)"><input value="${esc(m.ip)}" placeholder="IPv4（留空自动）" onkeydown="if(event.key==='Enter')saveIp('${m.id}',this.value)"><button onclick="saveIp('${m.id}',this.previousElementSibling.value)">保存 IP</button></div></div>`).join('')||'<p>无设备</p>';if(!mutationError)error()}catch(e){error(e.message)}finally{busy=false}}
async function act(fn){if(busy)return;busy=true;let succeeded=false;try{await fn();mutationError='';error();succeeded=true}catch(e){mutationError=e.message;error(mutationError)}finally{busy=false}if(succeeded)await load(true)}
function toggle(id,val){act(()=>api(`/api/members/${id}/auth`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({authorized:val})}))}
function saveIp(id,ip){act(()=>api(`/api/members/${id}/ip`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip})}))}
function renameMember(id,name){act(()=>api(`/api/members/${id}/name`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})}))}
function removeMember(id){if(confirm(`确定踢出 ${id}？`))act(()=>api(`/api/members/${id}`,{method:'DELETE'}))}
load(true);setInterval(load,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("无效的 Content-Length") from exc
        if length <= 0 or length > MAX_BODY:
            raise ValueError("请求内容为空或过大")
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("请求 JSON 无效") from exc
        if not isinstance(data, dict):
            raise ValueError("请求 JSON 必须是对象")
        return data

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/members":
            try:
                return self._json(200, list_members())
            except ControllerError as exc:
                return self._json(502, {"error": str(exc)})
        if path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
        return self._json(404, {"error": "接口不存在"})

    def do_POST(self):
        path = urlparse(self.path).path
        match = re.fullmatch(r"/api/members/([^/]+)/(auth|ip|name)", path)
        if not match:
            return self._json(404, {"error": "接口不存在"})
        member_id, action = match.groups()
        try:
            data = self._read_json()
            if action == "auth":
                result = set_auth(member_id, data.get("authorized"))
            elif action == "ip":
                result = set_ip(member_id, data.get("ip"))
            else:
                _validate_member_id(member_id)
                name = data.get("name")
                if not isinstance(name, str) or len(name) > 100:
                    raise ValueError("备注名无效")
                KNOWN_NAMES[member_id.lower()] = name.strip()
                save_names()
                result = {"ok": True}
            return self._json(200, result)
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except ControllerError as exc:
            return self._json(502, {"error": str(exc)})
        except OSError:
            return self._json(500, {"error": "保存备注失败"})

    def do_DELETE(self):
        match = re.fullmatch(r"/api/members/([^/]+)", urlparse(self.path).path)
        if not match:
            return self._json(404, {"error": "接口不存在"})
        try:
            kick(match.group(1))
            return self._json(200, {"ok": True})
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except ControllerError as exc:
            return self._json(502, {"error": str(exc)})

    def log_message(self, *_args):
        pass


def main():
    load_names()
    ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
