# -*- encoding: utf-8 -*-
"""
通用 CDP(Chrome DevTools Protocol)客户端 —— 安卓 Chrome H5 性能采集底座。

流程: adb 发现 devtools socket -> adb forward 到本机端口 -> HTTP /json 列 tab
      -> websocket 连上目标 tab -> 收发 CDP 命令/事件。

注意:新版 Chrome 会因 Origin 头拒绝 ws 握手(403),create_connection 必须
suppress_origin=True 不发 Origin 头。Chrome 的 socket 名固定为 chrome_devtools_remote。
"""
import json
import time

import requests
import websocket  # websocket-client
from loguru import logger

from magnax.public.adb import adb


class CDPError(Exception):
    """CDP 通信异常"""
    pass


class CDPClient(object):
    DEFAULT_SOCKET = 'chrome_devtools_remote'

    def __init__(self, device_id, local_port=9333, socket_name=None):
        self.device_id = device_id
        self.local_port = local_port
        self.socket_name = socket_name or self.DEFAULT_SOCKET
        self.ws = None
        self._id = 0
        self._event_buf = []

    # ---------- socket 发现 & forward ----------
    @staticmethod
    def list_sockets(device_id):
        """列出设备上所有 devtools_remote socket 名(Chrome + 各 WebView)"""
        out = adb.shell('cat /proc/net/unix', device_id)
        names = set()
        for line in out.splitlines():
            if 'devtools_remote' in line:
                idx = line.find('@')
                if idx >= 0:
                    names.add(line[idx + 1:].strip())
        return sorted(names)

    @staticmethod
    def list_targets(device_id):
        """列出可调试目标:Chrome + 各 App 的 WebView(解析 pid->包名,给出友好标签)。
        返回 [{'socket','type','pkg','label'}],供前端选择'调试目标'。"""
        socks = CDPClient.list_sockets(device_id)
        # 一次 ps 建 pid->进程名(=包名) 映射,用于把 webview_devtools_remote_<pid> 解析成 App
        pidmap = {}
        try:
            out = adb.shell('ps -A', device_id)
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    pidmap[parts[1]] = parts[-1]
        except Exception:
            pass
        targets = []
        for s in socks:
            if s.startswith('webview_devtools_remote_'):
                pid = s.rsplit('_', 1)[-1]
                pkg = pidmap.get(pid, '')
                targets.append({'socket': s, 'type': 'webview', 'pkg': pkg,
                                'label': f'WebView: {pkg or ("pid " + pid)}'})
            elif 'chrome_devtools_remote' in s:
                targets.append({'socket': s, 'type': 'chrome', 'pkg': 'com.android.chrome',
                                'label': 'Chrome'})
            else:
                targets.append({'socket': s, 'type': 'other', 'pkg': '', 'label': s})
        # Chrome 排前面
        targets.sort(key=lambda t: 0 if t['type'] == 'chrome' else 1)
        return targets

    def _forward(self):
        adb.forward_remove(self.local_port, self.device_id)
        adb.forward(self.local_port, f'localabstract:{self.socket_name}', self.device_id)

    def list_pages(self):
        """forward 后通过 HTTP /json 列出可调试页面 tab"""
        self._forward()
        try:
            resp = requests.get(f'http://127.0.0.1:{self.local_port}/json', timeout=8)
            pages = resp.json()
        except Exception as e:
            raise CDPError(f'读取 /json 失败(确认 Chrome 已打开页面): {e}')
        return [p for p in pages if p.get('type') == 'page' and p.get('webSocketDebuggerUrl')]

    # ---------- websocket ----------
    def connect(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=20, suppress_origin=True)

    def _recv(self, timeout):
        self.ws.settimeout(timeout)
        return json.loads(self.ws.recv())

    def call(self, method, params=None, timeout=20):
        """发一条 CDP 命令,等待同 id 的应答;过程中的事件缓存到 _event_buf"""
        self._id += 1
        mid = self._id
        self.ws.send(json.dumps({'id': mid, 'method': method, 'params': params or {}}))
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = self._recv(max(0.1, end - time.time()))
            except Exception:
                break
            if msg.get('id') == mid:
                if 'error' in msg:
                    raise CDPError(f"{method}: {msg['error']}")
                return msg.get('result', {})
            if 'method' in msg:
                self._event_buf.append(msg)
        raise CDPError(f'{method} 超时')

    def wait_event(self, method, timeout=25):
        """等待某个 CDP 事件(先查缓存,再读新消息)"""
        for i, m in enumerate(self._event_buf):
            if m.get('method') == method:
                return self._event_buf.pop(i)
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = self._recv(max(0.1, end - time.time()))
            except Exception:
                break
            if msg.get('method') == method:
                return msg
        return None

    def drain_until(self, stop_method, timeout=25, extra_wait=1.0):
        """持续读消息直到收到 stop_method 事件(或超时),返回期间所有事件。
        用于 reload 时批量抓 Network.* 事件做瀑布流。extra_wait 为收到停止事件后
        再多收一会儿,捕获晚到的 loadingFinished。"""
        events = list(self._event_buf)
        self._event_buf = []
        end = time.time() + timeout
        stopped = False
        while time.time() < end:
            try:
                msg = self._recv(max(0.1, end - time.time()))
            except Exception:
                break
            if 'method' in msg:
                events.append(msg)
                if msg['method'] == stop_method:
                    stopped = True
                    break
        if stopped and extra_wait:
            grace = time.time() + extra_wait
            while time.time() < grace:
                try:
                    msg = self._recv(max(0.1, grace - time.time()))
                except Exception:
                    break
                if 'method' in msg:
                    events.append(msg)
        return events

    def drain_duration(self, duration):
        """固定时长内收集所有事件并返回。比 drain_until 更适合 SPA/游戏
        (素材常在 loadEventFired 之后才下载)。"""
        events = list(self._event_buf)
        self._event_buf = []
        end = time.time() + duration
        while time.time() < end:
            try:
                msg = self._recv(max(0.1, end - time.time()))
            except Exception:
                break
            if 'method' in msg:
                events.append(msg)
        return events

    def evaluate(self, expression, return_by_value=True):
        """在页面上下文执行 JS 并取返回值"""
        r = self.call('Runtime.evaluate', {
            'expression': expression,
            'returnByValue': return_by_value,
        })
        return r.get('result', {}).get('value')

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None
