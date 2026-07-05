# -*- encoding: utf-8 -*-
"""
iOS WebKit Inspector 传输层 —— iOS Safari / WKWebView H5 性能采集底座。

对标安卓的 cdp_client.py:安卓走 CDP over adb,iOS 走 WebKit Inspector Protocol over
RSD/tunneld。底层直接复用 pymobiledevice3 自带的 WebinspectorService + InspectorSession,
无需外部 ios-webkit-debug-proxy 二进制。

pymobiledevice3 的 webinspector 是全异步且有状态(持久 receive 任务),而 MagnaX 的采集是
同步的、被 Flask 多线程按 HTTP 请求驱动。这里用一个"后台事件循环线程 + 单例"把异步接口包成
同步:保活 WebinspectorService/InspectorSession,运行时轮询每次仅 ~3ms(实测),避免每次
重连(get_open_application_pages 有 ~1.5s 固定等待)。

设备前提(缺一即 WebInspectorNotEnabledError):
  ① 设置→Apps→Safari→高级→网页检查器 打开;② 手机解锁亮屏(锁屏时 webinspectord 不响应);
  ③ Safari 前台开着 http 页面(非无痕)。WKWebView 需 App 设 isInspectable=true。
"""
import asyncio
import threading

from loguru import logger


class IOSInspectorError(Exception):
    """iOS WebKit Inspector 通信异常"""
    pass


def _get_rsd_sync(device_id, retries=4):
    """在无运行事件循环的线程里取设备句柄(get_tunneld_devices 内部自开循环,不能在
    运行中的 loop 里调 —— 故本函数只在 run_in_executor 的线程里执行)。
    iOS17+ 走 tunneld 的 RSD;iOS<17 退回 usbmux lockdown。两者都能喂给 WebinspectorService。
    tunneld 高频建连偶发瞬时无设备,重试几次再退回。"""
    import time as _t
    for attempt in range(max(1, retries)):
        try:
            from pymobiledevice3.tunneld.api import get_tunneld_devices
            devs = get_tunneld_devices()
            for r in devs:
                if not device_id or device_id in str(r.udid):
                    return r
            if devs:
                return devs[0]
        except Exception as e:
            logger.debug(f'[iOS H5] tunneld 查询失败: {e}')
        if attempt < retries - 1:
            _t.sleep(0.6)
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        return create_using_usbmux(serial=device_id)
    except Exception as e:
        logger.debug(f'[iOS H5] usbmux 连接失败: {e}')
    return None


class _LoopThread(object):
    """一个常驻后台线程跑一个事件循环,所有异步操作提交到它上面串行执行。"""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro, timeout=30):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result(timeout)


