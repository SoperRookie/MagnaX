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
import re
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
  window.__h5inp = 0; window.__h5tbt = 0; window.__h5lt = []; window.__h5ltspans = [];
  try {
    new PerformanceObserver(function(l){
      var es = l.getEntries(); var e = es[es.length-1];
      window.__h5lcp = Math.round(e.renderTime || e.loadTime || e.startTime);
    }).observe({type:'largest-contentful-paint', buffered:true});
    new PerformanceObserver(function(l){
      for (var e of l.getEntries()) { if (!e.hadRecentInput) window.__h5cls += e.value; }
    }).observe({type:'layout-shift', buffered:true});
    new PerformanceObserver(function(l){
      for (var e of l.getEntries()){
        window.__h5longtask += 1;
        window.__h5tbt += Math.max(0, e.duration - 50);  // TBT:超过50ms的阻塞部分累加
        var a = (e.attribution && e.attribution[0]) || {};
        window.__h5lt.push({dur: Math.round(e.duration), at: (a.name || a.containerName || a.containerType || 'self')});
        if (window.__h5lt.length > 30) window.__h5lt.shift();
        window.__h5ltspans.push([Math.round(e.startTime), Math.round(e.startTime + e.duration)]);  // 供TTI计算
      }
    }).observe({type:'longtask', buffered:true});
    // INP/FID:交互响应延迟,取最大(近似 INP)
    new PerformanceObserver(function(l){
      for (var e of l.getEntries()){ var d = Math.round(e.duration); if (d > window.__h5inp) window.__h5inp = d; }
    }).observe({type:'event', durationThreshold:16, buffered:true});
    new PerformanceObserver(function(l){
      for (var e of l.getEntries()){ var d = Math.round(e.processingStart - e.startTime); if (d > window.__h5inp) window.__h5inp = d; }
    }).observe({type:'first-input', buffered:true});
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
  var fcp = paint['first-contentful-paint'] || 0;
  // TTI 近似:FCP 之后,找第一个 5s 内无长任务的安静窗口,TTI=该窗口前最后一个长任务结束(无则 FCP)
  var spans = (window.__h5ltspans || []).filter(function(s){ return s[1] > fcp; }).sort(function(a,b){return a[0]-b[0];});
  var tti = fcp;
  for (var i=0;i<spans.length;i++){
    tti = spans[i][1];
    var nextStart = (i+1<spans.length) ? spans[i+1][0] : Infinity;
    if (nextStart - spans[i][1] >= 5000) break;
  }
  return JSON.stringify({
    ttfb: Math.max(0, Math.round((nav.responseStart||0) - (nav.requestStart||0))),
    dcl:  Math.max(0, Math.round((nav.domContentLoadedEventEnd||0) - (nav.startTime||0))),
    load: Math.max(0, Math.round((nav.loadEventEnd||0) - (nav.startTime||0))),
    fp:   paint['first-paint'] ? Math.round(paint['first-paint']) : 0,
    fcp:  Math.round(fcp),
    lcp:  Math.round(window.__h5lcp || 0),
    cls:  Number((window.__h5cls || 0).toFixed(4)),
    tbt:  Math.round(window.__h5tbt || 0),
    tti:  Math.round(tti)
  });
})()'''

# 读运行时指标
RUNTIME_JS = r'''(function(){
  return JSON.stringify({
    fps: Math.round(window.__h5fps || 0),
    cls: Number((window.__h5cls || 0).toFixed(4)),
    longtask: window.__h5longtask || 0,
    inp: Math.round(window.__h5inp || 0),
    lt: (window.__h5lt || []).slice(-10)
  });
})()'''


class H5PerformanceMonitor(object):
    """H5 性能采集。每次采集独立重连 CDP(与 iOS 方案一致,避免长连接泄漏)。"""

    def __init__(self, deviceId, url=None, wsUrl=None, noLog=True, local_port=9333, socket=None):
        self.deviceId = deviceId
        self.url = url
        self.wsUrl = wsUrl
        self.noLog = noLog
        # socket 指定调试目标(Chrome=chrome_devtools_remote 或 App 的 webview_devtools_remote_<pid>);
        # forward 用它,这样选 WebView 时隧道指向对的 socket
        self.client = CDPClient(deviceId, local_port=local_port, socket_name=socket)

    def _pick_ws(self):
        if self.wsUrl:
            # 直接给了 ws 地址时,仍需确保 adb forward 隧道在(否则 127.0.0.1:port 连不上)
            self.client._forward()
            # 把 ws 里的端口改成本实例的转发端口,隔离不同采集器(运行时9333/剖析9334),
            # 避免并发时共用端口互相 remove forward 打断对方
            return re.sub(r'(://[^:/]+:)\d+', lambda m: m.group(1) + str(self.client.local_port),
                          self.wsUrl, count=1)
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
        """CDP Performance 域取一组指标(对标 Chrome Performance Monitor,不依赖页面 flag):
        JS堆/DOM节点/事件监听器数/累计布局数/累计样式重算数。
        layout/recalc 是累计值,前端按相邻差算成'每秒'。"""
        self.client.call('Performance.enable')
        ms = {m['name']: m['value'] for m in self.client.call('Performance.getMetrics').get('metrics', [])}
        return {
            'heap': round(ms.get('JSHeapUsedSize', 0) / 1024 / 1024, 2),
            'nodes': int(ms.get('Nodes', 0)),
            'listeners': int(ms.get('JSEventListeners', 0)),
            'layoutCount': int(ms.get('LayoutCount', 0)),
            'recalcCount': int(ms.get('RecalcStyleCount', 0)),
            'documents': int(ms.get('Documents', 0)),
            'frames': int(ms.get('Frames', 0)),
        }

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
            m = self._metrics()
            data['heap'] = m['heap']; data['nodes'] = m['nodes']
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
            data.update(self._metrics())  # heap/nodes/listeners/layoutCount/recalcCount
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
                # 不 reload:抓本窗口内"当前正在加载"的网络活动(实时模式,不打断页面)
                events = self.client.drain_duration(capture_seconds)
            resources = self._build_waterfall(events)
            # 落盘最近一次瀑布流,保存报告时归档(make_report 搬 .json),供报告页展示
            try:
                with open(os.path.join(f.report_dir, 'h5_waterfall.json'), 'w', encoding='utf-8') as fp:
                    json.dump({'resources': resources}, fp)
            except Exception as e:
                logger.warning(f'[H5] 瀑布流落盘失败: {e}')
            return {'resources': resources, 'total': len(resources)}
        finally:
            self.client.close()

    def collectProfile(self, seconds=5):
        """CPU 剖析 seconds 秒,聚合每个函数的 self-time,返回 Top 热点函数。
        直接回答'哪段 JS 在烧 CPU/发热'。需页面在剖析期间正常运行(游戏渲染中)。"""
        self.client.connect(self._pick_ws())
        try:
            self.client.call('Profiler.enable')
            self.client.call('Profiler.setSamplingInterval', {'interval': 1000})  # 1ms/样本
            self.client.call('Profiler.start')
            import time as _t
            _t.sleep(max(1, min(int(seconds), 30)))
            r = self.client.call('Profiler.stop', timeout=40)
            top = self._top_functions(r.get('profile', {}))
            # 落盘最近一次剖析结果,保存报告时归档(make_report 会搬 .json),供报告页展示热点表
            try:
                with open(os.path.join(f.report_dir, 'h5_profile.json'), 'w', encoding='utf-8') as fp:
                    json.dump({'top': top}, fp)
            except Exception as e:
                logger.warning(f'[H5] 剖析结果落盘失败: {e}')
            return {'top': top}
        finally:
            self.client.close()

    @staticmethod
    def _top_functions(profile, top_n=20):
        """从 CPU profile 聚合 self-time(hitCount)到函数级,返回 Top N。
        采样间隔 1ms,故 hitCount≈自耗时(ms);selfPercent 为占总采样比。"""
        nodes = profile.get('nodes', []) or []
        total = sum(n.get('hitCount', 0) for n in nodes) or 1
        agg = {}
        for n in nodes:
            hits = n.get('hitCount', 0)
            if hits <= 0:
                continue
            cf = n.get('callFrame', {})
            name = cf.get('functionName') or '(anonymous)'
            url = cf.get('url', '') or ''
            line = cf.get('lineNumber', -1)
            key = (name, url, line)
            agg[key] = agg.get(key, 0) + hits
        items = [{
            'function': name,
            'url': (url.split('/')[-1] if url else '(native)'),
            'line': (line + 1) if line >= 0 else 0,
            'selfPercent': round(h * 100.0 / total, 1),
            'selfMs': h,
        } for (name, url, line), h in agg.items()]
        items.sort(key=lambda x: x['selfMs'], reverse=True)
        return items[:top_n]

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
                reqs[rid]['timing'] = resp.get('timing') or {}  # 阶段耗时(DNS/连接/TLS/TTFB)
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
            # 阶段耗时(DNS/连接/TLS/TTFB/下载),来自 ResourceTiming(偏移量,-1=不适用)
            tm = r.get('timing') or {}

            def _ph(a, b):
                sa, sb = tm.get(a, -1), tm.get(b, -1)
                return round(sb - sa, 1) if (sa is not None and sb is not None and sa >= 0 and sb >= sa) else 0
            rhe = tm.get('receiveHeadersEnd', -1)
            download = round(max(0, dur_ms - rhe), 1) if (rhe is not None and rhe >= 0) else 0
            out.append({
                'url': r['url'][:160], 'type': r['type'], 'status': r['status'],
                'start': max(0, start_ms), 'duration': max(0, dur_ms),
                'size': round(r['size'] / 1024, 2), 'failed': r['failed'],
                'dns': _ph('dnsStart', 'dnsEnd'), 'connect': _ph('connectStart', 'connectEnd'),
                'tls': _ph('sslStart', 'sslEnd'), 'ttfb': _ph('sendEnd', 'receiveHeadersEnd'),
                'download': download,
            })
        out.sort(key=lambda x: x['start'])
        return out

    def collectHost(self, pkgname):
        """采宿主进程原生指标(CPU/GPU/温度)并落 h5_host_*.log,用于发热归因报告。
        用 noLog=True 抑制原生类自身写 cpu_app.log 等(避免与原生报告日志冲突)。"""
        from magnax.public.apm import CPU, GPU, Battery, ThermalSensor
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
            # 优先表层温度(机身外壳/skin,最贴手感),取不到再退回电池温度
            temp = ThermalSensor(self.deviceId).getSurfaceTemp()
            if temp is None:
                final = Battery(deviceId=self.deviceId, platform=Platform.Android).getBattery(noLog=True)
                temp = final[1] if final and len(final) > 1 else 0
        except Exception as e:
            logger.warning(f'[H5] 温度采集失败: {e}')
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
                          ('h5_lcp', 'lcp'), ('h5_dcl', 'dcl'), ('h5_load', 'load'),
                          ('h5_tbt', 'tbt'), ('h5_tti', 'tti')]:
            f.add_log(os.path.join(f.report_dir, f'{name}.log'), t, data.get(key, 0))

    def _log_runtime(self, data):
        t = self._now()
        f.add_log(os.path.join(f.report_dir, 'h5_pagefps.log'), t, data.get('fps', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_heap.log'), t, data.get('heap', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_nodes.log'), t, data.get('nodes', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_longtask.log'), t, data.get('longtask', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_listeners.log'), t, data.get('listeners', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_layout.log'), t, data.get('layoutCount', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_recalc.log'), t, data.get('recalcCount', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_inp.log'), t, data.get('inp', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_documents.log'), t, data.get('documents', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_frames.log'), t, data.get('frames', 0))
        # 持续刷新最近长任务明细到 json,供报告页归因表(item5);非时序,故单独存
        try:
            lt = data.get('lt') or []
            if lt:
                with open(os.path.join(f.report_dir, 'h5_longtasks.json'), 'w', encoding='utf-8') as fp_:
                    json.dump({'lt': lt}, fp_)
        except Exception:
            pass
