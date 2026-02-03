import datetime
import re
import time
import os
import json
import sys
from loguru import logger
from typing import Optional

# 使用 pymobiledevice3 进行设备控制
try:
    from pymobiledevice3.lockdown import create_using_usbmux, LockdownClient
    from pymobiledevice3.usbmux import list_devices as pmd3_list_devices
    from pymobiledevice3.remote.remote_service_discovery import RemoteServiceDiscoveryService
    PMD3_AVAILABLE = True
except ImportError:
    PMD3_AVAILABLE = False
    create_using_usbmux = None
    LockdownClient = None
    pmd3_list_devices = None
    RemoteServiceDiscoveryService = None
    logger.warning("pymobiledevice3 not available, iOS features will be limited")
import multiprocessing
from magnax.public.ios_perf_adapter import PyiOSDeviceAdapter
from magnax.public.adb import adb
from magnax.public.common import Devices, File, Method, Platform, Scrcpy
from magnax.public.android_fps import FPSMonitor, TimeUtils

d = Devices()
f = File()
m = Method()


def get_ios_devices():
    """获取连接的iOS设备列表"""
    if not PMD3_AVAILABLE:
        logger.warning("pymobiledevice3 not available")
        return []
    try:
        devices = pmd3_list_devices()
        return devices
    except Exception as e:
        logger.error(f"Failed to list iOS devices: {e}")
        return []


def get_ios_device_udids():
    """获取连接的iOS设备UDID列表"""
    devices = get_ios_devices()
    return [d.serial for d in devices]


def get_ios_lockdown_client(device_id):
    """获取iOS设备的lockdown client用于获取设备信息"""
    if not PMD3_AVAILABLE:
        logger.warning("pymobiledevice3 not available, some iOS features may not work")
        return None
    try:
        # 使用 pymobiledevice3 创建 lockdown client
        return create_using_usbmux(serial=device_id)
    except Exception as e:
        logger.error(f"Failed to create lockdown client for device {device_id}: {e}")
        return None

class Target:
    CPU = 'cpu'
    Memory = 'memory'
    MemoryDetail = 'memory_detail'
    Battery = 'battery'
    Network = 'network'
    FPS = 'fps'
    GPU = 'gpu'
    DISK = 'disk'

class CPU(object):

    def __init__(self, pkgName, deviceId, platform=Platform.Android, pid=None):
        self.pkgName = pkgName
        self.deviceId = deviceId
        self.platform = platform
        self.pid = pid
        if self.pid is None and self.platform == Platform.Android:
            self.pid = d.getPid(pkgName=self.pkgName, deviceId=self.deviceId)[0].split(':')[0]

    def getprocessCpuStat(self):
        """get the cpu usage of a process at a certain time"""
        cmd = 'cat /proc/{}/stat'.format(self.pid)
        result = adb.shell(cmd=cmd, deviceId=self.deviceId)
        r = re.compile("\\s+")
        toks = r.split(result)
        if len(toks) < 17:
            logger.warning(f'[CPU] Invalid /proc/{self.pid}/stat output: {result[:100]}')
            return 0
        processCpu = float(toks[13]) + float(toks[14]) + float(toks[15]) + float(toks[16])
        return processCpu

    def getTotalCpuStat(self):
        """get the total cpu usage at a certain time"""
        cmd = 'cat /proc/stat |{} ^cpu'.format(d.filterType())
        result = adb.shell(cmd=cmd, deviceId=self.deviceId)
        totalCpu = 0
        lines = result.split('\n')
        lines.pop(0)
        for line in lines:
            toks = line.split()
            if toks[1] in ['', ' ']:
                toks.pop(1)
            for i in range(1, 8):
                totalCpu += float(toks[i])
        return float(totalCpu)
    
    def getCpuCoreStat(self):
        """get the core cpu usage at a certain time"""
        cmd = 'cat /proc/stat |{} ^cpu'.format(d.filterType())
        result = adb.shell(cmd=cmd, deviceId=self.deviceId)
        coreCpu = 0
        coreCpuList = []
        lines = result.split('\n')
        lines.pop(0)
        for line in lines:
            toks = line.split()
            if toks[1] in ['', ' ']:
                toks.pop(1)
            for i in range(1, 8):
                coreCpu += float(toks[i])
            coreCpuList.append(coreCpu)
            coreCpu = 0
        return coreCpuList
    
    def getCoreIdleCpuStat(self):
        """get the core idel cpu usage at a certain time"""
        cmd = 'cat /proc/stat |{} ^cpu'.format(d.filterType())
        result = adb.shell(cmd=cmd, deviceId=self.deviceId)
        idleCpuList = []
        idleCpu = 0
        lines = result.split('\n')
        lines.pop(0)
        for line in lines:
            toks = line.split()
            if toks[1] in ['', ' ']:
                toks.pop(1)
            idleCpu += float(toks[4])
            idleCpuList.append(idleCpu)
            idleCpu = 0
        return idleCpuList
    
    def getIdleCpuStat(self):
        """get the total cpu usage at a certain time"""
        cmd = 'cat /proc/stat |{} ^cpu'.format(d.filterType())
        result = adb.shell(cmd=cmd, deviceId=self.deviceId)
        idleCpu = 0
        lines = result.split('\n')
        lines.pop(0)
        for line in lines:
            toks = line.split()
            if toks[1] in ['', ' ']:
                toks.pop(1)
            idleCpu += float(toks[4])
        return idleCpu
    
    def getCoreCpuRate(self, cores=0,noLog=False):
        coreCpuRateList = []
        try:
            processCpuTime_1 = self.getprocessCpuStat()
            coreCpuTotalTime_List1 = self.getCpuCoreStat()
            time.sleep(1)
            processCpuTime_2 = self.getprocessCpuStat()
            coreCpuTotalTime_List2 = self.getCpuCoreStat()
            for i in range(len(coreCpuTotalTime_List1)):
                divisor = coreCpuTotalTime_List2[i] - coreCpuTotalTime_List1[i]
                if divisor == 0:
                    coreCpuRateList.append(0.0)
                    continue
                coreCpuRate = round(float((processCpuTime_2 - processCpuTime_1) / divisor * 100), 2)
                if cores > 0:
                    coreCpuRate /= cores
                coreCpuRate = round(float(coreCpuRate), 2)
                coreCpuRateList.append(coreCpuRate)
                if noLog is False:
                    apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
                    f.add_log(os.path.join(f.report_dir,'cpu{}.log'.format(i)), apm_time, coreCpuRate)
        except Exception as e:
            if len(d.getPid(self.deviceId, self.pkgName)) == 0:
                logger.error('[CPU Core] {} : No process found'.format(self.pkgName))
            else:
                logger.exception(e)
        return coreCpuRateList    

    def getAndroidCpuRate(self, noLog=False):
        """get the Android cpu rate of a process"""
        try:
            processCpuTime_1 = self.getprocessCpuStat()
            totalCpuTime_1 = self.getTotalCpuStat()
            idleCputime_1 = self.getIdleCpuStat()
            time.sleep(1)
            processCpuTime_2 = self.getprocessCpuStat()
            totalCpuTime_2 = self.getTotalCpuStat()
            idleCputime_2 = self.getIdleCpuStat()
            appCpuRate = round(float((processCpuTime_2 - processCpuTime_1) / (totalCpuTime_2 - totalCpuTime_1) * 100), 2)
            sysCpuRate = round(float(((totalCpuTime_2 - idleCputime_2) - (totalCpuTime_1 - idleCputime_1)) / (totalCpuTime_2 - totalCpuTime_1) * 100), 2)
            if noLog is False:
                apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
                f.add_log(os.path.join(f.report_dir,'cpu_app.log'), apm_time, appCpuRate)
                f.add_log(os.path.join(f.report_dir,'cpu_sys.log'), apm_time, sysCpuRate)
        except Exception as e:
            appCpuRate, sysCpuRate = 0, 0
            if len(d.getPid(self.deviceId, self.pkgName)) == 0:
                logger.error('[CPU] {} : No process found'.format(self.pkgName))
            else:
                logger.exception(e)
        return appCpuRate, sysCpuRate

    def getiOSCpuRate(self, noLog=False):
        """get the iOS cpu rate of a process, unit:%"""
        apm = iosPerformance(self.pkgName, self.deviceId)
        appCpuRate = round(float(apm.getPerformance(apm.cpu)[0]), 2)
        sysCpuRate = round(float(apm.getPerformance(apm.cpu)[1]), 2)
        if noLog is False:
            apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
            f.add_log(os.path.join(f.report_dir,'cpu_app.log'), apm_time, appCpuRate)
            f.add_log(os.path.join(f.report_dir,'cpu_sys.log'), apm_time, sysCpuRate)
        return appCpuRate, sysCpuRate

    def getCpuRate(self, noLog=False):
        """Get the cpu rate of a process, unit:%"""
        appCpuRate, systemCpuRate = self.getAndroidCpuRate(noLog) if self.platform == Platform.Android else self.getiOSCpuRate(noLog)
        return appCpuRate, systemCpuRate    