class IOSWebInspector(object):
    """保活一条 webinspector 连接 + 一个页面的 InspectorSession,对外提供同步方法。
    按 device_id 单例(见 get_inspector),让运行时轮询复用同一 session。"""

    def __init__(self, device_id):
        self.device_id = device_id
        self._lt = _LoopThread()
        self._insp = None            # WebinspectorService
        self._session = None         # InspectorSession(当前页面)
        self._page_url = None        # 当前页面 url(重连时按它找回同一页)
        self._lock = asyncio.Lock()  # 串行化对单条 ws 的读写

    # ---------- 同步入口(Flask 线程调用) ----------
    def list_pages(self, timeout=1.5):
        return self._lt.run(self._alist_pages(timeout), timeout=timeout + 12)

    # WiFi 隧道抖动时 WebKit 事件收不到,evaluate/connect 会一直等到超时。把默认超时压到 8s,
    # 让卡住的一次快速失败(前端图表顿一下跳过,配合 collectRuntime/Load 的丢弃自愈下次恢复),
    # 而不是死等 25s。reload 触发导航略慢,给 15s。
    _CONNECT_TIMEOUT = 8
    _EVAL_TIMEOUT = 8
    _RELOAD_TIMEOUT = 15

    def connect_page(self, url=None, page_id=None):
        return self._lt.run(self._aconnect_page(url, page_id), timeout=self._CONNECT_TIMEOUT)

    def evaluate(self, js, timeout=None):
        """执行 JS 取返回值(通常是 JSON 字符串)。session 断了自动重连重试一次。"""
        return self._lt.run(self._aeval(js), timeout=timeout or self._EVAL_TIMEOUT)

    def send(self, method, timeout=None, **params):
        """发一条 WebKit 协议域命令(如 Heap.enable / Network.enable),返回原始 result。"""
        return self._lt.run(self._asend(method, params), timeout=timeout or self._EVAL_TIMEOUT)

    def reload(self, ignore_cache=True, timeout=None):
        return self._lt.run(self._areload(ignore_cache), timeout=timeout or self._RELOAD_TIMEOUT)

    def close(self):
        try:
            self._lt.run(self._aclose(), timeout=10)
        except Exception:
            pass

    # ---------- 异步实现(跑在后台 loop) ----------
    async def _ensure_insp(self):
        if self._insp is not None:
            return
        rsd = await self._lt.loop.run_in_executor(None, _get_rsd_sync, self.device_id)
        if rsd is None:
            raise IOSInspectorError('未找到 iOS 设备(iOS17+ 需 tunneld 隧道在跑)')
        from pymobiledevice3.services.webinspector import WebinspectorService
        insp = WebinspectorService(rsd)
        try:
            await insp.connect(timeout=10)
        except Exception as e:
            raise IOSInspectorError(
                '连不上 webinspector,请确认:①设置→Apps→Safari→高级→网页检查器 已开;'
                '②手机解锁亮屏;③Safari 开着 http 页面(非无痕)。'
                f' 原始错误: {e}')
        self._insp = insp

    async def _web_pages(self, timeout):
        from pymobiledevice3.services.webinspector import WirTypes
        pages = await self._insp.get_open_application_pages(timeout=timeout)
        return [ap for ap in pages if ap.page.type_ in (WirTypes.WEB, WirTypes.WEB_PAGE)]

    async def _alist_pages(self, timeout):
        await self._ensure_insp()
        out = []
        for ap in await self._web_pages(timeout):
            out.append({
                'id': ap.page.id_, 'app': ap.application.name,
                'bundle': ap.application.bundle, 'pid': ap.application.pid,
                'url': ap.page.web_url, 'title': ap.page.web_title,
            })
        return out

    def _dispose_session(self):
        """关掉旧 InspectorSession 的后台 receive 任务。否则它会持续吞 wir_events,
        令后续 get_open_application_pages / 新 session 抢不到事件而超时。"""
        sess = self._session
        self._session = None
        if sess is not None:
            task = getattr(sess, '_receive_task', None)
            if task is not None:
                try:
                    task.cancel()
                except Exception:
                    pass

    async def _aconnect_page(self, url, page_id):
        await self._ensure_insp()
        # 复用:已连到目标页且 url 仍匹配当前页,直接复用当前 session,避免每次轮询重建。
        # 以 url 而非 page_id 判身份 —— page_id 会因 reload 变化,url 才是跨 reload 稳定的身份;
        # page_id 仅用于首连/换页时消歧(多标签同 url 的极端情况)。reload 后 InspectorSession
        # 会自动跟随新 target,故 session 仍有效。
        if self._session is not None and url and self._page_url and url in self._page_url:
            return {'url': self._page_url, 'title': ''}
        cand = await self._web_pages(1.5)
        if not cand:
            raise IOSInspectorError('没有可调试网页(确认 Safari 打开 http 页面、非无痕、已开网页检查器)')
        ap = None
        if page_id is not None:
            ap = next((a for a in cand if str(a.page.id_) == str(page_id)), None)
        if ap is None and url:
            ap = next((a for a in cand if url and url in a.page.web_url), None)
        if ap is None:
            ap = next((a for a in cand if a.page.web_url.startswith('http')), cand[0])
        self._dispose_session()  # 建新 session 前先关旧的 receive 任务
        # pymobiledevice3 建 session 时 InspectorSession.create 会 pop wir_events[0],
        # 该 applicationSentListing 事件偶发还没入队就 pop 空列表(IndexError)。
        # 重试:每次先重新拉页面(触发设备重发 listing 事件补充 wir_events)再建 session,
        # 显著降低首连失败率;彻底拿不到再抛明确错误。
        last_err = None
        for attempt in range(4):
            try:
                self._session = await self._insp.inspector_session(ap.application, ap.page)
                break
            except IndexError as e:  # wir_events.pop from empty list
                last_err = e
                self._dispose_session()
                await asyncio.sleep(0.6)
                cand2 = await self._web_pages(1.5)
                if cand2:
                    ap = (next((a for a in cand2 if str(a.page.id_) == str(ap.page.id_)), None)
                          or next((a for a in cand2 if a.page.web_url.startswith('http')), cand2[0]))
        else:
            raise IOSInspectorError(
                f'webinspector 建会话失败(WebKit 事件未就绪,多为隧道抖动或页面刚切换): {last_err}')
        await self._session.runtime_enable()
        self._page_url = ap.page.web_url
        return {'url': ap.page.web_url, 'title': ap.page.web_title}

    async def _reconnect(self):
        self._dispose_session()
        try:
            if self._insp:
                await self._insp.close()
        except Exception:
            pass
        self._insp = None
        await self._aconnect_page(self._page_url, None)

    async def _ensure_session(self):
        if self._session is None:
            await self._aconnect_page(self._page_url, None)

    async def _aeval(self, js):
        async with self._lock:
            await self._ensure_session()
            try:
                return await self._session.runtime_evaluate(js, return_by_value=True)
            except Exception as e:
                logger.warning(f'[iOS H5] evaluate 失败,重连重试: {e}')
                await self._reconnect()
                return await self._session.runtime_evaluate(js, return_by_value=True)

    async def _asend(self, method, params):
        async with self._lock:
            await self._ensure_session()
            try:
                return await self._session.send_command(method, **params)
            except Exception as e:
                logger.warning(f'[iOS H5] {method} 失败,重连重试: {e}')
                await self._reconnect()
                return await self._session.send_command(method, **params)

    async def _areload(self, ignore_cache):
        async with self._lock:
            await self._ensure_session()
            # WebKit InspectorSession 无 Page.addScriptToEvaluateOnNewDocument 的等价简易接口,
            # 直接用 JS 触发 reload;target 变更由 InspectorSession 的 didCommitProvisionalTarget 自动跟。
            expr = 'location.reload(true)' if ignore_cache else 'location.reload()'
            return await self._session.runtime_evaluate(expr, return_by_value=True)

    async def _aclose(self):
        self._dispose_session()
        try:
            if self._insp:
                await self._insp.close()
        finally:
            self._insp = None


# ---------- 单例注册表(按 device_id 复用连接) ----------
_registry = {}
_registry_lock = threading.Lock()


def get_inspector(device_id):
    with _registry_lock:
        insp = _registry.get(device_id)
        if insp is None:
            insp = IOSWebInspector(device_id)
            _registry[device_id] = insp
        return insp


def drop_inspector(device_id):
    with _registry_lock:
        insp = _registry.pop(device_id, None)
    if insp:
        insp.close()


def list_ios_targets(device_id):
    """列出 iOS 可调试目标(Safari 各标签 + 可调试 WKWebView),供前端选择。
    返回 [{'id','app','bundle','pid','url','title','label'}]。"""
    pages = get_inspector(device_id).list_pages()
    SAFARI = 'com.apple.mobilesafari'
    for p in pages:
        if p.get('bundle') == SAFARI:
            p['label'] = f"Safari: {p.get('title') or p.get('url') or ''}"[:80]
        else:
            p['label'] = f"{p.get('app') or p.get('bundle')}: {p.get('title') or p.get('url') or ''}"[:80]
    # Safari 排前面
    pages.sort(key=lambda x: 0 if x.get('bundle') == SAFARI else 1)
    return pages
