# -*- encoding: utf-8 -*-
"""
H5 性能采集 —— 安卓真机 Chrome,基于 CDP。

口径(MVP):白屏 = FP(first-paint),首屏 = LCP(largest-contentful-paint)。
- 加载类(collectLoad):reload 一次取 TTFB/FP/FCP/DCL/Load/LCP/CLS,一次性"成绩单"。
- 运行时(collectRuntime):不 reload,持续轮询 JS堆/页面FPS/DOM节点/长任务,做时序图。

Web Vitals(LCP/CLS/长任务)与页面 FPS 通过 PerformanceObserver / rAF 注入页面采集,
注入发生在 CDP 协议层,不改 H5 源码。注入脚本持续运行在页面里,断开连接后依然有效,
因此运行时轮询可"每次重连"而不丢 FPS。
"""
import os
import json
import datetime

from loguru import logger

from magnax.public.cdp_client import CDPClient, CDPError
from magnax.public.common import File, Platform

f = File()

# 持续注入脚本:LCP/CLS/长任务 Observer + rAF 帧率计数。幂等(已注入则跳过)。
INJECT_JS = r'''(function(){
  if (window.__h5_inited) return;
  window.__h5_inited = true;
  window.__h5lcp = 0; window.__h5cls = 0; window.__h5longtask = 0; window.__h5fps = 0;
  try {
    new PerformanceObserver(function(l){
      var es = l.getEntries(); var e = es[es.length-1];
      window.__h5lcp = Math.round(e.renderTime || e.loadTime || e.startTime);
    }).observe({type:'largest-contentful-paint', buffered:true});
    new PerformanceObserver(function(l){
      for (var e of l.getEntries()) { if (!e.hadRecentInput) window.__h5cls += e.value; }
    }).observe({type:'layout-shift', buffered:true});
    new PerformanceObserver(function(l){
      window.__h5longtask += l.getEntries().length;
    }).observe({type:'longtask', buffered:true});
  } catch (e) {}
  var frames = 0, last = performance.now();
  function loop(now){
    frames++;
    if (now - last >= 1000){ window.__h5fps = Math.round(frames*1000/(now-last)); frames = 0; last = now; }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})()'''

# 读加载类指标
LOAD_JS = r'''(function(){
  var nav = performance.getEntriesByType('navigation')[0] || {};
  var paint = {}; performance.getEntriesByType('paint').forEach(function(p){paint[p.name]=p.startTime;});
  return JSON.stringify({
    ttfb: Math.max(0, Math.round((nav.responseStart||0) - (nav.requestStart||0))),
    dcl:  Math.max(0, Math.round((nav.domContentLoadedEventEnd||0) - (nav.startTime||0))),
    load: Math.max(0, Math.round((nav.loadEventEnd||0) - (nav.startTime||0))),
    fp:   paint['first-paint'] ? Math.round(paint['first-paint']) : 0,
    fcp:  paint['first-contentful-paint'] ? Math.round(paint['first-contentful-paint']) : 0,
    lcp:  Math.round(window.__h5lcp || 0),
    cls:  Number((window.__h5cls || 0).toFixed(4))
  });
})()'''

# 读运行时指标
RUNTIME_JS = r'''(function(){
  return JSON.stringify({
    fps: Math.round(window.__h5fps || 0),
    cls: Number((window.__h5cls || 0).toFixed(4)),
    longtask: window.__h5longtask || 0
  });
})()'''