class Memory(object):
    def __init__(self, pkgName, deviceId, platform=Platform.Android, pid=None):
        self.pkgName = pkgName
        self.deviceId = deviceId
        self.platform = platform
        self.pid = pid
        if self.pid is None and self.platform == Platform.Android:
            self.pid = d.getPid(pkgName=self.pkgName, deviceId=self.deviceId)[0].split(':')[0]

    def getAndroidMemory(self):
        """Get the Android memory ,unit:MB"""
        try:
            cmd = 'dumpsys meminfo {}'.format(self.pid)
            output = adb.shell(cmd=cmd, deviceId=self.deviceId)
            m_total = re.search(r'TOTAL\s*(\d+)', output)
            if not m_total:
                m_total = re.search(r'TOTAL PSS:\s*(\d+)', output)
            m_swap = re.search(r'TOTAL SWAP PSS:\s*(\d+)', output)
            if not m_swap:
                m_swap = re.search(r'TOTAL SWAP \(KB\):\s*(\d+)', output)
            totalPass = round(float(float(m_total.group(1))) / 1024, 2)
            swapPass = round(float(float(m_swap.group(1))) / 1024, 2)
        except Exception as e:
            totalPass, swapPass= 0, 0
            if len(d.getPid(self.deviceId, self.pkgName)) == 0:
                logger.error('[Memory] {} : No process found'.format(self.pkgName))
            else:
                logger.exception(e)
        return totalPass, swapPass
    
    def getAndroidMemoryDetail(self, noLog=False):
        """Get the Android detail memory ,unit:MB"""
        try:
            cmd = 'dumpsys meminfo {}'.format(self.pid)
            output = adb.shell(cmd=cmd, deviceId=self.deviceId)
            m_java = re.search(r'Java Heap:\s*(\d+)', output)
            m_native = re.search(r'Native Heap:\s*(\d+)', output)
            m_code = re.search(r'Code:\s*(\d+)', output)
            m_stack = re.search(r'Stack:\s*(\d+)', output)
            m_graphics = re.search(r'Graphics:\s*(\d+)', output)
            m_private = re.search(r'Private Other:\s*(\d+)', output)
            m_system = re.search(r'System:\s*(\d+)', output)
            java_heap = round(float(float(m_java.group(1))) / 1024, 2)
            native_heap = round(float(float(m_native.group(1))) / 1024, 2)
            code_pss = round(float(float(m_code.group(1))) / 1024, 2)
            stack_pss = round(float(float(m_stack.group(1))) / 1024, 2)
            graphics_pss = round(float(float(m_graphics.group(1))) / 1024, 2)
            private_pss = round(float(float(m_private.group(1))) / 1024, 2)
            system_pss = round(float(float(m_system.group(1))) / 1024, 2)
            memory_dict = dict(
                java_heap=java_heap,
                native_heap=native_heap,
                code_pss=code_pss,
                stack_pss=stack_pss,
                graphics_pss=graphics_pss,
                private_pss=private_pss,
                system_pss=system_pss
            )
            if noLog is False:
                apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
                f.add_log(os.path.join(f.report_dir,'mem_java_heap.log'), apm_time, memory_dict.get('java_heap'))
                f.add_log(os.path.join(f.report_dir,'mem_native_heap.log'), apm_time, memory_dict.get('native_heap'))
                f.add_log(os.path.join(f.report_dir,'mem_code_pss.log'), apm_time, memory_dict.get('code_pss'))
                f.add_log(os.path.join(f.report_dir,'mem_stack_pss.log'), apm_time, memory_dict.get('stack_pss'))
                f.add_log(os.path.join(f.report_dir,'mem_graphics_pss.log'), apm_time, memory_dict.get('graphics_pss'))
                f.add_log(os.path.join(f.report_dir,'mem_private_pss.log'), apm_time, memory_dict.get('private_pss'))
                f.add_log(os.path.join(f.report_dir,'mem_system_pss.log'), apm_time, memory_dict.get('system_pss'))
        except Exception as e:
            memory_dict = dict(
                java_heap=0,
                native_heap=0,
                code_pss=0,
                stack_pss=0,
                graphics_pss=0,
                private_pss=0,
                system_pss=0
            )
            if len(d.getPid(self.deviceId, self.pkgName)) == 0:
                logger.error('[Memory Detail] {} : No process found'.format(self.pkgName))
            else:
                logger.exception(e)
        return memory_dict

    def getiOSMemory(self):
        """Get the iOS memory"""
        apm = iosPerformance(self.pkgName, self.deviceId)
        totalPass = round(float(apm.getPerformance(apm.memory)), 2)
        swapPass = 0
        return totalPass, swapPass

    def getProcessMemory(self, noLog=False):
        """Get the app memory"""
        totalPass, swapPass = self.getAndroidMemory() if self.platform == Platform.Android else self.getiOSMemory()
        if noLog is False:
            apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
            f.add_log(os.path.join(f.report_dir,'mem_total.log'), apm_time, totalPass)
            if self.platform == Platform.Android:
                f.add_log(os.path.join(f.report_dir,'mem_swap.log'), apm_time, swapPass)
        return totalPass, swapPass

