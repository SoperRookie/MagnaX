# -*- encoding: utf-8 -*-
"""
iOS H5 性能采集 —— iOS 真机 Safari / WKWebView,基于 WebKit Inspector Protocol。

对标安卓 h5_perf.py:方法签名/落盘文件名保持一致,好让报告管线(_setH5Perfs / make_report)
无改动复用。差异只在传输层(ios_webinspector 而非 cdp_client)与 WebKit 能力边界。

口径(与安卓统一,差异处标注):
- 白屏 = FCP(WebKit 无 first-paint,故白屏取 FCP;字段名仍叫 fp 供报告复用)。
- 首屏 = LCP(iOS 26 WebKit 已支持 largest-contentful-paint)。
- 加载类(collectLoad):reload 一次取 TTFB/FCP/LCP/DCL/Load。
- 运行时(collectRuntime):不 reload,轮询 页面FPS/DOM节点/INP/(CLS/长任务若支持)。

WebKit 能力实测(iOS 26.5):✅ nav timing/FCP/LCP/INP(event)/FPS(rAF)/DOM节点;
❌ first-paint、CLS(layout-shift)、longtask、performance.memory(JS堆)。不支持的指标
用 PerformanceObserver 独立 try 包裹(某类型不支持不影响其余采集),缺的值不落盘 → 报告不显示。
JS 堆、瀑布流等走 WebKit 协议域补齐(见 collectHeap / collectWaterfall)。
"""
import os
import json
import datetime

from loguru import logger

from magnax.public.ios_webinspector import get_inspector, IOSInspectorError
from magnax.public.common import File

f = File()

# 持续注入脚本:各 Observer 独立 try(WebKit 某类型不支持时不连累其余);rAF 帧率在 try 外,
# 保证 FPS 一定采得到。幂等(已注入则跳过)。与安卓 INJECT_JS 同义,但对 WebKit 更防御。
INJECT_JS = r'''(function(){
  if (window.__h5_inited) return;
  window.__h5_inited = true;
  window.__h5lcp=0; window.__h5cls=0; window.__h5longtask=0; window.__h5fps=0;
  window.__h5inp=0; window.__h5tbt=0; window.__h5lt=[];
  // 权威能力判断:用 supportedEntryTypes(WebKit 对不支持的类型 observe() 不抛异常,
  // 会静默不触发,故不能用"observe 没抛=支持",否则 longtask/cls 假阳性)。
  var SET = (window.PerformanceObserver && PerformanceObserver.supportedEntryTypes) || [];
  window.__h5supp = {
    lcp: SET.indexOf('largest-contentful-paint') >= 0,
    cls: SET.indexOf('layout-shift') >= 0,
    longtask: SET.indexOf('longtask') >= 0,
    inp: SET.indexOf('event') >= 0 || SET.indexOf('first-input') >= 0
  };
  function obs(type, cb, opts){
    try { var o = opts || {}; o.type = type; o.buffered = true;
          new PerformanceObserver(cb).observe(o); return true; }
    catch (e) { return false; }
  }
  obs('largest-contentful-paint', function(l){
    var es=l.getEntries(); var e=es[es.length-1];
    window.__h5lcp = Math.round(e.renderTime || e.loadTime || e.startTime);
  });
  obs('layout-shift', function(l){
    for (var e of l.getEntries()){ if(!e.hadRecentInput) window.__h5cls += e.value; }
  });
  obs('longtask', function(l){
    for (var e of l.getEntries()){
      window.__h5longtask += 1; window.__h5tbt += Math.max(0, e.duration - 50);
      window.__h5lt.push({dur: Math.round(e.duration), at: 'self'});
      if (window.__h5lt.length > 30) window.__h5lt.shift();
    }
  });
  obs('event', function(l){
    for (var e of l.getEntries()){ var d=Math.round(e.duration); if(d>window.__h5inp) window.__h5inp=d; }
  }, {durationThreshold:16});
  obs('first-input', function(l){
    for (var e of l.getEntries()){ var d=Math.round(e.processingStart - e.startTime); if(d>window.__h5inp) window.__h5inp=d; }
  });
  var frames=0, last=performance.now();
  function loop(now){
    frames++;
    if (now - last >= 1000){ window.__h5fps = Math.round(frames*1000/(now-last)); frames=0; last=now; }
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);
})()'''

# 读加载类指标(白屏=FCP)
LOAD_JS = r'''(function(){
  var nav = performance.getEntriesByType('navigation')[0] || {};
  var paint = {}; performance.getEntriesByType('paint').forEach(function(p){paint[p.name]=p.startTime;});
  var fcp = paint['first-contentful-paint'] || 0;
  return JSON.stringify({
    ttfb: Math.max(0, Math.round((nav.responseStart||0) - (nav.requestStart||0))),
    dcl:  Math.max(0, Math.round((nav.domContentLoadedEventEnd||0) - (nav.startTime||0))),
    load: Math.max(0, Math.round((nav.loadEventEnd||0) - (nav.startTime||0))),
    fcp:  Math.round(fcp),
    lcp:  Math.round(window.__h5lcp || 0),
    cls:  Number((window.__h5cls || 0).toFixed(4)),
    nodes: document.getElementsByTagName('*').length,
    supp: window.__h5supp || {}
  });
})()'''