class H5PerformanceMonitor(object):
    """H5 性能采集。每次采集独立重连 CDP(与 iOS 方案一致,避免长连接泄漏)。"""

    def __init__(self, deviceId, url=None, wsUrl=None, noLog=True, local_port=9333):
        self.deviceId = deviceId
        self.url = url
        self.wsUrl = wsUrl
        self.noLog = noLog
        self.client = CDPClient(deviceId, local_port=local_port)

    def _pick_ws(self):
        if self.wsUrl:
            # 直接给了 ws 地址时,仍需确保 adb forward 隧道在(否则 127.0.0.1:port 连不上)
            self.client._forward()
            return self.wsUrl
        pages = self.client.list_pages()
        if not pages:
            raise CDPError('没有可调试的页面(确认 Chrome 已打开 H5、非无痕模式)')
        if self.url:
            p = next((x for x in pages if self.url in x.get('url', '')), None)
            if p:
                return p['webSocketDebuggerUrl']
        p = next((x for x in pages if x.get('url', '').startswith('http')), pages[0])
        return p['webSocketDebuggerUrl']

    def _metrics(self):
        """CDP Performance 域取 JS堆/DOM节点(不依赖页面 flag)"""
        self.client.call('Performance.enable')
        ms = {m['name']: m['value'] for m in self.client.call('Performance.getMetrics').get('metrics', [])}
        heap = round(ms.get('JSHeapUsedSize', 0) / 1024 / 1024, 2)
        nodes = int(ms.get('Nodes', 0))
        return heap, nodes

    def collectLoad(self, do_reload=True):
        """reload 取一次完整加载指标(白屏/首屏/FCP/LCP/...)"""
        self.client.connect(self._pick_ws())
        try:
            self.client.call('Page.enable')
            self.client.call('Runtime.enable')
            # 注册到后续每次新文档(reload 后仍生效)
            self.client.call('Page.addScriptToEvaluateOnNewDocument', {'source': INJECT_JS})
            if do_reload:
                self.client.call('Page.reload', {'ignoreCache': True})
                self.client.wait_event('Page.loadEventFired', timeout=25)
                import time as _t
                _t.sleep(1.5)  # 等 LCP 收敛
            else:
                self.client.evaluate(INJECT_JS)
            data = json.loads(self.client.evaluate(LOAD_JS))
            data['heap'], data['nodes'] = self._metrics()
            if not self.noLog:
                self._log_load(data)
            return data
        finally:
            self.client.close()

    def collectRuntime(self):
        """不 reload,取一次运行时快照(JS堆/页面FPS/DOM节点/长任务)"""
        self.client.connect(self._pick_ws())
        try:
            self.client.call('Runtime.enable')
            self.client.evaluate(INJECT_JS)  # 幂等:确保 FPS/Observer 已注入
            data = json.loads(self.client.evaluate(RUNTIME_JS))
            data['heap'], data['nodes'] = self._metrics()
            if not self.noLog:
                self._log_runtime(data)
            return data
        finally:
            self.client.close()

    def collectWaterfall(self, do_reload=True, capture_seconds=6):
        """reload 抓资源瀑布流(每个资源 url/类型/状态/起止/耗时/大小)。固定窗口采集
        capture_seconds 秒,兼顾传统页面与 SPA(素材在 load 后下载)。
        注意:canvas 游戏(如 Egret)不暴露标准资源加载,瀑布流会是空的。"""
        self.client.connect(self._pick_ws())
        try:
            self.client.call('Page.enable')
            self.client.call('Network.enable')
            if do_reload:
                self.client.call('Page.reload', {'ignoreCache': True})
                events = self.client.drain_duration(capture_seconds)
            else:
                events = []
            resources = self._build_waterfall(events)
            return {'resources': resources, 'total': len(resources)}
        finally:
            self.client.close()

    def collectScreenshot(self):
        """截当前屏(不 reload,快且稳),返回 jpeg base64。
        不调 Page.enable —— 截图不需要它,且它会引发事件洪流干扰应答匹配。"""
        self.client.connect(self._pick_ws())
        try:
            r = self.client.call('Page.captureScreenshot',
                                 {'format': 'jpeg', 'quality': 60, 'fromSurface': True},
                                 timeout=20)
            return {'screenshot': r.get('data', '')}
        finally:
            self.client.close()

    @staticmethod
    def _build_waterfall(events):
        """把 Network.* 事件聚合成按请求的资源列表"""
        reqs = {}
        t0 = None
        for ev in events:
            m = ev.get('method')
            p = ev.get('params', {})
            rid = p.get('requestId')
            if m == 'Network.requestWillBeSent':
                ts = p.get('timestamp', 0)
                if t0 is None:
                    t0 = ts
                req = p.get('request', {})
                reqs[rid] = {
                    'url': req.get('url', ''),
                    'type': p.get('type', 'Other'),
                    'start': ts, 'end': ts, 'status': 0, 'size': 0, 'failed': False,
                }
            elif m == 'Network.responseReceived' and rid in reqs:
                resp = p.get('response', {})
                reqs[rid]['status'] = resp.get('status', 0)
                reqs[rid]['type'] = p.get('type', reqs[rid]['type'])
            elif m == 'Network.loadingFinished' and rid in reqs:
                reqs[rid]['end'] = p.get('timestamp', reqs[rid]['end'])
                reqs[rid]['size'] = int(p.get('encodedDataLength', 0) or 0)
            elif m == 'Network.loadingFailed' and rid in reqs:
                reqs[rid]['end'] = p.get('timestamp', reqs[rid]['end'])
                reqs[rid]['failed'] = True
        out = []
        if t0 is None:
            t0 = 0
        for r in reqs.values():
            start_ms = round((r['start'] - t0) * 1000, 1)
            dur_ms = round((r['end'] - r['start']) * 1000, 1)
            out.append({
                'url': r['url'][:160], 'type': r['type'], 'status': r['status'],
                'start': max(0, start_ms), 'duration': max(0, dur_ms),
                'size': round(r['size'] / 1024, 2), 'failed': r['failed'],
            })
        out.sort(key=lambda x: x['start'])
        return out

    def collectHost(self, pkgname):
        """采宿主进程原生指标(CPU/GPU/温度)并落 h5_host_*.log,用于发热归因报告。
        用 noLog=True 抑制原生类自身写 cpu_app.log 等(避免与原生报告日志冲突)。"""
        from magnax.public.apm import CPU, GPU, Battery
        appCpu = sysCpu = gpuVal = temp = 0
        try:
            appCpu, sysCpu = CPU(pkgName=pkgname, deviceId=self.deviceId,
                                 platform=Platform.Android).getCpuRate(noLog=True)
        except Exception as e:
            logger.warning(f'[H5] 宿主 CPU 采集失败: {e}')
        try:
            gpuVal = GPU(pkgName=pkgname, deviceId=self.deviceId,
                         platform=Platform.Android).getGPU(noLog=True)
        except Exception as e:
            logger.warning(f'[H5] 宿主 GPU 采集失败: {e}')
        try:
            final = Battery(deviceId=self.deviceId, platform=Platform.Android).getBattery(noLog=True)
            temp = final[1] if final and len(final) > 1 else 0
        except Exception as e:
            logger.warning(f'[H5] 设备温度采集失败: {e}')
        if not self.noLog:
            t = self._now()
            f.add_log(os.path.join(f.report_dir, 'h5_host_cpu_app.log'), t, appCpu)
            f.add_log(os.path.join(f.report_dir, 'h5_host_cpu_sys.log'), t, sysCpu)
            f.add_log(os.path.join(f.report_dir, 'h5_host_gpu.log'), t, gpuVal)
            f.add_log(os.path.join(f.report_dir, 'h5_host_temp.log'), t, temp)
        return {'appCpuRate': appCpu, 'systemCpuRate': sysCpu, 'gpu': gpuVal, 'temperature': temp}

    # ---------- 落日志(复用 File.add_log,格式 time=value) ----------
    def _now(self):
        return datetime.datetime.now().strftime('%H:%M:%S.%f')

    def _log_load(self, data):
        t = self._now()
        for name, key in [('h5_ttfb', 'ttfb'), ('h5_fp', 'fp'), ('h5_fcp', 'fcp'),
                          ('h5_lcp', 'lcp'), ('h5_dcl', 'dcl'), ('h5_load', 'load')]:
            f.add_log(os.path.join(f.report_dir, f'{name}.log'), t, data.get(key, 0))

    def _log_runtime(self, data):
        t = self._now()
        f.add_log(os.path.join(f.report_dir, 'h5_pagefps.log'), t, data.get('fps', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_heap.log'), t, data.get('heap', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_nodes.log'), t, data.get('nodes', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_longtask.log'), t, data.get('longtask', 0))