class Battery(object):
    def __init__(self, deviceId, platform=Platform.Android):
        self.deviceId = deviceId
        self.platform = platform

    def getBattery(self, noLog=False):
        if self.platform == Platform.Android:
            level, temperature = self.getAndroidBattery(noLog)
            return level, temperature
        else:
            temperature, current, voltage, power = self.getiOSBattery(noLog)
            return temperature, current, voltage, power

    def getAndroidBattery(self, noLog=False):
        """Get android battery info, unit:%"""
        # Switch mobile phone battery to non-charging state
        self.recoverBattery()
        cmd = 'dumpsys battery set status 1'
        adb.shell(cmd=cmd, deviceId=self.deviceId)
        # Get phone battery info
        cmd = 'dumpsys battery'
        output = adb.shell(cmd=cmd, deviceId=self.deviceId)
        level = int(re.findall(u'level:\s?(\d+)', output)[0])
        temperature = int(re.findall(u'temperature:\s?(\d+)', output)[0]) / 10
        if noLog is False:
             apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
             f.add_log(os.path.join(f.report_dir,'battery_level.log'), apm_time, level)
             f.add_log(os.path.join(f.report_dir,'battery_tem.log'), apm_time, temperature)
        return level, temperature

    def getiOSBattery(self, noLog=False):
        """Get ios battery info, unit:%"""
        try:
            # 使用 pymobiledevice3 获取电池信息
            lockdown_client = get_ios_lockdown_client(self.deviceId)
            if lockdown_client is None:
                logger.error("Failed to get lockdown client for iOS battery info")
                return 0, 0, 0, 0

            # Use DiagnosticsService.get_battery() - works without tunnel
            from pymobiledevice3.services.diagnostics import DiagnosticsService
            diagnostics = DiagnosticsService(lockdown_client)

            try:
                battery_info = diagnostics.get_battery()
            except Exception as e:
                logger.warning(f"DiagnosticsService.get_battery() failed: {e}")
                return 0, 0, 0, 0

            if not battery_info:
                logger.warning("Battery information not available")
                return 0, 0, 0, 0

            # Extract battery metrics from the response
            # Temperature - check multiple possible keys
            temperature = (battery_info.get('Temperature', 0) or
                          battery_info.get('BatteryData', {}).get('AlgoTemperature', 0) / 10000)
            tem = m._setValue(temperature / 100 if temperature > 100 else temperature)

            # Current (mA) - use Amperage or InstantAmperage
            current = abs(battery_info.get('Amperage', 0) or
                         battery_info.get('InstantAmperage', 0))
            current = m._setValue(current)

            # Voltage (mV) - use AppleRawBatteryVoltage
            voltage = (battery_info.get('AppleRawBatteryVoltage', 0) or
                      battery_info.get('Voltage', 0))
            voltage = m._setValue(voltage)

            # Power (mW)
            power = current * voltage / 1000 if current and voltage else 0

            if noLog is False:
                apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
                f.add_log(os.path.join(f.report_dir,'battery_tem.log'), apm_time, tem)
                f.add_log(os.path.join(f.report_dir,'battery_current.log'), apm_time, current)
                f.add_log(os.path.join(f.report_dir,'battery_voltage.log'), apm_time, voltage)
                f.add_log(os.path.join(f.report_dir,'battery_power.log'), apm_time, power)

            return tem, current, voltage, power

        except Exception as e:
            logger.error(f"Failed to get iOS battery info: {e}")
            # 返回默认值以避免程序崩溃
            return 0, 0, 0, 0

    def recoverBattery(self):
        """Reset phone charging status"""
        cmd = 'dumpsys battery reset'
        adb.shell(cmd=cmd, deviceId=self.deviceId)