# 读运行时指标
RUNTIME_JS = r'''(function(){
  return JSON.stringify({
    fps: Math.round(window.__h5fps || 0),
    nodes: document.getElementsByTagName('*').length,
    inp: Math.round(window.__h5inp || 0),
    cls: Number((window.__h5cls || 0).toFixed(4)),
    longtask: window.__h5longtask || 0,
    lt: (window.__h5lt || []).slice(-10),
    supp: window.__h5supp || {}
  });
})()'''


class IOSH5PerformanceMonitor(object):
    """iOS H5 性能采集。传输层复用按 device 单例的持久 webinspector 连接。"""

    def __init__(self, deviceId, url=None, pageId=None, noLog=True):
        self.deviceId = deviceId
        self.url = url
        self.pageId = pageId
        self.noLog = noLog
        self.insp = get_inspector(deviceId)

    def _connect(self):
        """确保连到目标页面(按 url/pageId 选;已连同页则复用)。"""
        self.insp.connect_page(url=self.url, page_id=self.pageId)

    def _eval_json(self, js):
        raw = self.insp.evaluate(js)
        if raw is None:
            raise IOSInspectorError('evaluate 返回空(页面可能已关闭或隧道断)')
        return json.loads(raw)

    def collectLoad(self, do_reload=True):
        """reload 取一次完整加载指标(白屏=FCP/首屏=LCP/FCP/TTFB/DCL/Load)"""
        try:
            self._connect()
            self.insp.evaluate(INJECT_JS)         # 先注入(reload 前也注入,尽量赶上 LCP)
            if do_reload:
                self.insp.reload(ignore_cache=True)
                import time as _t
                _t.sleep(2.0)                     # 等 load + LCP 收敛
                self.insp.evaluate(INJECT_JS)     # reload 后页面是新文档,重新注入
                _t.sleep(0.5)
            data = self._eval_json(LOAD_JS)
            data['fp'] = data.get('fcp', 0)       # 白屏口径=FCP,复用报告的 fp 字段
            data['tbt'] = 0
            data['tti'] = 0
            if not self.noLog:
                self._log_load(data)
            return data
        finally:
            if do_reload:
                # reload 会污染 WebinspectorService 单例:旧 target 残留使之后的 connect/建 session/
                # evaluate 永久 hang(表现为"第一次采集成、之后全 25s 超时卡死")。
                # 本次 reload 采完即丢弃该 inspector,下一次 load/runtime 会用全新连接重建,保证可重复采集。
                from magnax.public.ios_webinspector import drop_inspector
                drop_inspector(self.deviceId)
                self.insp = None

    def collectRuntime(self):
        """不 reload,取一次运行时快照(页面FPS/DOM节点/INP/CLS/长任务)"""
        try:
            self._connect()
            self.insp.evaluate(INJECT_JS)         # 幂等:确保 FPS/Observer 已注入(不会重置 fps 计数)
            data = self._eval_json(RUNTIME_JS)
            data['heap'] = self._heap_mb()        # JS 堆走 WebKit Heap 域(页面拿不到 performance.memory)
            if not self.noLog:
                self._log_runtime(data)
            return data
        except Exception:
            # 运行时轮询若卡死(session 变坏 -> _lt.run 25s 超时)或异常,丢弃坏 inspector,
            # 让下一次轮询用全新连接自愈。否则一次卡死后每次轮询都 25s 超时返回空,
            # 前端 fps/nodes/inp 图表将永远收不到数据点。
            from magnax.public.ios_webinspector import drop_inspector
            drop_inspector(self.deviceId)
            self.insp = None
            raise

    def _heap_mb(self):
        """通过 WebKit Heap 域取 JS 堆大小(MB)。performance.memory 在 WebKit 不暴露给页面。
        阶段2 用 Heap 域实现(snapshot 的 totalSize 或增量估算);阶段1 先返回 0(不落盘)。"""
        return 0

    def collectHost(self, bundle):
        """采宿主 App(Safari=com.apple.mobilesafari 或自家 App bundle)的原生指标做发热归因。
        复用 iOS 原生 DVT 适配器(CPU/内存/GPU)+ 电池温度。落 h5_host_*.log,与安卓同名进报告。"""
        appCpu = sysCpu = mem = gpuVal = temp = 0
        try:
            adapter = _get_host_adapter(self.deviceId, bundle)
            appCpu, sysCpu = adapter.get_cpu()
            mem = adapter.get_memory()
            try:
                gpuVal = adapter.get_gpu()
            except Exception:
                gpuVal = 0
        except Exception as e:
            logger.warning(f'[iOS H5] 宿主原生采集失败: {e}')
        temp = self._ios_battery_temp()  # iOS 无表层温度传感器,用电池温度做发热代理
        if not self.noLog:
            t = self._now()
            f.add_log(os.path.join(f.report_dir, 'h5_host_cpu_app.log'), t, appCpu)
            f.add_log(os.path.join(f.report_dir, 'h5_host_cpu_sys.log'), t, sysCpu)
            f.add_log(os.path.join(f.report_dir, 'h5_host_gpu.log'), t, gpuVal)
            f.add_log(os.path.join(f.report_dir, 'h5_host_mem.log'), t, mem)
            f.add_log(os.path.join(f.report_dir, 'h5_host_temp.log'), t, temp)
        return {'appCpuRate': appCpu, 'systemCpuRate': sysCpu, 'gpu': gpuVal,
                'memory': mem, 'temperature': temp}

    def _ios_battery_temp(self):
        """iOS 电池温度(℃)做发热代理。DiagnosticsService.get_battery() 的 Temperature,
        不需隧道。iOS 无安卓那种表层/skin 温度传感器,电池温度是可得的最接近手感的信号。"""
        try:
            from magnax.public.apm import get_ios_lockdown_client
            from pymobiledevice3.services.diagnostics import DiagnosticsService
            lc = get_ios_lockdown_client(self.deviceId)
            if lc is None:
                return 0
            b = DiagnosticsService(lc).get_battery() or {}
            temp = b.get('Temperature', 0) or 0
            return round(temp / 100.0, 1) if temp > 100 else temp
        except Exception as e:
            logger.warning(f'[iOS H5] 电池温度采集失败: {e}')
            return 0

    def collectWaterfall(self, do_reload=True, capture_seconds=6, reset=False):
        """资源瀑布流(WebKit Network 域)。阶段2 实现,先返回空,保证前端不报错。"""
        return {'resources': [], 'total': 0}

    def collectProfile(self, seconds=5):
        """JS 热点剖析(WebKit ScriptProfiler 域)。阶段2 实现,先返回空。"""
        return {'top': []}

    def collectScreenshot(self):
        """截屏(WebKit Page.snapshotRect)。阶段2 实现,先返回空。"""
        return {'screenshot': ''}

    # ---------- 落日志(复用 File.add_log,格式 time=value;仅写 iOS 有效指标) ----------
    def _now(self):
        return datetime.datetime.now().strftime('%H:%M:%S.%f')

    def _log_load(self, data):
        t = self._now()
        # iOS 有效:ttfb/fp(=fcp)/fcp/lcp/dcl/load;CLS 仅在支持时写
        pairs = [('h5_ttfb', 'ttfb'), ('h5_fp', 'fp'), ('h5_fcp', 'fcp'),
                 ('h5_lcp', 'lcp'), ('h5_dcl', 'dcl'), ('h5_load', 'load')]
        for name, key in pairs:
            f.add_log(os.path.join(f.report_dir, f'{name}.log'), t, data.get(key, 0))

    def _log_runtime(self, data):
        t = self._now()
        supp = data.get('supp') or {}
        # 一定有:页面FPS、DOM节点、堆(可能0)
        f.add_log(os.path.join(f.report_dir, 'h5_pagefps.log'), t, data.get('fps', 0))
        f.add_log(os.path.join(f.report_dir, 'h5_nodes.log'), t, data.get('nodes', 0))
        if data.get('heap'):
            f.add_log(os.path.join(f.report_dir, 'h5_heap.log'), t, data.get('heap', 0))
        # 条件写(WebKit 支持才落盘,否则报告不显示该曲线,不误导为恒0)
        if supp.get('inp'):
            f.add_log(os.path.join(f.report_dir, 'h5_inp.log'), t, data.get('inp', 0))
        if supp.get('longtask'):
            f.add_log(os.path.join(f.report_dir, 'h5_longtask.log'), t, data.get('longtask', 0))
            lt = data.get('lt') or []
            if lt:
                try:
                    with open(os.path.join(f.report_dir, 'h5_longtasks.json'), 'w', encoding='utf-8') as fp_:
                        json.dump({'lt': lt}, fp_)
                except Exception:
                    pass


# 宿主原生适配器按 (device, bundle) 缓存,避免每次采集重建 DVT 连接(iOS DVT 建连较重)
_host_adapters = {}


def _get_host_adapter(device_id, bundle):
    from magnax.public.ios_perf_adapter import PyiOSDeviceAdapter
    key = (device_id, bundle)
    ad = _host_adapters.get(key)
    if ad is None:
        ad = PyiOSDeviceAdapter(device_id, bundle)
        _host_adapters[key] = ad
    return ad
