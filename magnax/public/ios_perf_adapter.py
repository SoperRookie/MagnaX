"""
iOS Performance Adapter using pymobiledevice3 Python API only.

This module provides a unified adapter for collecting iOS performance metrics
using pymobiledevice3 DVT services directly (no CLI subprocess calls).

For iOS 17+: Uses tunneld service
    Start with: sudo python3 -m pymobiledevice3 remote start-tunnel
    Or daemon mode: sudo python3 -m pymobiledevice3 remote tunneld

For iOS < 17: Uses direct USB connection via lockdown
"""

import time
import asyncio
import threading
from dataclasses import dataclass, field
from typing import Tuple, Optional, Dict, Any, List
from loguru import logger


def _run_async(coro):
    """Run an async coroutine in sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're already in an async context, create a new loop in a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)
    else:
        return asyncio.run(coro)


# tunneld 无可用设备(隧道断)时的告警节流:高频采集下每次都 warn 会刷屏,
# 这里做全局限流,最多每 _TUNNELD_WARN_INTERVAL 秒告警一次。
_last_tunneld_warn_time: float = 0.0
_TUNNELD_WARN_INTERVAL = 15.0


def _warn_tunneld_missing(device_id: Optional[str]) -> None:
    """iOS 17+ 场景下 tunneld 拿不到设备(隧道已断)时,给出明确可操作的告警。

    设备重插/休眠、tunneld 进程状态卡死后很常见,一旦隧道断,CPU/内存/FPS/GPU/网络
    会全部静默变 0。这里把原来的 debug 提升为可见 WARNING(节流),避免下次再当成
    '某个 App 采不到数据' 反复排查。
    """
    global _last_tunneld_warn_time
    now = time.time()
    if now - _last_tunneld_warn_time < _TUNNELD_WARN_INTERVAL:
        return
    _last_tunneld_warn_time = now
    logger.warning(
        "[iOS Perf] tunneld 无可用设备,隧道可能已断(设备重插/休眠或 tunneld 卡死后常见)"
        " —— iOS 17+ 所有性能数据都会变 0。请重启 tunneld:\n"
        "  sudo python3 -m pymobiledevice3 remote tunneld\n"
        f"  (目标设备: {device_id})"
    )


@dataclass
class PerformanceCache:
    """Performance data cache with TTL support."""
    cpu_app: float = 0.0
    cpu_sys: float = 0.0
    memory_mb: float = 0.0
    fps: int = 0
    gpu: float = 0.0
    network_rx_kb: float = 0.0
    network_tx_kb: float = 0.0
    timestamp: float = field(default_factory=time.time)

    # Raw network bytes for delta calculation
    _last_net_rx_bytes: int = 0
    _last_net_tx_bytes: int = 0
    _last_net_time: float = 0.0

    def is_valid(self, ttl: float = 2.0) -> bool:
        """Check if cache is still valid."""
        return (time.time() - self.timestamp) < ttl


class PMD3PerformanceAdapter:
    """
    Unified pymobiledevice3 performance adapter.

    Uses DVT services directly via Python API for all iOS versions.
    For iOS 17+, tunneld must be running:
        sudo python3 -m pymobiledevice3 remote tunneld
    """

    # 网络差分基准值,按 device_id 跨 adapter 实例保持。
    # netBytesIn/Out 是累积计数器,网速靠两次读数做差分。
    # 由于"方案B"每次采集后会 close() 销毁 adapter,基准值必须存在类级别才能跨周期保留,
    # 否则每次都是首读取 -> 差分恒为 0 -> iOS 网络永远抓不到数据。
    # 结构: {device_id: (rx_bytes, tx_bytes, timestamp)}
    _net_baseline: Dict[str, Tuple[int, int, float]] = {}

    # CPU 差值基准,同样按 device_id 跨 adapter 实例保留。
    # app/系统 CPU 靠 cpuTotalUser+cpuTotalSystem 两次读数做差分,基准若放实例级,
    # "方案B"每次采集后 close() 销毁 adapter -> 每帧都是首帧 -> app CPU 恒为 0。
    # 与 _net_baseline 同样的坑,之前只修了网络漏了 CPU。
    # 结构: {device_id: (last_cpu_total{pid: int}, last_cpu_time)}
    _cpu_baseline: Dict[str, Tuple[Dict[int, int], float]] = {}

    def __init__(self, device_id: str, bundle_id: str):
        self.device_id = device_id
        self.bundle_id = bundle_id

        self._lock = threading.RLock()
        self._dvt = None
        self._lockdown = None
        self._rsd = None
        self._is_ios17: Optional[bool] = None
        self._init_error: Optional[str] = None
        self._target_pid: Optional[int] = None

        # Cache
        self._cache = PerformanceCache()
        self._cache_ttl = 2.0

        # Sysmontap data cache (shared between CPU/Memory/Network)
        self._sysmon_data: Optional[Dict] = None
        self._sysmon_processes: Optional[List[Dict]] = None
        self._sysmon_time: float = 0.0

        # CPU delta tracking (for calculating CPU % from cpuTotalUser/cpuTotalSystem)
        self._last_cpu_time: float = 0.0
        self._last_cpu_total: Dict[int, int] = {}  # pid -> cpuTotalUser + cpuTotalSystem
        self._sysmon_ttl = 1.0  # Reduced TTL for more responsive data

        # Graphics data cache (shared between FPS/GPU)
        self._graphics_data: Optional[Dict] = None
        self._graphics_time: float = 0.0
        self._graphics_ttl = 1.0  # Reduced TTL for more responsive data

        # Collection state tracking
        self._collecting_sysmon = False
        self._collecting_graphics = False

    def _detect_ios_version(self) -> bool:
        """Detect if device is iOS 17+."""
        if self._is_ios17 is not None:
            return self._is_ios17

        try:
            from pymobiledevice3.lockdown import create_using_usbmux
            lockdown = create_using_usbmux(serial=self.device_id)
            version = lockdown.product_version
            if version:
                major = int(version.split('.')[0])
                self._is_ios17 = major >= 17
                logger.info(f"[iOS Perf] Device iOS version: {version}, iOS 17+: {self._is_ios17}")
                return self._is_ios17
        except Exception as e:
            logger.debug(f"[iOS Perf] Failed to detect iOS version via USB: {e}")

        # If USB detection fails, try tunneld service (iOS 17+ only works via tunnel)
        try:
            from pymobiledevice3.tunneld.api import get_tunneld_devices
            devices = get_tunneld_devices()
            if devices:
                for rsd in devices:
                    if self.device_id is None or self.device_id in str(rsd.udid):
                        self._is_ios17 = True
                        logger.info(f"[iOS Perf] Found device via tunneld, assuming iOS 17+")
                        return True
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[iOS Perf] tunneld service check failed: {e}")

        # Default to iOS < 17
        self._is_ios17 = False
        return False

    def _get_tunnel_rsd(self):
        """Get RemoteServiceDiscovery from tunneld service."""
        try:
            from pymobiledevice3.tunneld.api import get_tunneld_devices, get_tunneld_device_by_udid
            from pymobiledevice3.exceptions import TunneldConnectionError

            # Try to get all devices first (more reliable)
            try:
                devices = get_tunneld_devices()
                if devices and len(devices) > 0:
                    for rsd in devices:
                        if self.device_id is None or self.device_id in str(rsd.udid):
                            logger.info(f"[iOS Perf] Found tunneld device: {rsd.udid}")
                            return rsd
                    # Use first device if no exact match
                    logger.info(f"[iOS Perf] Using first tunneld device: {devices[0].udid}")
                    return devices[0]
                else:
                    # 高频建连时 tunneld 偶发瞬时无设备,_ensure_connected 会自动重试,降为 debug 避免刷屏
                    logger.debug("[iOS Perf] tunneld returned no devices (will retry)")
            except TunneldConnectionError:
                logger.warning("[iOS Perf] tunneld connection failed - is tunneld running?")

        except ImportError as e:
            logger.warning(f"[iOS Perf] tunneld API not available: {e}")
        except Exception as e:
            logger.warning(f"[iOS Perf] tunneld error: {type(e).__name__}: {e}")
        return None

    def _create_dvt_service(self):
        """Create DVT service based on iOS version."""
        from pymobiledevice3.services.dvt.dvt_secure_socket_proxy import DvtSecureSocketProxyService

        self._detect_ios_version()

        if self._is_ios17:
            # iOS 17+ requires tunnel service
            rsd = self._get_tunnel_rsd()
            if rsd is None:
                self._init_error = (
                    "tunneld 无可用设备,隧道可能已断。iOS 17+ 需要隧道服务,请重启 tunneld:\n"
                    "  sudo python3 -m pymobiledevice3 remote tunneld\n"
                    "(设备重插/休眠或 tunneld 卡死后,所有 iOS 性能数据会静默变 0)"
                )
                # 瞬时无 rsd 时由上层 _ensure_connected 重试,单次不刷屏;
                # 但通过节流的 _warn_tunneld_missing 给出可见告警,避免"静默返回 0"难以排查。
                _warn_tunneld_missing(self.device_id)
                return None

            self._rsd = rsd
            dvt = DvtSecureSocketProxyService(lockdown=rsd)
            dvt.__enter__()
            logger.info("[iOS Perf] DVT service connected via tunnel (iOS 17+)")
            return dvt
        else:
            # iOS < 17 uses direct USB
            from pymobiledevice3.lockdown import create_using_usbmux
            lockdown = create_using_usbmux(serial=self.device_id)
            self._lockdown = lockdown
            dvt = DvtSecureSocketProxyService(lockdown=lockdown)
            dvt.__enter__()
            logger.info("[iOS Perf] DVT service connected via USB (iOS < 17)")
            return dvt

    def _ensure_connected(self, max_retries: int = 2) -> bool:
        """Ensure DVT service is connected with retry logic."""
        with self._lock:
            if self._dvt is not None:
                return True

            last_error = None
            for attempt in range(max_retries):
                try:
                    self._dvt = self._create_dvt_service()
                    if self._dvt:
                        self._resolve_target_pid()
                        return True
                except Exception as e:
                    last_error = e
                    logger.warning(f"[iOS Perf] Connection attempt {attempt + 1}/{max_retries} failed: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(0.5)  # Brief delay before retry

            if last_error:
                self._init_error = str(last_error)
                logger.error(f"[iOS Perf] Failed to connect DVT service after {max_retries} attempts: {last_error}")

            return False

    def _resolve_target_pid(self):
        """Try to resolve PID for bundle_id using ProcessControl."""
        if not self._dvt or not self.bundle_id:
            return

        try:
            from pymobiledevice3.services.dvt.instruments.process_control import ProcessControl
            proc_ctrl = ProcessControl(self._dvt)
            pid = proc_ctrl.process_identifier_for_bundle_identifier(self.bundle_id)
            if pid and pid > 0:
                self._target_pid = pid
                logger.info(f"[iOS Perf] Resolved PID {pid} for bundle_id {self.bundle_id}")
                return
        except Exception as e:
            logger.debug(f"[iOS Perf] ProcessControl lookup failed: {e}")

        self._target_pid = None

    def _collect_sysmontap_data(self) -> Tuple[Optional[Dict], Optional[List[Dict]]]:
        """
        Collect system monitoring data via Sysmontap.
        Returns (system_data, processes_list).
        Uses caching to avoid repeated calls.
        """
        # Non-blocking check: if another thread is collecting, return cached data
        if self._collecting_sysmon:
            logger.debug("[iOS Perf] Sysmontap collection in progress, returning cached data")
            return self._sysmon_data, self._sysmon_processes

        with self._lock:
            current_time = time.time()
            if (self._sysmon_data is not None and
                (current_time - self._sysmon_time) < self._sysmon_ttl):
                return self._sysmon_data, self._sysmon_processes

            if not self._ensure_connected():
                return None, None

            self._collecting_sysmon = True

            try:
                from pymobiledevice3.services.dvt.instruments.sysmontap import Sysmontap

                system_data = {}
                processes = []
                sys_attrs = None
                proc_attrs = None

                sysmon = Sysmontap(self._dvt)
                sysmon.__enter__()

                try:
                    sample_count = 0
                    has_system_data = False
                    has_process_data = False
                    processes_sample_count = 0

                    for raw_data in sysmon:
                        # Skip non-dict samples (sometimes strings are returned)
                        if not isinstance(raw_data, dict):
                            continue

                        sample_count += 1

                        # Get attribute lists (field names) - only available in first sample
                        if sys_attrs is None:
                            sys_attrs = raw_data.get('SystemAttributes', [])
                            proc_attrs = raw_data.get('ProcessesAttributes', [])

                        # Parse System data (network, CPU total)
                        sys_values = raw_data.get('System')
                        if sys_values and isinstance(sys_values, list) and sys_attrs and len(sys_values) > 0:
                            system_data = dict(zip(sys_attrs, sys_values))
                            has_system_data = True

                            # Also capture SystemCPUUsage if available
                            cpu_usage = raw_data.get('SystemCPUUsage', {})
                            if cpu_usage:
                                system_data.update(cpu_usage)

                        # Capture CPUCount if available
                        if 'CPUCount' in raw_data:
                            system_data['CPUCount'] = raw_data.get('CPUCount', 1)

                        # Parse Processes data (CPU per process, memory)
                        proc_dict = raw_data.get('Processes')
                        if proc_dict and isinstance(proc_dict, dict) and proc_attrs:
                            processes_sample_count += 1

                            # Skip first Processes sample - it often has cpuUsage=None
                            if processes_sample_count == 1:
                                logger.debug("[iOS Perf] Skipping first Processes sample")
                                continue

                            processes = []  # Clear and rebuild each time
                            for pid, proc_values in proc_dict.items():
                                if isinstance(proc_values, list):
                                    proc_info = dict(zip(proc_attrs, proc_values))
                                    proc_info['pid'] = pid
                                    processes.append(proc_info)
                                elif isinstance(proc_values, dict):
                                    proc_values['pid'] = pid
                                    processes.append(proc_values)
                            has_process_data = True

                        # Need both system data and valid process data
                        # Processes start around sample 6, so allow up to 10 samples
                        if (has_system_data and has_process_data) or sample_count >= 10:
                            break
                finally:
                    # Close Sysmontap, ignoring "clear" errors on some iOS versions
                    try:
                        sysmon.__exit__(None, None, None)
                    except Exception:
                        pass

                # Only update cache if we got USEFUL data
                # system_data must have netBytesIn to be useful
                # processes must have at least one entry to be useful
                has_valid_system = bool(system_data and 'netBytesIn' in system_data)
                has_valid_processes = bool(processes and len(processes) > 0)

                if has_valid_system or has_valid_processes:
                    if has_valid_system:
                        self._sysmon_data = system_data
                    if has_valid_processes:
                        self._sysmon_processes = processes
                    self._sysmon_time = current_time
                    logger.debug(f"[iOS Perf] Sysmontap collected: {len(processes)} processes, "
                                f"netBytesIn={system_data.get('netBytesIn', 'N/A')}")
                else:
                    logger.debug("[iOS Perf] Sysmontap returned no useful data, keeping previous cache")

                self._collecting_sysmon = False
                return system_data, processes

            except Exception as e:
                self._collecting_sysmon = False
                error_msg = str(e)
                logger.warning(f"[iOS Perf] Sysmontap collection failed: {e}")
                # Close DVT on connection errors to force reconnection
                if 'Bad file descriptor' in error_msg or 'magic' in error_msg or 'closed' in error_msg.lower():
                    self._close_dvt()
                return self._sysmon_data, self._sysmon_processes

    def _collect_graphics_data(self) -> Optional[Dict]:
        """
        Collect graphics data via Graphics service.
        Returns dict with FPS and GPU metrics.
        Uses caching to avoid repeated calls.
        """
        # Non-blocking check: if another thread is collecting, return cached data
        if self._collecting_graphics:
            logger.debug("[iOS Perf] Graphics collection in progress, returning cached data")
            return self._graphics_data

        with self._lock:
            current_time = time.time()
            if (self._graphics_data is not None and
                (current_time - self._graphics_time) < self._graphics_ttl):
                return self._graphics_data

            if not self._ensure_connected():
                return None

            self._collecting_graphics = True

            try:
                from pymobiledevice3.services.dvt.instruments.graphics import Graphics

                logger.debug("[iOS Perf] Starting Graphics data collection...")
                graphics = Graphics(self._dvt)
                graphics.__enter__()

                try:
                    sample_count = 0
                    for data in graphics:
                        sample_count += 1
                        if data:
                            fps = data.get('CoreAnimationFramesPerSecond', 0)
                            gpu = data.get('Device Utilization %', 0)

                            # Skip samples with FPS=0 (common when screen is idle or during startup)
                            # But always accept after sample 3 to avoid getting stuck
                            if fps == 0 and sample_count < 3:
                                logger.debug(f"[iOS Perf] Skipping sample {sample_count} with FPS=0")
                                continue

                            self._graphics_data = data
                            self._graphics_time = current_time
                            logger.debug(f"[iOS Perf] Graphics collected: FPS={fps}, GPU={gpu}")
                            break  # Got sample

                        if sample_count >= 5:  # Give up after 5 samples
                            logger.warning("[iOS Perf] Graphics returned no valid data after 5 samples")
                            break
                finally:
                    # Close Graphics, ignoring "clear" errors on some iOS versions
                    try:
                        graphics.__exit__(None, None, None)
                    except Exception:
                        pass

                self._collecting_graphics = False
                return self._graphics_data

            except Exception as e:
                self._collecting_graphics = False
                error_msg = str(e)
                logger.warning(f"[iOS Perf] Graphics collection failed: {e}")
                # Close DVT on connection errors to force reconnection
                if 'Bad file descriptor' in error_msg or 'magic' in error_msg or 'closed' in error_msg.lower():
                    self._close_dvt()
                return self._graphics_data

    def _match_by_pid(self, processes: List[Dict]) -> Optional[Dict]:
        """按 PID 精确匹配进程。
        pid 在不同 iOS 版本/机型可能是 int 或 str,这里统一转 int 比较,
        避免 '362' == 362 这类类型不一致导致漏匹配。"""
        if not self._target_pid:
            return None
        for proc in processes:
            pid = proc.get('pid')
            try:
                if int(pid) == int(self._target_pid):
                    return proc
            except (TypeError, ValueError):
                continue
        return None

    def _find_app_process(self, processes: List[Dict]) -> Optional[Dict]:
        """Find process matching bundle_id using multiple matching strategies."""
        if not processes or not self.bundle_id:
            return None

        # 1) 优先按 PID 精确匹配。
        #    cocos/引擎打包的 App 可执行名会被混淆(如 x5N4GZCHysB),与 bundle_id、
        #    显示名毫不相干,后面的"按名字打分"对它们永远打不中,PID 是唯一可靠方式。
        proc = self._match_by_pid(processes)
        if proc is not None:
            return proc

        # 2) PID 没命中:可能是首次尚未解析,或 App 重启/切换导致 PID 变化。
        #    重新用 ProcessControl 解析一次 PID 再试,而不是直接退回脆弱的名字匹配 ——
        #    这样混淆名的 cocos 包在 PID 抖动时也能稳定恢复,不会静默丢数据。
        self._resolve_target_pid()
        proc = self._match_by_pid(processes)
        if proc is not None:
            return proc

        # 3) 仍未命中,退回按名字打分(仅对进程名与 bundle_id 相近的普通 App 有效)。
        bundle_id_lower = self.bundle_id.lower()
        app_name = self.bundle_id.split('.')[-1].lower()

        # Filter meaningful bundle parts
        bundle_parts = [p for p in bundle_id_lower.split('.')
                       if p not in ('com', 'apple', 'app', 'ios', 'mobile') and len(p) >= 3]

        best_match = None
        best_score = 0

        for proc in processes:
            name = str(proc.get('name', '')).lower()
            exec_name = str(proc.get('execName', '')).lower()
            bundle_identifier = str(proc.get('bundleIdentifier', '')).lower()

            score = 0

            # Exact bundle identifier match (highest priority)
            if bundle_identifier and bundle_id_lower == bundle_identifier:
                return proc

            # Exact name match with bundle_id
            if bundle_id_lower == name:
                return proc

            # Process name starts with bundle_id (handles truncation)
            if name.startswith(bundle_id_lower[:len(name)]) and len(name) >= 8:
                score = 100

            # Bundle_id starts with process name
            elif bundle_id_lower.startswith(name) and len(name) >= 8:
                score = 95

            # App name exact match
            elif app_name == name:
                score = 90

            # App name in process name
            elif app_name in name and len(app_name) >= 3:
                score = 85

            # Name in app name
            elif name in app_name and len(name) >= 4:
                score = 80

            # Bundle parts in name
            elif bundle_parts and any(part == name or part in name for part in bundle_parts):
                score = 75

            # Check execName
            elif bundle_id_lower in exec_name:
                score = 70
            elif app_name in exec_name and len(app_name) >= 3:
                score = 65
            elif bundle_parts and any(part in exec_name for part in bundle_parts):
                score = 60

            if score > best_score:
                best_score = score
                best_match = proc

        if best_score >= 60:
            logger.debug(f"[iOS Perf] Matched process: {best_match.get('name')} (score={best_score})")
            return best_match

        logger.warning(f"[iOS Perf] No process match for {self.bundle_id}. "
                      f"Available: {[p.get('name') for p in processes[:15]]}")
        return None

    def _calculate_cpu_from_delta(self, proc: Dict, current_time: float) -> float:
        """Calculate CPU % from cpuTotalUser + cpuTotalSystem delta."""
        pid = proc.get('pid', 0)
        cpu_user = proc.get('cpuTotalUser', 0) or 0
        cpu_sys = proc.get('cpuTotalSystem', 0) or 0
        cpu_total = cpu_user + cpu_sys

        if self._last_cpu_time > 0 and pid in self._last_cpu_total:
            dt = current_time - self._last_cpu_time
            if dt > 0:
                delta = cpu_total - self._last_cpu_total[pid]
                # Convert from nanoseconds to seconds, then to percentage
                cpu_pct = (delta / 1e9) / dt * 100
                # Store for next calculation
                self._last_cpu_total[pid] = cpu_total
                return max(0.0, cpu_pct)

        # First reading - store baseline
        self._last_cpu_total[pid] = cpu_total
        return 0.0

    def get_cpu(self) -> Tuple[float, float]:
        """
        Get CPU usage.
        Returns (app_cpu%, sys_cpu%).

        Note: CPU % is calculated from cpuTotalUser + cpuTotalSystem deltas
        since the cpuUsage field may not be populated on iOS 17+.
        """
        try:
            system_data, processes = self._collect_sysmontap_data()
            current_time = time.time()

            # 从类级基准恢复上次读数(跨 adapter 实例/跨采集保留)。
            # 否则方案B每帧新建 adapter -> 基准为空 -> 差分恒 0 -> app CPU 永远采不到。
            last_total, last_time = PMD3PerformanceAdapter._cpu_baseline.get(
                self.device_id, ({}, 0.0))
            self._last_cpu_total = dict(last_total)
            self._last_cpu_time = last_time

            app_cpu = 0.0
            sys_cpu = 0.0
            cpu_count = system_data.get('CPUCount', 6) if system_data else 6

            if system_data:
                # Try System CPU from total load first
                total_load = system_data.get('CPU_TotalLoad', 0)
                if total_load and total_load > 0:
                    sys_cpu = total_load / cpu_count if cpu_count > 1 else total_load

            if processes:
                # Find target app process
                app_proc = self._find_app_process(processes)
                if app_proc:
                    # Try cpuUsage field first
                    raw_cpu = app_proc.get('cpuUsage')
                    if raw_cpu is not None and isinstance(raw_cpu, (int, float)) and raw_cpu > 0:
                        app_cpu = float(raw_cpu)
                    else:
                        # Calculate from cpuTotalUser + cpuTotalSystem delta
                        app_cpu = self._calculate_cpu_from_delta(app_proc, current_time)

                # Calculate system CPU from all processes if not available
                if sys_cpu <= 0:
                    total_cpu = 0.0
                    for p in processes:
                        raw = p.get('cpuUsage')
                        if raw is not None and isinstance(raw, (int, float)) and raw > 0:
                            total_cpu += float(raw)
                        else:
                            # Use delta calculation
                            total_cpu += self._calculate_cpu_from_delta(p, current_time)
                    sys_cpu = total_cpu / cpu_count if cpu_count > 0 else total_cpu

            # Update last CPU time for delta calculations
            self._last_cpu_time = current_time
            # 持久化基准到类级,供下次采集(新 adapter)做差分
            PMD3PerformanceAdapter._cpu_baseline[self.device_id] = (
                self._last_cpu_total, current_time)

            self._cache.cpu_app = round(app_cpu, 2)
            self._cache.cpu_sys = round(min(sys_cpu, 100.0), 2)  # Cap at 100%
            return (self._cache.cpu_app, self._cache.cpu_sys)

        except Exception as e:
            logger.error(f"[iOS Perf] get_cpu failed: {e}")
            return (self._cache.cpu_app, self._cache.cpu_sys)

    # 不同 iOS 版本/机型 Sysmontap 返回的内存字段名不一致，按优先级尝试这些已知字段
    _MEM_FIELDS = ('physFootprint', 'memResidentSize', 'memRShrd',
                   'memRPrvt', 'memAnon', 'memVirtualSize')

    def _extract_memory_bytes(self, proc: Dict) -> float:
        """从进程信息里提取内存字节数，兼容不同 iOS 版本的字段命名。"""
        # 1) 先按已知字段名取
        for key in self._MEM_FIELDS:
            val = proc.get(key)
            if isinstance(val, (int, float)) and val > 0:
                return float(val)
        # 2) 已知字段都没有 → 启发式扫描任何像内存的字段（footprint/resident/mem*）
        candidates = {k: v for k, v in proc.items()
                      if isinstance(v, (int, float)) and v > 0
                      and ('footprint' in k.lower() or 'resident' in k.lower()
                           or k.lower().startswith('mem'))}
        if candidates:
            # 取数值最大的那个（通常即占用内存），并打印出来便于确认字段名
            key = max(candidates, key=candidates.get)
            logger.warning(f"[iOS Perf] 已知内存字段缺失，启发式采用 '{key}'={candidates[key]}; "
                           f"该进程全部内存类字段: {candidates}")
            return float(candidates[key])
        # 3) 彻底没有 → 打印该进程所有数值字段，方便定位
        nums = {k: v for k, v in proc.items() if isinstance(v, (int, float))}
        logger.warning(f"[iOS Perf] 进程 {proc.get('name')} 未找到任何内存字段, "
                       f"可用数值字段: {nums}")
        return 0.0

    def get_memory(self) -> float:
        """Get memory usage in MB."""
        try:
            _, processes = self._collect_sysmontap_data()

            if processes:
                app_proc = self._find_app_process(processes)
                if app_proc:
                    mem_bytes = self._extract_memory_bytes(app_proc)

                    if mem_bytes > 0:
                        # Convert to MB
                        if mem_bytes > 1000000:  # Bytes
                            self._cache.memory_mb = round(mem_bytes / (1024 * 1024), 2)
                        else:  # Already in MB or some other unit
                            self._cache.memory_mb = round(mem_bytes, 2)

                        logger.debug(f"[iOS Perf] App memory: {self._cache.memory_mb} MB")

            return self._cache.memory_mb

        except Exception as e:
            logger.error(f"[iOS Perf] get_memory failed: {e}")
            return self._cache.memory_mb

    def get_fps(self) -> int:
        """Get current FPS."""
        try:
            data = self._collect_graphics_data()

            if data:
                fps = data.get('CoreAnimationFramesPerSecond', 0)
                if isinstance(fps, (int, float)):
                    self._cache.fps = int(fps)

            return self._cache.fps

        except Exception as e:
            logger.error(f"[iOS Perf] get_fps failed: {e}")
            return self._cache.fps

    def get_gpu(self) -> float:
        """Get GPU utilization percentage."""
        try:
            data = self._collect_graphics_data()

            if data:
                # Try different GPU metric keys
                gpu = (data.get('Device Utilization %', 0) or
                       data.get('Renderer Utilization %', 0) or
                       data.get('Tiler Utilization %', 0) or 0)

                if isinstance(gpu, (int, float)):
                    self._cache.gpu = float(gpu)

            return self._cache.gpu

        except Exception as e:
            logger.error(f"[iOS Perf] get_gpu failed: {e}")
            return self._cache.gpu

    def get_network(self) -> Tuple[float, float]:
        """
        Get network usage.
        Returns (download_kb/s, upload_kb/s) - rate per second.
        """
        try:
            system_data, _ = self._collect_sysmontap_data()

            # 必须确认拿到了 netBytesIn,否则会用 0 当基准值,下次采集算出巨大的假差分
            if system_data and 'netBytesIn' in system_data:
                rx_bytes = system_data.get('netBytesIn', 0) or 0
                tx_bytes = system_data.get('netBytesOut', 0) or 0
                current_time = time.time()

                logger.debug(f"[iOS Perf] Network raw: rx={rx_bytes}, tx={tx_bytes}")

                # 基准值存在类级别,跨 adapter 实例保留(方案B每次会销毁 adapter)
                baseline = PMD3PerformanceAdapter._net_baseline.get(self.device_id)
                if baseline:
                    last_rx, last_tx, last_time = baseline
                    time_delta = current_time - last_time
                    if time_delta > 0:
                        # 设备重启会让累积计数器归零,max(0,...) 防止出现负差分
                        rx_delta = max(0, rx_bytes - last_rx)
                        tx_delta = max(0, tx_bytes - last_tx)

                        # 转成 KB/s
                        self._cache.network_rx_kb = round((rx_delta / 1024) / time_delta, 2)
                        self._cache.network_tx_kb = round((tx_delta / 1024) / time_delta, 2)

                        logger.debug(f"[iOS Perf] Network delta: rx_kb/s={self._cache.network_rx_kb}, tx_kb/s={self._cache.network_tx_kb}")
                else:
                    logger.debug("[iOS Perf] Network: first reading, storing baseline")

                # 保存本次读数,供下次采集做差分
                PMD3PerformanceAdapter._net_baseline[self.device_id] = (rx_bytes, tx_bytes, current_time)
            else:
                logger.debug("[iOS Perf] Network: no system_data available")

            return (self._cache.network_rx_kb, self._cache.network_tx_kb)

        except Exception as e:
            logger.error(f"[iOS Perf] get_network failed: {e}")
            return (self._cache.network_rx_kb, self._cache.network_tx_kb)

    def get_init_error(self) -> Optional[str]:
        """Get initialization error message if any."""
        return self._init_error

    def _close_dvt(self):
        """Close DVT service."""
        with self._lock:
            if self._dvt:
                try:
                    self._dvt.__exit__(None, None, None)
                except Exception as e:
                    logger.debug(f"[iOS Perf] DVT close error: {e}")
                self._dvt = None
            self._lockdown = None
            self._rsd = None
            self._target_pid = None
            self._collecting_sysmon = False
            self._collecting_graphics = False

    def close(self):
        """Clean up resources."""
        self._close_dvt()
        logger.info("[iOS Perf] Adapter closed")


# Backward compatibility alias
PyiOSDeviceAdapter = PMD3PerformanceAdapter


# Keep utility functions for external use
def get_ios_version(device_id: str) -> Optional[str]:
    """Get iOS version for a device."""
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        lockdown = create_using_usbmux(serial=device_id)
        return lockdown.product_version
    except Exception as e:
        logger.error(f"[iOS Perf] Failed to get iOS version: {e}")
        return None


def check_tunnel_down(device_id: Optional[str]) -> Optional[str]:
    """检查 iOS 17+ 的 tunneld 隧道是否可用。

    返回 None 表示无需担心(设备非 iOS 17+ 走 USB,或隧道正常握着设备);
    返回一段可操作的错误提示字符串,表示隧道已断——此时 CPU/内存/FPS/GPU/网络
    会全部静默变 0,需要重启 tunneld。

    注意:此函数会做一次 usbmux/隧道查询,有百毫秒级开销。调用方应仅在采集到
    「全 0」数据时才调用它做诊断,不要放进高频 happy path。
    """
    # 非 iOS 17+ 走 USB,不依赖 tunneld,隧道列表为空也正常,直接放行。
    # 版本探测失败(设备可能已拔)时不下结论,继续查隧道。
    try:
        if not is_ios17_or_above(device_id):
            return None
    except Exception:
        pass

    try:
        from pymobiledevice3.tunneld.api import get_tunneld_devices
        devices = get_tunneld_devices()
        for rsd in devices or []:
            if device_id is None or device_id in str(rsd.udid):
                return None  # 隧道正常握着这台设备
        # tunneld 在跑但列表里没有这台设备 —— 隧道确实断了
        return (
            "tunneld 隧道已断,iOS 17+ 所有性能数据(CPU/内存/FPS/GPU/网络)会全部为 0。"
            "请重启 tunneld:sudo python3 -m pymobiledevice3 remote tunneld"
            "(设备重插/休眠或 WiFi 连接不稳时常见)"
        )
    except ImportError:
        return None
    except Exception as e:
        return (
            f"tunneld 隧道状态检查失败({type(e).__name__}: {e}),iOS 17+ 需要 tunneld 运行。"
            "请确认已执行:sudo python3 -m pymobiledevice3 remote tunneld"
        )


def is_ios17_or_above(device_id: str) -> bool:
    """Check if device is running iOS 17 or above."""
    version = get_ios_version(device_id)
    if version:
        try:
            major = int(version.split('.')[0])
            return major >= 17
        except:
            pass
    return False


def get_tunnel_rsd(device_id: str = None):
    """Get RemoteServiceDiscovery from tunneld service."""
    try:
        from pymobiledevice3.tunneld.api import get_tunneld_devices, get_tunneld_device_by_udid

        # Try to get specific device by UDID first
        if device_id:
            rsd = get_tunneld_device_by_udid(device_id)
            if rsd:
                logger.info(f"[iOS Perf] Found tunneld device: {rsd.udid}")
                return rsd

        # Fall back to getting all devices
        devices = get_tunneld_devices()
        if devices:
            for rsd in devices:
                if device_id is None or device_id in str(rsd.udid):
                    logger.info(f"[iOS Perf] Found tunneld device: {rsd.udid}")
                    return rsd
            logger.info(f"[iOS Perf] Using first tunneld device: {devices[0].udid}")
            return devices[0]
    except ImportError:
        logger.debug("[iOS Perf] tunneld API not available")
    except Exception as e:
        logger.debug(f"[iOS Perf] tunneld daemon not running: {e}")
    return None


# Backward compatibility alias
get_tunneld_rsd = get_tunnel_rsd