class Network(object):

    def __init__(self, pkgName, deviceId, platform=Platform.Android, pid=None):
        self.pkgName = pkgName
        self.deviceId = deviceId
        self.platform = platform
        self.pid = pid
        if self.pid is None and self.platform == Platform.Android:
            self.pid = d.getPid(pkgName=self.pkgName, deviceId=self.deviceId)[0].split(':')[0]

    def getAndroidNet(self, wifi=True):
        """Get Android send/recv data, unit:KB wlan0/rmnet_ipa0"""
        try:
            if wifi is True:
                net = 'wlan0'
                adb.shell(cmd='svc wifi enable', deviceId=self.deviceId)
            else:
                net = 'rmnet_ipa0'
                adb.shell(cmd='svc wifi disable', deviceId=self.deviceId)
                adb.shell(cmd='svc data enable', deviceId=self.deviceId)
            cmd = 'cat /proc/{}/net/dev |{} {}'.format(self.pid, d.filterType(), net)
            output_pre = adb.shell(cmd=cmd, deviceId=self.deviceId)
            m_pre = re.search(r'{}:\s*(\d+)\s*\d+\s*\d+\s*\d+\s*\d+\s*\d+\s*\d+\s*\d+\s*(\d+)'.format(net), output_pre)
            sendNum_pre = round(float(float(m_pre.group(2)) / 1024), 2)
            recNum_pre = round(float(float(m_pre.group(1)) / 1024), 2)
            time.sleep(0.5)
            output_final = adb.shell(cmd=cmd, deviceId=self.deviceId)
            m_final = re.search(r'{}:\s*(\d+)\s*\d+\s*\d+\s*\d+\s*\d+\s*\d+\s*\d+\s*\d+\s*(\d+)'.format(net), output_final)
            sendNum_final = round(float(float(m_final.group(2)) / 1024), 2)
            recNum_final = round(float(float(m_final.group(1)) / 1024), 2)
            sendNum = round(float(sendNum_final - sendNum_pre), 2)
            recNum = round(float(recNum_final - recNum_pre), 2)
        except Exception as e:
            sendNum, recNum = 0, 0
            if len(d.getPid(self.deviceId, self.pkgName)) == 0:
                logger.error('[Network] {} : No process found'.format(self.pkgName))
            else:
                logger.exception(e)
        return sendNum, recNum

    def setAndroidNet(self, wifi=True):
        try:
            if wifi is True:
                net = 'wlan0'
                adb.shell(cmd='svc wifi enable', deviceId=self.deviceId)
            else:
                net = 'rmnet_ipa0'
                adb.shell(cmd='svc wifi disable', deviceId=self.deviceId)
                adb.shell(cmd='svc data enable', deviceId=self.deviceId)
            cmd = f'cat /proc/{self.pid}/net/dev |{d.filterType()} {net}'
            output_pre = adb.shell(cmd=cmd, deviceId=self.deviceId)
            m = re.search(r'{}:\s*(\d+)\s*\d+\s*\d+\s*\d+\s*\d+\s*\d+\s*\d+\s*\d+\s*(\d+)'.format(net), output_pre)    
            sendNum = round(float(float(m.group(2)) / 1024), 2)
            recNum = round(float(float(m.group(1)) / 1024), 2)
        except Exception as e:
            sendNum, recNum = 0, 0
            if len(d.getPid(self.deviceId, self.pkgName)) == 0:
                logger.error('[Network] {} : No process found'.format(self.pkgName))
            else:
                logger.exception(e)
        return sendNum, recNum


    def getiOSNet(self):
        """Get iOS upflow and downflow data"""
        apm = iosPerformance(self.pkgName, self.deviceId)
        apm_data = apm.getPerformance(apm.network)
        sendNum = round(float(apm_data[1]), 2)
        recNum = round(float(apm_data[0]), 2)
        return sendNum, recNum

    def getNetWorkData(self, wifi=True, noLog=False):
        """Get the upflow and downflow data, unit:KB"""
        sendNum, recNum = self.getAndroidNet(wifi) if self.platform == Platform.Android else self.getiOSNet()
        if noLog is False:
            apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
            f.add_log(os.path.join(f.report_dir,'upflow.log'), apm_time, sendNum)
            f.add_log(os.path.join(f.report_dir,'downflow.log'), apm_time, recNum)
        return sendNum, recNum

class FPS(object):
    AndroidFPS = None

    @classmethod
    def getObject(cls, *args, **kwargs):
        if kwargs['platform'] == Platform.Android:
            if cls.AndroidFPS is None:
                cls.AndroidFPS = FPS(*args, **kwargs)
            return cls.AndroidFPS
        return FPS(*args, **kwargs)

    @classmethod
    def clear(cls):
        if cls.AndroidFPS is not None and cls.AndroidFPS.monitors is not None:
            logger.info('[FPS] Stopping FPS monitor')
            cls.AndroidFPS.monitors.stop()
            cls.AndroidFPS.monitor_started = False
        cls.AndroidFPS = None

    def __init__(self, pkgName, deviceId, platform=Platform.Android, surfaceview=True):
        self.pkgName = pkgName
        self.deviceId = deviceId
        self.platform = platform
        self.surfaceview = surfaceview
        self.apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
        self.monitors = None
        self.monitor_started = False
    
    def getAndroidFps(self, noLog=False):
        """get Android Fps, unit:HZ"""
        try:
            # 如果监控器未启动，则初始化并启动
            if not self.monitor_started or self.monitors is None:
                logger.info(f'[FPS] Initializing FPS monitor for {self.pkgName}')
                self.monitors = FPSMonitor(device_id=self.deviceId, package_name=self.pkgName, frequency=1,
                                          surfaceview=self.surfaceview, start_time=TimeUtils.getCurrentTimeUnderline())
                self.monitors.start()
                self.monitor_started = True
                
                # 初次启动需要等待一段时间让收集器收集足够的数据
                import time
                time.sleep(3)  # 等待3秒确保有足够的数据点
                logger.info(f'[FPS] FPS monitor initialized for {self.pkgName}')
            
            # 从持久化的监控器获取当前FPS数据
            # 使用全局变量，这些变量由监控器实时更新
            from magnax.public.android_fps import collect_fps, collect_jank
            fps = collect_fps
            jank = collect_jank
            
            if noLog is False:
                apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
                f.add_log(os.path.join(f.report_dir,'fps.log'), apm_time, fps)
                f.add_log(os.path.join(f.report_dir,'jank.log'), apm_time, jank)
            
            logger.debug(f'[FPS] {self.pkgName}: fps={fps}, jank={jank}')
        except Exception as e:
            fps, jank = 0, 0
            if len(d.getPid(self.deviceId, self.pkgName)) == 0:
                logger.error('[FPS] {} : No process found'.format(self.pkgName))
            else:
                logger.error('[FPS] {} : Failed to get FPS data - {}'.format(self.pkgName, str(e)))
                # 如果监控器出错，尝试重置以便下次重新初始化
                if self.monitors is not None:
                    try:
                        self.monitors.stop()
                    except:
                        pass
                    self.monitors = None
                    self.monitor_started = False
                    logger.warning('[FPS] FPS monitor reset due to error, will reinitialize on next call')
                logger.exception(e)        
        return fps, jank
    
    def getiOSFps(self, noLog=False):
        """get iOS Fps"""
        apm = iosPerformance(self.pkgName, self.deviceId)
        fps = int(apm.getPerformance(apm.fps))
        if noLog is False:
            apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
            f.add_log(os.path.join(f.report_dir,'fps.log'), apm_time, fps)
        return fps, 0

    def getFPS(self, noLog=False):
        """get fps、jank"""
        fps, jank = self.getAndroidFps(noLog) if self.platform == Platform.Android else self.getiOSFps(noLog)
        return fps, jank
    
    def stopMonitor(self):
        """停止FPS监控器"""
        if self.monitors is not None and self.monitor_started:
            logger.info(f'[FPS] Stopping FPS monitor for {self.pkgName}')
            self.monitors.stop()
            self.monitor_started = False
            self.monitors = None

class GPU(object):
    def __init__(self, pkgName, deviceId, platform=Platform.Android):
        self.pkgName = pkgName
        self.deviceId = deviceId
        self.platform = platform

    def getAndroidGpuRate(self):
        try:
            cmd = 'cat /sys/class/kgsl/kgsl-3d0/gpubusy'
            result = adb.shell(cmd=cmd, deviceId=self.deviceId)
            
            # 检查是否有错误或权限问题
            if not result or result.strip() == '' or 'No such file' in result or 'Permission denied' in result or 'Operation not permitted' in result:
                logger.warning(f'[GPU] kgsl方法获取失败，结果: {result}')
                return self._getGpuRateFallback()
            
            # 验证数据格式
            parts = result.strip().split(' ')
            if len(parts) < 2:
                logger.warning(f'[GPU] kgsl数据格式错误: {result}')
                return self._getGpuRateFallback()
            
            # 验证数据是否为有效数字
            try:
                part1 = parts[0].strip()
                part2 = parts[1].strip()
                
                if part1 == '' or part2 == '':
                    logger.warning(f'[GPU] kgsl数据包含空值: part1="{part1}", part2="{part2}"')
                    return self._getGpuRateFallback()
                
                val1 = int(part1)
                val2 = int(part2)
                
                if val2 == 0:
                    logger.warning('[GPU] kgsl除数为0')
                    return self._getGpuRateFallback()
                
                gpu = round(float(val1 / val2) * 100, 2)
                logger.debug(f'[GPU] kgsl获取成功: {gpu}% (busy={val1}, total={val2})')
                return gpu
                
            except ValueError as e:
                logger.warning(f'[GPU] kgsl数据解析失败: {e}, 原始数据: {result}')
                return self._getGpuRateFallback()
                
        except Exception as e:
            logger.error(f'[GPU] kgsl方法异常: {e}')
            return self._getGpuRateFallback()
    
    def _getGpuRateFallback(self):
        """GPU获取失败时的备用方案"""
        try:
            # 尝试其他GPU获取方法
            cmd = 'cat /proc/gpuinfo'
            result = adb.shell(cmd=cmd, deviceId=self.deviceId)
            
            if result and 'No such file' not in result and 'Permission denied' not in result:
                logger.debug(f'[GPU] 备用方法gpuinfo结果: {result[:100]}...')
                # 这里可以解析其他格式的GPU数据
                # 暂时返回0作为安全值
                
        except Exception as e:
            logger.debug(f'[GPU] 备用方法失败: {e}')
        
        # 返回默认值0，表示GPU数据不可用
        logger.warning('[GPU] 所有GPU获取方法都失败，返回默认值0')
        return 0.0

    def getiOSGpuRate(self):
        try:
            apm = iosPerformance(self.pkgName, self.deviceId)
            gpu = apm.getPerformance(apm.gpu)
            return gpu
        except Exception as e:
            logger.error(f'[GPU] iOS GPU获取失败: {e}')
            return 0.0

    def getGPU(self, noLog=False):
        try:
            gpu = self.getAndroidGpuRate() if self.platform == Platform.Android else self.getiOSGpuRate()
            
            # 确保返回值是有效的数字
            if not isinstance(gpu, (int, float)) or gpu < 0 or gpu > 100:
                logger.warning(f'[GPU] 获取到无效数值: {gpu}，使用默认值0')
                gpu = 0.0
            
            if noLog is False:
                apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
                f.add_log(os.path.join(f.report_dir,'gpu.log'), apm_time, gpu)
            return gpu
        except Exception as e:
            logger.error(f'[GPU] 获取GPU数据时发生异常: {e}')
            if noLog is False:
                apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
                f.add_log(os.path.join(f.report_dir,'gpu.log'), apm_time, 0.0)
            return 0.0

class Disk(object):
    def __init__(self, deviceId, platform=Platform.Android):
        self.deviceId = deviceId
        self.platform = platform

    def setInitialDisk(self):
        disk_info = adb.shell(cmd='df', deviceId=self.deviceId)
        with open(os.path.join(f.report_dir,'initail_disk.log'), 'a+', encoding="utf-8") as file:
                file.write(disk_info)

    def setCurrentDisk(self):
        disk_info = adb.shell(cmd='df', deviceId=self.deviceId)
        with open(os.path.join(f.report_dir,'current_disk.log'), 'a+', encoding="utf-8") as file:
                file.write(disk_info)
    
    def getAndroidDisk(self):
        disk_info = adb.shell(cmd='df', deviceId=self.deviceId)
        disk_lines = disk_info.splitlines()
        disk_lines.pop(0)
        size_list = list()
        used_list = list()
        free_list = list()
        for line in disk_lines:
            disk_value_list = line.split()
            size_list.append(int(disk_value_list[1]))
            used_list.append(int(disk_value_list[2]))
            free_list.append(int(disk_value_list[3]))
        sum_size = sum(size_list)    
        sum_used = sum(used_list)
        sum_free = sum(free_list)
        disk_dict = {'disk_size':sum_size, 'used':sum_used, 'free': sum_free}
        return disk_dict

    def getiOSDisk(self):
        try:
            # 使用pymobiledevice3获取存储信息
            lockdown_client = get_ios_lockdown_client(self.deviceId)
            if lockdown_client is None:
                logger.debug("Failed to get lockdown client for iOS disk info")
                return {'used': 0, 'free': 0, 'total': 0}

            # 尝试从lockdown获取磁盘信息
            device_info = lockdown_client.all_values

            total_capacity = device_info.get('TotalDiskCapacity', 0)
            total_data_capacity = device_info.get('TotalDataCapacity', 0)
            total_data_available = device_info.get('TotalDataAvailable', 0)

            # 如果lockdown没有磁盘信息，尝试通过sysmon获取IO统计
            if total_capacity == 0:
                import subprocess
                disk_read = 0
                disk_write = 0
                try:
                    result = subprocess.run(
                        ['python3', '-m', 'pymobiledevice3', 'developer', 'dvt', 'sysmon', 'system',
                         '--tunnel', '', '--udid', self.deviceId],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            if ':' in line:
                                key, value = line.split(':', 1)
                                key = key.strip()
                                value = value.strip()
                                if key == 'diskBytesRead':
                                    disk_read = int(value)
                                elif key == 'diskBytesWritten':
                                    disk_write = int(value)

                        if disk_read > 0 or disk_write > 0:
                            # 返回IO统计（无法获取实际容量）
                            return {
                                'total': 0,
                                'used': round((disk_read + disk_write) / (1024 * 1024 * 1024), 2),
                                'free': 0,
                                'disk_read_gb': round(disk_read / (1024 * 1024 * 1024), 2),
                                'disk_write_gb': round(disk_write / (1024 * 1024 * 1024), 2)
                            }
                except Exception:
                    pass

                return {'used': 0, 'free': 0, 'total': 0}

            # 计算已用空间
            used_capacity = total_data_capacity - total_data_available

            disk_dict = {
                'total': round(total_capacity / (1024 * 1024 * 1024), 2),
                'used': round(used_capacity / (1024 * 1024 * 1024), 2),
                'free': round(total_data_available / (1024 * 1024 * 1024), 2)
            }

            return disk_dict

        except Exception as e:
            logger.debug(f"Failed to get iOS disk info: {e}")
            return {'used': 0, 'free': 0, 'total': 0}
    
    def getDisk(self, noLog=False):
        disk = self.getAndroidDisk() if self.platform == Platform.Android else self.getiOSDisk()
        if noLog is False:
            apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
            f.add_log(os.path.join(f.report_dir,'disk_used.log'), apm_time, disk.get('used'))
            f.add_log(os.path.join(f.report_dir,'disk_free.log'), apm_time, disk.get('free'))
        return disk    

class ThermalSensor(object):
    def __init__(self, deviceId, platform=Platform.Android):
        self.deviceId = deviceId
        self.platform = platform

    def setInitalThermalTemp(self):
        temp_list = list()
        typeLength = len(self.getThermalType())
        if typeLength > 3:
            for i in range(len(self.getThermalType())):
                cmd = 'cat /sys/class/thermal/thermal_zone{}/temp'.format(i)
                temp = adb.shell(cmd=cmd, deviceId=self.deviceId)
                temp_dict = {
                    'type':self.getThermalType()[i],
                    'temp':temp
                }
                temp_list.append(temp_dict)
            content = json.dumps(temp_list)
            f.create_file(filename='init_thermal_temp.json', content=content)
    
    def setCurrentThermalTemp(self):
        temp_list = list()
        typeLength = len(self.getThermalType())
        if typeLength > 3:
            for i in range(len(self.getThermalType())):
                cmd = 'cat /sys/class/thermal/thermal_zone{}/temp'.format(i)
                temp = adb.shell(cmd=cmd, deviceId=self.deviceId)
                temp_dict = {
                    'type':self.getThermalType()[i],
                    'temp':temp
                }
                temp_list.append(temp_dict)
            content = json.dumps(temp_list)
            f.create_file(filename='current_thermal_temp.json', content=content)

    def getThermalType(self):
        cmd = 'cat /sys/class/thermal/thermal_zone*/type'
        result = adb.shell(cmd=cmd, deviceId=self.deviceId)
        typeList = result.splitlines()
        return typeList

    def getThermalTemp(self):
        temp_list = list()
        typeLength = len(self.getThermalType())
        if typeLength > 3:
            for i in range(len(self.getThermalType())):
                cmd = 'cat /sys/class/thermal/thermal_zone{}/temp'.format(i)
                temp = adb.shell(cmd=cmd, deviceId=self.deviceId)
                temp_dict = {
                    'type':self.getThermalType()[i],
                    'temp':temp
                }
                temp_list.append(temp_dict)
            return temp_list 
        else:
            logger.exception('No permission')     

class Energy(object):
    def __init__(self, deviceId, packageName):
        self.deviceId = deviceId
        self.packageName = packageName
    
    def _complete_udid(self, udid: Optional[str] = None) -> str:
        """获取完整的设备UDID"""
        try:
            device_udids = get_ios_device_udids()

            # Find udid exactly match
            if udid in device_udids:
                return udid

            if udid:
                logger.error("Device for %s not detected" % udid)
                return ""

            if len(device_udids) == 1:
                return device_udids[0]

            # 简化逻辑，不再区分连接类型
            if len(device_udids) >= 2:
                logger.warning("More than 2 USB devices detected, using first one")
                return device_udids[0]
            if len(device_udids) == 0:
                logger.error("No local device detected")
                return ""

            return device_udids[0]
        except Exception as e:
            logger.error(f"Failed to get device UDID: {e}")
            return ""

    def _get_lockdown_client(self, udid: Optional[str] = None):
        """获取设备的lockdown client"""
        _udid = self._complete_udid(udid)
        if not _udid:
            return None
        
        if _udid != udid:
            logger.debug("AutoComplete udid %s", _udid)
        
        return get_ios_lockdown_client(_udid)

    def getEnergy(self):
        """获取iOS应用能耗信息 - 通过电池信息估算"""
        # 默认返回值（兼容API期望的格式）
        default_result = {
            "energy.overhead": 0,
            "energy.version": 0,
            "energy.gpu.cost": 0,
            "energy.cpu.cost": 0,
            "energy.appstate.cost": 0,
            "energy.thermalstate.cost": 0,
            "energy.networking.cost": 0,
            "energy.cost": 0,
            "energy.display.cost": 0,
            "energy.location.cost": 0,
        }

        try:
            lockdown_client = self._get_lockdown_client(self.deviceId)
            if lockdown_client is None:
                logger.debug("Failed to get lockdown client for energy monitoring")
                return default_result

            # 使用DiagnosticsService获取电池功率作为能耗估算
            from pymobiledevice3.services.diagnostics import DiagnosticsService
            diagnostics = DiagnosticsService(lockdown_client)

            try:
                battery_info = diagnostics.get_battery()
                if battery_info:
                    # 计算功率 (mW)
                    voltage = battery_info.get('AppleRawBatteryVoltage', 0)  # mV
                    current = abs(battery_info.get('Amperage', 0))  # mA
                    power = (voltage * current) / 1000  # mW

                    # 返回兼容API的格式，将总功率作为energy.cost
                    return {
                        "energy.overhead": 0,
                        "energy.version": 1,
                        "energy.gpu.cost": 0,
                        "energy.cpu.cost": 0,
                        "energy.appstate.cost": 0,
                        "energy.thermalstate.cost": 0,
                        "energy.networking.cost": 0,
                        "energy.cost": round(power, 2),  # 总功率 mW
                        "energy.display.cost": 0,
                        "energy.location.cost": 0,
                        "voltage": voltage,
                        "current": current,
                    }
            except Exception as e:
                logger.debug(f"Energy calculation failed: {e}")

            return default_result

        except Exception as e:
            logger.debug(f"Failed to get iOS energy info: {e}")
            return default_result
          
class DataType:
    """Performance data types for iOS monitoring."""
    CPU = 'cpu'
    MEMORY = 'memory'
    NETWORK = 'network'
    FPS = 'fps'
    GPU = 'gpu'


class iosPerformance(object):
    """
    iOS Performance Monitor using py-ios-device.

    This class provides a unified interface for collecting iOS performance metrics
    including CPU, Memory, FPS, GPU, and Network data.
    """

    def __init__(self, pkgName, deviceId):
        self.pkgName = pkgName
        self.deviceId = deviceId
        self.apm_time = datetime.datetime.now().strftime('%H:%M:%S.%f')
        self.cpu = DataType.CPU
        self.memory = DataType.MEMORY
        self.network = DataType.NETWORK
        self.fps = DataType.FPS
        self.gpu = DataType.GPU
        self._adapter = None

    def _get_adapter(self) -> PyiOSDeviceAdapter:
        """Get or create the PyiOSDeviceAdapter instance."""
        if self._adapter is None:
            self._adapter = PyiOSDeviceAdapter(self.deviceId, self.pkgName)
        return self._adapter

    def getPerformance(self, perfType: str):
        """
        Get performance data for the specified type.

        Args:
            perfType: One of DataType.CPU, DataType.MEMORY, DataType.NETWORK,
                     DataType.FPS, or DataType.GPU

        Returns:
            Performance data in the format expected by the caller:
            - CPU: (app_cpu%, sys_cpu%)
            - Memory: float (MB)
            - FPS: int
            - GPU: float (%)
            - Network: (download_kb, upload_kb)
        """
        try:
            adapter = self._get_adapter()

            if perfType == DataType.CPU:
                return adapter.get_cpu()
            elif perfType == DataType.MEMORY:
                return adapter.get_memory()
            elif perfType == DataType.FPS:
                return adapter.get_fps()
            elif perfType == DataType.GPU:
                return adapter.get_gpu()
            elif perfType == DataType.NETWORK:
                return adapter.get_network()
            else:
                logger.warning(f"[iOS Perf] Unknown performance type: {perfType}")
                return 0

        except Exception as e:
            logger.error(f"[iOS Perf] Failed to get {perfType} data: {e}")
            # Return default values based on performance type
            if perfType == DataType.NETWORK:
                return 0.0, 0.0
            elif perfType == DataType.CPU:
                return 0.0, 0.0
            else:
                return 0

    def close(self):
        """Clean up resources."""
        if self._adapter:
            self._adapter.close()
            self._adapter = None

class initPerformanceService(object):
    CONFIG_DIR = os.path.dirname(os.path.realpath(__file__))
    CONIFG_PATH = os.path.join(CONFIG_DIR, 'config.json')

    @classmethod
    def get_status(cls):
        config_json = open(file=cls.CONIFG_PATH, mode='r').read()
        run_switch = json.loads(config_json).get('run_switch')
        return run_switch
    
    @classmethod
    def start(cls):
        config_json = dict()
        config_json['run_switch'] = 'on'
        with open(cls.CONIFG_PATH, "w") as file:
            json.dump(config_json, file)

    @classmethod
    def stop(cls):
        config_json = dict()
        config_json['run_switch'] = 'off'
        with open(cls.CONIFG_PATH, "w") as file:
            json.dump(config_json, file) 
        logger.info('stop solox success')    
        return True           

class AppPerformanceMonitor(initPerformanceService):
    """for python api"""

    def __init__(self, pkgName=None, platform=Platform.Android, deviceId=None,
                 surfaceview=True, noLog=True, pid=None, record=False, collect_all=False,
                 duration=0):
        self.pkgName = pkgName
        self.deviceId = deviceId
        self.platform = platform
        self.surfaceview = surfaceview
        self.noLog = noLog
        self.pid = pid
        self.record = record
        self.collect_all = collect_all
        self.duration = duration
        self.end_time = time.time() + self.duration
        d.devicesCheck(platform=self.platform, deviceid=self.deviceId, pkgname=self.pkgName)
        self.start()
    
    def collectCpu(self):
        _cpu = CPU(self.pkgName, self.deviceId, self.platform, pid=self.pid)
        result = {}
        while self.get_status() == 'on':
            appCpuRate, systemCpuRate = _cpu.getCpuRate(noLog=self.noLog)
            result = {'appCpuRate': appCpuRate, 'systemCpuRate': systemCpuRate}
            logger.info(f'cpu: {result}')
            if self.collect_all is False:
                break
            if self.duration > 0 and time.time() > self.end_time:
                break
        return result

    def collectCoreCpu(self):
        _cpucore = CPU(self.pkgName, self.deviceId, self.platform, pid=self.pid)
        cores = d.getCpuCores(self.deviceId)
        value = _cpucore.getCoreCpuRate(cores=cores, noLog=self.noLog)
        result = {'cpu{}'.format(value.index(element)):element for element in  value}
        logger.info(f'cpu core: {result}')
        return result    
    
    def collectMemory(self):
        _memory = Memory(self.pkgName, self.deviceId, self.platform, pid=self.pid)
        result = {}
        while self.get_status() == 'on':
            total, swap = _memory.getProcessMemory(noLog=self.noLog)
            result = {'total': total, 'swap': swap}
            logger.info(f'memory: {result}')
            if self.collect_all is False:
                break
            if self.duration > 0 and time.time() > self.end_time:
                break
        return result
    
    def collectMemoryDetail(self):
        _memory = Memory(self.pkgName, self.deviceId, self.platform, pid=self.pid)
        result = {}
        while self.get_status() == 'on':
            if self.platform == Platform.iOS:
                break
            result = _memory.getAndroidMemoryDetail(noLog=self.noLog)
            logger.info(f'memory detail: {result}')
            if self.collect_all is False:
                break
            if self.duration > 0 and time.time() > self.end_time:
                break
        return result
    
    def collectBattery(self):
        _battery = Battery(self.deviceId, self.platform)
        result = {}
        while self.get_status() == 'on':
            final = _battery.getBattery(noLog=self.noLog)
            if self.platform == Platform.Android:
                result = {'level': final[0], 'temperature': final[1]}
            else:
                result = {'temperature': final[0], 'current': final[1], 'voltage': final[2], 'power': final[3]}
            logger.info(f'battery: {result}')
            if self.collect_all is False:
                break
            if self.duration > 0 and time.time() > self.end_time:
                break
        return result

    def collectNetwork(self, wifi=True):
        _network = Network(self.pkgName, self.deviceId, self.platform, pid=self.pid)
        if self.noLog is False and self.platform == Platform.Android:
            data = _network.setAndroidNet(wifi=wifi)
            f.record_net('pre', data[0], data[1])
        result = {}
        while self.get_status() == 'on':
            upFlow, downFlow = _network.getNetWorkData(wifi=wifi,noLog=self.noLog)
            result = {'send': upFlow, 'recv': downFlow}
            logger.info(f'network: {result}')
            if self.collect_all is False:
                break
            if self.duration > 0 and time.time() > self.end_time:
                break
        return result

    def collectFps(self):
        _fps = FPS(self.pkgName, self.deviceId, self.platform, self.surfaceview)
        result = {}
        while self.get_status() == 'on':
            fps, jank = _fps.getFPS(noLog=self.noLog)
            result = {'fps': fps, 'jank': jank}
            logger.info(f'fps: {result}')
            if self.collect_all is False:
                break
            if self.duration > 0 and time.time() > self.end_time:
                break
        return result

    def collectGpu(self):
        _gpu = GPU(self.pkgName, self.deviceId, self.platform)
        result = {}
        while self.get_status() == 'on':
            gpu = _gpu.getGPU(noLog=self.noLog)
            result = {'gpu': gpu}
            logger.info(f'gpu: {result}')
            if self.collect_all is False:
                break
            if self.duration > 0 and time.time() > self.end_time:
                break
        return result
    
    def collectThermal(self):
         _thermal = ThermalSensor(self.deviceId, self.platform)
         result = _thermal.getThermalTemp()
         logger.info(f'thermal: {result}')
         return result
    
    def collectDisk(self):
        _disk = Disk(self.deviceId, self.platform)
        result = _disk.getDisk()
        logger.info(f'disk: {result}')
        return result
    
    def setPerfs(self, report_path=None):
        match(self.platform):
            case Platform.Android:
                adb.shell(cmd='dumpsys battery reset', deviceId=self.deviceId)
                _flow = Network(self.pkgName, self.deviceId, self.platform, pid=self.pid)
                data = _flow.setAndroidNet()
                f.record_net('end', data[0], data[1])
                scene = f.make_report(app=self.pkgName, devices=self.deviceId,
                                      video=0, platform=self.platform, model='normal')
                summary = f._setAndroidPerfs(scene)
                summary_dict = {}
                summary_dict['app'] = summary['app']
                summary_dict['platform'] = summary['platform']
                summary_dict['devices'] = summary['devices']
                summary_dict['ctime'] = summary['ctime']
                summary_dict['cpu_app'] = summary['cpuAppRate']
                summary_dict['cpu_sys'] = summary['cpuSystemRate']
                summary_dict['mem_total'] = summary['totalPassAvg']
                summary_dict['mem_swap'] = summary['swapPassAvg']
                summary_dict['fps'] = summary['fps']
                summary_dict['jank'] = summary['jank']
                summary_dict['level'] = summary['batteryLevel']
                summary_dict['tem'] = summary['batteryTeml']
                summary_dict['net_send'] = summary['flow_send']
                summary_dict['net_recv'] = summary['flow_recv']
                summary_dict['gpu'] = summary['gpu']
                summary_dict['cpu_charts'] = f.getCpuLog(Platform.Android, scene)
                summary_dict['mem_charts'] = f.getMemLog(Platform.Android, scene)
                summary_dict['mem_detail_charts'] = f.getMemDetailLog(Platform.Android, scene)
                summary_dict['net_charts'] = f.getFlowLog(Platform.Android, scene)
                summary_dict['battery_charts'] = f.getBatteryLog(Platform.Android, scene)
                summary_dict['fps_charts'] = f.getFpsLog(Platform.Android, scene)['fps']
                summary_dict['jank_charts'] = f.getFpsLog(Platform.Android, scene)['jank']
                summary_dict['gpu_charts'] = f.getGpuLog(Platform.Android, scene)
                f.make_android_html(scene=scene, summary=summary_dict, report_path=report_path)
            case Platform.iOS:
                scene = f.make_report(app=self.pkgName, devices=self.deviceId,
                                      video=0, platform=self.platform, model='normal')
                summary = f._setiOSPerfs(scene)
                summary_dict = {}
                summary_dict['app'] = summary['app']
                summary_dict['platform'] = summary['platform']
                summary_dict['devices'] = summary['devices']
                summary_dict['ctime'] = summary['ctime']
                summary_dict['cpu_app'] = summary['cpuAppRate']
                summary_dict['cpu_sys'] = summary['cpuSystemRate']
                summary_dict['mem_total'] = summary['totalPassAvg']
                summary_dict['fps'] = summary['fps']
                summary_dict['current'] = summary['batteryCurrent']
                summary_dict['voltage'] = summary['batteryVoltage']
                summary_dict['power'] = summary['batteryPower']
                summary_dict['tem'] = summary['batteryTeml']
                summary_dict['gpu'] = summary['gpu']
                summary_dict['net_send'] = summary['flow_send']
                summary_dict['net_recv'] = summary['flow_recv']
                summary_dict['cpu_charts'] = f.getCpuLog(Platform.iOS, scene)
                summary_dict['mem_charts'] = f.getMemLog(Platform.iOS, scene)
                summary_dict['net_charts'] = f.getFlowLog(Platform.iOS, scene)
                summary_dict['battery_charts'] = f.getBatteryLog(Platform.iOS, scene)
                summary_dict['fps_charts'] = f.getFpsLog(Platform.iOS, scene)
                summary_dict['gpu_charts'] = f.getGpuLog(Platform.iOS, scene)
                f.make_ios_html(scene=scene, summary=summary_dict, report_path=report_path)
            case _:
                raise Exception('platfrom is invalid')

    def collectAll(self, report_path=None):
        try:
            f.clear_file()
            process_num = 8 if self.record else 7
            pool = multiprocessing.Pool(processes=process_num)
            pool.apply_async(self.collectCpu)
            pool.apply_async(self.collectMemory)
            pool.apply_async(self.collectMemoryDetail)
            pool.apply_async(self.collectBattery)
            pool.apply_async(self.collectFps)
            pool.apply_async(self.collectNetwork)
            pool.apply_async(self.collectGpu)
            if self.record:
                pool.apply_async(Scrcpy.start_record, (self.deviceId))
            pool.close()
            pool.join()
            self.setPerfs(report_path=report_path)
        except KeyboardInterrupt:
            if self.record:
                logger.info('收到中断信号，停止录屏...')
                Scrcpy.stop_record()
                logger.info('等待录屏文件释放...')
                time.sleep(2)  # 等待文件释放
            self.setPerfs(report_path=report_path)
        except Exception as e:
            if self.record:
                logger.info('发生异常，停止录屏...')
                Scrcpy.stop_record()
                logger.info('等待录屏文件释放...')
                time.sleep(2)  # 等待文件释放
            logger.exception(e)
        finally:
            logger.info('End of testing')         