# -*- coding: utf-8 -*-
import datetime
import queue
import re
import threading
import time
import traceback
from loguru import logger
from magnax.public.adb import adb
from magnax.public.common import Devices

d = Devices()

collect_fps = 0
collect_jank = 0


class SurfaceStatsCollector(object):
    def __init__(self, device, frequency, package_name, fps_queue, jank_threshold, surfaceview, use_legacy=False):
        self.device = device
        self.frequency = frequency
        self.package_name = package_name
        self.jank_threshold = jank_threshold / 1000.0 
        self.use_legacy_method = use_legacy
        self.use_gfxinfo_method = False  # 新增gfxinfo备用方案
        self.surface_before = 0
        self.last_timestamp = 0
        self.gfxinfo_before = None  # 存储之前的gfxinfo数据
        self.data_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.focus_window = None
        self.surfaceview = surfaceview
        self.fps_queue = fps_queue

    def start(self, start_time):
        if not self.use_legacy_method:
            try:
                self.focus_window = self.get_focus_activity()
                if self.focus_window:
                    if self.focus_window.find('$') != -1:
                        self.focus_window = self.focus_window.replace('$', '\$')
                    logger.debug(f'[FPS] Using focus window: {self.focus_window}')
                else:
                    logger.warning('[FPS] Failed to get focus window, switching to legacy method')
                    self.use_legacy_method = True
            except Exception as e:
                logger.warning(f'[FPS] Unable to get focus activity: {str(e)}, switching to legacy method')
                self.use_legacy_method = True
        
        if self.use_legacy_method:
            logger.info("[FPS] Using legacy method for FPS detection")
            try:
                self.surface_before = self._get_surface_stats_legacy()
                if not self.surface_before:
                    logger.error("[FPS] Legacy method failed to get initial surface stats")
                    logger.warning("[FPS] Switching to gfxinfo fallback method")
                    # 切换到gfxinfo方法
                    self.use_legacy_method = False
                    self.use_gfxinfo_method = True
                    # 初始化时获取基准gfxinfo数据（不重置）
                    self.gfxinfo_before = self._get_gfxinfo_stats(reset_stats=False)
                    if not self.gfxinfo_before:
                        logger.error("[FPS] All FPS detection methods failed")
                        # 使用默认值作为最后的回退
                        self.surface_before = {'page_flip_count': 0, 'timestamp': datetime.datetime.now()}
                        self.use_legacy_method = True  # 回退到legacy方法避免后续代码出错
                        self.use_gfxinfo_method = False
                    else:
                        logger.info("[FPS] Successfully initialized gfxinfo method")
            except Exception as e:
                logger.error(f"[FPS] Legacy method initialization failed: {str(e)}")
                logger.warning("[FPS] Trying gfxinfo fallback method")
                self.use_legacy_method = False
                self.use_gfxinfo_method = True
                try:
                    self.gfxinfo_before = self._get_gfxinfo_stats(reset_stats=False)
                    if not self.gfxinfo_before:
                        logger.error("[FPS] All FPS detection methods failed")
                        self.surface_before = {'page_flip_count': 0, 'timestamp': datetime.datetime.now()}
                        self.use_legacy_method = True
                        self.use_gfxinfo_method = False
                    else:
                        logger.info("[FPS] Successfully initialized gfxinfo method")
                except Exception as gfx_e:
                    logger.error(f"[FPS] gfxinfo method also failed: {str(gfx_e)}")
                    self.surface_before = {'page_flip_count': 0, 'timestamp': datetime.datetime.now()}
                    self.use_legacy_method = True
                    self.use_gfxinfo_method = False
        
        self.collector_thread = threading.Thread(target=self._collector_thread)
        self.collector_thread.start()
        self.calculator_thread = threading.Thread(target=self._calculator_thread, args=(start_time,))
        self.calculator_thread.start()

    def stop(self):
        if self.collector_thread:
            self.stop_event.set()
            self.collector_thread.join()
            self.collector_thread = None
            if self.fps_queue:
                self.fps_queue.task_done()

    def get_surfaceview(self):
        activity_name = ''
        activity_line = ''
        try:
            dumpsys_result = adb.shell(cmd='dumpsys SurfaceFlinger --list | {} {}'.format(d.filterType(), self.package_name), deviceId=self.device)
            dumpsys_result_list = dumpsys_result.split('\n')
            for line in dumpsys_result_list:
                if line.startswith('SurfaceView') and line.find(self.package_name) != -1:
                    activity_line = line.strip()
                    return activity_line

            activity_name = dumpsys_result_list[len(dumpsys_result_list) - 1]
            if not activity_name.__contains__(self.package_name):
                logger.error('get activity name failed, Please provide SurfaceFlinger --list information to the author')
                logger.info('dumpsys SurfaceFlinger --list info: {}'.format(dumpsys_result))
        except Exception:
            traceback.print_exc()
            logger.error('get activity name failed, Please provide SurfaceFlinger --list information to the author')
            logger.info('dumpsys SurfaceFlinger --list info: {}'.format(dumpsys_result))
        return activity_name            
     
    def get_surfaceview_activity(self):
        activity_name = ''
        activity_line = ''
        try:
            dumpsys_result = adb.shell(cmd='dumpsys SurfaceFlinger --list | {} {}'.format(d.filterType(), self.package_name), deviceId=self.device)
            dumpsys_result_list = dumpsys_result.split('\n')    
            for line in dumpsys_result_list:
                if line.startswith('SurfaceView') and line.find(self.package_name) != -1:
                    activity_line = line.strip()
                    break
            if activity_line:
                if activity_line.find(' ')  != -1:      
                    activity_name = activity_line.split(' ')[2]
                else:
                    activity_name = activity_line.replace('SurfaceView','').replace('[','').replace(']','').replace('-','').strip()    
            else:
                activity_name = dumpsys_result_list[len(dumpsys_result_list) - 1]
                if not activity_name.__contains__(self.package_name):
                    logger.error('get activity name failed, Please provide SurfaceFlinger --list information to the author')
                    logger.info('dumpsys SurfaceFlinger --list info: {}'.format(dumpsys_result))
        except Exception:
            traceback.print_exc()
            logger.error('get activity name failed, Please provide SurfaceFlinger --list information to the author')
            logger.info('dumpsys SurfaceFlinger --list info: {}'.format(dumpsys_result))
        return activity_name
     
    def get_focus_activity(self):
        activity_name = ''
        activity_line = ''
        dumpsys_result = adb.shell(cmd='dumpsys window windows', deviceId=self.device)
        dumpsys_result_list = dumpsys_result.split('\n')
        for line in dumpsys_result_list:
            if line.find('mCurrentFocus') != -1:
                activity_line = line.strip()
        if activity_line:
            activity_line_split = activity_line.split(' ')
        else:
            return activity_name
        if len(activity_line_split) > 1:
            if activity_line_split[1] == 'u0':
                activity_name = activity_line_split[2].rstrip('}')
            else:
                activity_name = activity_line_split[1]
        if not activity_name:
            activity_name = self.get_surfaceview_activity()        
        return activity_name

    def get_foreground_process(self):
        focus_activity = self.get_focus_activity()
        if focus_activity:
            return focus_activity.split("/")[0]
        else:
            return ""

    def _calculate_results(self, refresh_period, timestamps):
        frame_count = len(timestamps)
        if frame_count == 0:
            fps = 0
            jank = 0
        elif frame_count == 1:
            fps = 1
            jank = 0
        else:
            seconds = timestamps[-1][1] - timestamps[0][1]
            if seconds > 0:
                fps = int(round((frame_count - 1) / seconds))
                jank = self._calculate_janky(timestamps)
            else:
                fps = 1
                jank = 0
        return fps, jank

    def _calculate_results_new(self, refresh_period, timestamps):
        frame_count = len(timestamps)
        if frame_count == 0:
            fps = 0
            jank = 0
        elif frame_count == 1:
            fps = 1
            jank = 0
        elif frame_count == 2 or frame_count == 3 or frame_count == 4:
            seconds = timestamps[-1][1] - timestamps[0][1]
            if seconds > 0:
                fps = int(round((frame_count - 1) / seconds))
                jank = self._calculate_janky(timestamps)
            else:
                fps = 1
                jank = 0
        else:
            seconds = timestamps[-1][1] - timestamps[0][1]
            if seconds > 0:
                fps = int(round((frame_count - 1) / seconds))
                jank = self._calculate_jankey_new(timestamps)
            else:
                fps = 1
                jank = 0
        return fps, jank

    def _calculate_jankey_new(self, timestamps):
        twofilmstamp = 83.3 / 1000.0
        tempstamp = 0
        jank = 0
        for index, timestamp in enumerate(timestamps):
            if (index == 0) or (index == 1) or (index == 2) or (index == 3):
                if tempstamp == 0:
                    tempstamp = timestamp[1]
                    continue
                costtime = timestamp[1] - tempstamp
                if costtime > self.jank_threshold:
                    jank = jank + 1
                tempstamp = timestamp[1]
            elif index > 3:
                currentstamp = timestamps[index][1]
                lastonestamp = timestamps[index - 1][1]
                lasttwostamp = timestamps[index - 2][1]
                lastthreestamp = timestamps[index - 3][1]
                lastfourstamp = timestamps[index - 4][1]
                tempframetime = ((lastthreestamp - lastfourstamp) + (lasttwostamp - lastthreestamp) + (
                        lastonestamp - lasttwostamp)) / 3 * 2
                currentframetime = currentstamp - lastonestamp
                if (currentframetime > tempframetime) and (currentframetime > twofilmstamp):
                    jank = jank + 1
        return jank

    def _calculate_janky(self, timestamps):
        tempstamp = 0
        jank = 0
        for timestamp in timestamps:
            if tempstamp == 0:
                tempstamp = timestamp[1]
                continue
            costtime = timestamp[1] - tempstamp
            if costtime > self.jank_threshold:
                jank = jank + 1
            tempstamp = timestamp[1]
        return jank

    def _calculator_thread(self, start_time):
        global collect_fps
        global collect_jank
        while True:
            try:
                data = self.data_queue.get()
                if isinstance(data, str) and data == 'Stop':
                    break
                before = time.time()
                
                # 处理gfxinfo数据
                if isinstance(data, tuple) and len(data) == 3 and data[0] == 'gfxinfo':
                    gfxinfo_data = data[1]
                    if self.gfxinfo_before is not None:
                        # 计算FPS - 基于前后两次gfxinfo数据的差值
                        td = gfxinfo_data['timestamp'] - self.gfxinfo_before['timestamp']
                        seconds = td.total_seconds()
                        frame_diff = gfxinfo_data['total_frames'] - self.gfxinfo_before['total_frames']
                        jank_diff = gfxinfo_data['janky_frames'] - self.gfxinfo_before['janky_frames']
                        
                        if seconds > 0 and frame_diff >= 0:
                            fps = int(round(frame_diff / seconds)) if frame_diff > 0 else 0
                            if fps > 60:  # 限制最大FPS
                                fps = 60
                            jank = jank_diff
                        else:
                            fps = 0
                            jank = 0
                        
                        logger.debug(f'[FPS] gfxinfo calculated: fps={fps}, jank={jank}, frame_diff={frame_diff}, seconds={seconds:.2f}')
                        collect_fps = fps
                        collect_jank = jank
                    else:
                        # 第一次采样，记录基准数据
                        collect_fps = 0
                        collect_jank = 0
                        logger.debug("[FPS] gfxinfo: First sample, establishing baseline")
                    
                    self.gfxinfo_before = gfxinfo_data
                    
                elif self.use_legacy_method:
                    td = data['timestamp'] - self.surface_before['timestamp']
                    seconds = td.seconds + td.microseconds / 1e6
                    frame_count = (data['page_flip_count'] -
                                   self.surface_before['page_flip_count'])
                    fps = int(round(frame_count / seconds))
                    if fps > 60:
                        fps = 60
                    self.surface_before = data
                    # logger.debug('FPS:%2s'%fps)
                    collect_fps = fps
                else:
                    refresh_period = data[0]
                    timestamps = data[1]
                    collect_time = data[2]
                    # fps,jank = self._calculate_results(refresh_period, timestamps)
                    fps, jank = self._calculate_results_new(refresh_period, timestamps)
                    # logger.debug('FPS:%2s Jank:%s'%(fps,jank))
                    collect_fps = fps
                    collect_jank = jank
                time_consume = time.time() - before
                delta_inter = self.frequency - time_consume
                if delta_inter > 0:
                    time.sleep(delta_inter)
            except:
                logger.error("an exception hanpend in fps _calculator_thread ,reason unkown!")
                s = traceback.format_exc()
                logger.debug(s)
                if self.fps_queue:
                    self.fps_queue.task_done()

    def _collector_thread(self):
        is_first = True
        consecutive_failures = 0
        max_failures = 5  # 最大连续失败次数
        
        while not self.stop_event.is_set():
            try:
                before = time.time()
                data_collected = False
                
                if self.use_gfxinfo_method:
                    try:
                        # 获取当前gfxinfo统计数据
                        gfxinfo_state = self._get_gfxinfo_stats(reset_stats=False)
                        if gfxinfo_state:
                            self.data_queue.put(('gfxinfo', gfxinfo_state, time.time()))
                            data_collected = True
                            consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                            if consecutive_failures <= 3:
                                logger.warning(f"[FPS] gfxinfo method failed to get data (attempt {consecutive_failures})")
                            elif consecutive_failures == max_failures:
                                logger.error(f"[FPS] gfxinfo method consistently failing, device may not support FPS detection")
                    except Exception as e:
                        consecutive_failures += 1
                        logger.error(f"[FPS] gfxinfo method exception (attempt {consecutive_failures}): {str(e)}")
                elif self.use_legacy_method:
                    try:
                        surface_state = self._get_surface_stats_legacy()
                        if surface_state:
                            self.data_queue.put(surface_state)
                            data_collected = True
                            consecutive_failures = 0
                        else:
                            consecutive_failures += 1
                            if consecutive_failures <= 3:  # 前3次失败只显示警告
                                logger.warning(f"[FPS] Legacy method failed to get data (attempt {consecutive_failures})")
                            elif consecutive_failures == max_failures:
                                logger.error(f"[FPS] Legacy method consistently failing, device may not support FPS detection")
                    except Exception as e:
                        consecutive_failures += 1
                        logger.error(f"[FPS] Legacy method exception (attempt {consecutive_failures}): {str(e)}")
                else:
                    timestamps = []
                    refresh_period, new_timestamps = self._get_surfaceflinger_frame_data()
                    
                    if refresh_period is None or new_timestamps is None:
                        consecutive_failures += 1
                        logger.warning(f"[FPS] SurfaceFlinger data is None (attempt {consecutive_failures})")
                        
                        # 如果连续失败次数过多，尝试切换到legacy方法
                        if consecutive_failures >= max_failures and not self.use_legacy_method:
                            logger.warning("[FPS] Too many failures, switching to legacy method")
                            self.use_legacy_method = True
                            self.surface_before = self._get_surface_stats_legacy()
                        else:
                            # 尝试重新获取焦点窗口
                            self.focus_window = self.get_focus_activity()
                        continue
                    
                    timestamps += [timestamp for timestamp in new_timestamps
                                   if timestamp[1] > self.last_timestamp]
                    if len(timestamps):
                        first_timestamp = [[0, self.last_timestamp, 0]]
                        if not is_first:
                            timestamps = first_timestamp + timestamps
                        self.last_timestamp = timestamps[-1][1]
                        is_first = False
                        data_collected = True
                        consecutive_failures = 0
                    else:
                        is_first = True
                        cur_focus_window = self.get_focus_activity()
                        if self.focus_window != cur_focus_window:
                            logger.debug(f"[FPS] Focus window changed: {self.focus_window} -> {cur_focus_window}")
                            self.focus_window = cur_focus_window
                        continue
                    
                    self.data_queue.put((refresh_period, timestamps, time.time()))
                
                # 如果成功收集数据，控制采样频率
                if data_collected:
                    time_consume = time.time() - before
                    # gfxinfo方法可以使用正常的采样间隔
                    if self.use_gfxinfo_method:
                        sample_interval = max(self.frequency, 1)  # 至少1秒间隔
                    else:
                        sample_interval = self.frequency
                    
                    delta_inter = sample_interval - time_consume
                    if delta_inter > 0:
                        time.sleep(delta_inter)
                
                # 如果失败次数过多，增加等待时间避免过于频繁的重试
                if consecutive_failures >= max_failures:
                    time.sleep(2)  # 等待2秒再重试
                    
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"[FPS] Exception in collector thread (attempt {consecutive_failures}): {str(e)}")
                logger.debug(traceback.format_exc())
                if self.fps_queue:
                    self.fps_queue.task_done()
                
                # 如果异常次数过多，等待更长时间
                if consecutive_failures >= max_failures:
                    time.sleep(5)
        
        self.data_queue.put(u'Stop')

    def _clear_surfaceflinger_latency_data(self):
        """Clears the SurfaceFlinger latency data.

        Returns:
            True if SurfaceFlinger latency is supported by the device, otherwise
            False.
        """
        # The command returns nothing if it is supported, otherwise returns many
        # lines of result just like 'dumpsys SurfaceFlinger'.
        if self.focus_window is None:
            results = adb.shell(cmd='dumpsys SurfaceFlinger --latency-clear', deviceId=self.device)
        else:
            results = adb.shell(cmd='dumpsys SurfaceFlinger --latency-clear %s' % self.focus_window,
                                deviceId=self.device)
        return not len(results)

    def get_sdk_version(self):
        sdk_version = int(adb.shell(cmd='getprop ro.build.version.sdk', deviceId=self.device))
        return sdk_version

    def _get_surfaceflinger_frame_data(self):
        """Returns collected SurfaceFlinger frame timing data.
        return:(16.6,[[t1,t2,t3],[t4,t5,t6]])
        Returns:
            A tuple containing:
            - The display's nominal refresh period in seconds.
            - A list of timestamps signifying frame presentation times in seconds.
            The return value may be (None, None) if there was no data collected (for
            example, if the app was closed before the collector thread has finished).
        """
        # shell dumpsys SurfaceFlinger --latency <window name>
        # prints some information about the last 128 frames displayed in
        # that window.
        # The data returned looks like this:
        # 16954612
        # 7657467895508     7657482691352     7657493499756
        # 7657484466553     7657499645964     7657511077881
        # 7657500793457     7657516600576     7657527404785
        # (...)
        #
        # The first line is the refresh period (here 16.95 ms), it is followed
        # by 128 lines w/ 3 timestamps in nanosecond each:
        # A) when the app started to draw
        # B) the vsync immediately preceding SF submitting the frame to the h/w
        # C) timestamp immediately after SF submitted that frame to the h/w
        #
        # The difference between the 1st and 3rd timestamp is the frame-latency.
        # An interesting data is when the frame latency crosses a refresh period
        # boundary, this can be calculated this way:
        #
        # ceil((C - A) / refresh-period)
        #
        # (each time the number above changes, we have a "jank").
        # If this happens a lot during an animation, the animation appears
        # janky, even if it runs at 60 fps in average.
        #

        # Google Pixel 2 android8.0 dumpsys SurfaceFlinger --latency结果
        # 16666666
        # 0       0       0
        # 0       0       0
        # 0       0       0
        # 0       0       0
        # 但华为 荣耀9 android8.0 dumpsys SurfaceFlinger --latency结果是正常的 但数据更新很慢  也不能用来计算fps
        # 16666666
        # 9223372036854775807     3618832932780   9223372036854775807
        # 9223372036854775807     3618849592155   9223372036854775807
        # 9223372036854775807     3618866251530   9223372036854775807

        refresh_period = None
        timestamps = []
        nanoseconds_per_second = 1e9
        pending_fence_timestamp = (1 << 63) - 1
        if self.surfaceview is not True:
            results = adb.shell(
                cmd='dumpsys SurfaceFlinger --latency %s' % self.focus_window, deviceId=self.device)
            results = results.replace("\r\n", "\n").splitlines()
            refresh_period = int(results[0]) / nanoseconds_per_second
            results = adb.shell(cmd='dumpsys gfxinfo %s framestats' % self.package_name, deviceId=self.device)
            results = results.replace("\r\n", "\n").splitlines()
            if not len(results):
                return (None, None)
            isHaveFoundWindow = False
            PROFILEDATA_line = 0
            activity = self.focus_window
            if self.focus_window.__contains__('#'):
                activity = activity.split('#')[0]
            for line in results:
                if not isHaveFoundWindow:
                    if "Window" in line and activity in line:
                        isHaveFoundWindow = True
                if not isHaveFoundWindow:
                    continue
                if "PROFILEDATA" in line:
                    PROFILEDATA_line += 1
                fields = []
                fields = line.split(",")
                if fields and '0' == fields[0]:
                    # https://www.cnblogs.com/zhengna/p/10032078.html
                    # 1 INTENDED_VSYNC
                    # 2 VSYNC
                    # 13 FRAME_COMPLETED
                    timestamp = [int(fields[1]), int(fields[2]), int(fields[13])]
                    if timestamp[1] == pending_fence_timestamp:
                        continue
                    timestamp = [_timestamp / nanoseconds_per_second for _timestamp in timestamp]
                    timestamps.append(timestamp)
                if 2 == PROFILEDATA_line:
                    break
        else:
            # self.focus_window = self.get_surfaceview_activity()
            self.focus_window = self.get_surfaceview()
            results = adb.shell(
                cmd='dumpsys SurfaceFlinger --latency \\"%s\\"' % self.focus_window, deviceId=self.device)
            results = results.replace("\r\n", "\n").splitlines()
            if len(results) <= 1 or int(results[-2].split()[0]) ==0:
                self.focus_window = self.get_surfaceview_activity()
                results = adb.shell(
                cmd='dumpsys SurfaceFlinger --latency \\"%s\\"' % self.focus_window, deviceId=self.device)
                results = results.replace("\r\n", "\n").splitlines()
            if not len(results):
                return (None, None)
            if not results[0].isdigit():
                return (None, None)
            try:
                refresh_period = int(results[0]) / nanoseconds_per_second
            except Exception as e:
                logger.exception(e)
                return (None, None)
            # If a fence associated with a frame is still pending when we query the
            # latency data, SurfaceFlinger gives the frame a timestamp of INT64_MAX.
            # Since we only care about completed frames, we will ignore any timestamps
            # with this value.
            
            for line in results[2:]:
                fields = line.split()
                if len(fields) != 3:
                    continue
                timestamp = [int(fields[0]), int(fields[1]), int(fields[2])]
                if timestamp[1] == pending_fence_timestamp:
                    continue
                timestamp = [_timestamp / nanoseconds_per_second for _timestamp in timestamp]
                timestamps.append(timestamp)
        return (refresh_period, timestamps)

    def _get_surface_stats_legacy(self):
        """Legacy method (before JellyBean), returns the current Surface index
             and timestamp.

        Calculate FPS by measuring the difference of Surface index returned by
        SurfaceFlinger in a period of time.

        Returns:
            Dict of {page_flip_count (or 0 if there was an error), timestamp}.
        """
        cur_surface = None
        timestamp = datetime.datetime.now()
        ret = adb.shell(cmd="service call SurfaceFlinger 1013", deviceId=self.device)
        if not ret:
            logger.warning("[FPS] Legacy method: No response from SurfaceFlinger service")
            return None
        
        # 检查是否包含错误信息
        if "Error:" in ret or "Permission denied" in ret or "Operation not permitted" in ret:
            logger.error(f"[FPS] Legacy method failed: {ret.strip()}")
            return None
            
        match = re.search('^Result: Parcel\((\w+)', ret)
        if match:
            hex_str = match.group(1)
            # 验证是否为有效的十六进制字符串
            try:
                # 检查是否包含非十六进制字符
                if not all(c in '0123456789abcdefABCDEF' for c in hex_str):
                    logger.error(f"[FPS] Legacy method: Invalid hex string '{hex_str}' in response: {ret.strip()}")
                    return None
                cur_surface = int(hex_str, 16)
                logger.debug(f"[FPS] Legacy method: Successfully got surface count {cur_surface}")
                return {'page_flip_count': cur_surface, 'timestamp': timestamp}
            except ValueError as e:
                logger.error(f"[FPS] Legacy method: Failed to parse hex '{hex_str}': {str(e)}")
                return None
        else:
            logger.error(f"[FPS] Legacy method: Unexpected response format: {ret.strip()}")
            return None

    def _get_gfxinfo_stats(self, reset_stats=False):
        """Gfxinfo fallback method for FPS detection.
        
        Uses dumpsys gfxinfo to get frame statistics.
        
        Args:
            reset_stats: Whether to reset the statistics first for fresh data
        
        Returns:
            Dict containing frame statistics or None if failed.
        """
        try:
            # 如果需要重置统计数据，先清除累积数据
            if reset_stats:
                reset_cmd = f'dumpsys gfxinfo {self.package_name} reset'
                adb.shell(cmd=reset_cmd, deviceId=self.device)
                time.sleep(0.1)  # 短暂等待重置完成
            
            timestamp = datetime.datetime.now()
            cmd = f'dumpsys gfxinfo {self.package_name}'
            result = adb.shell(cmd=cmd, deviceId=self.device)
            
            if not result or "No process found" in result:
                logger.warning(f"[FPS] gfxinfo: No process found for {self.package_name}")
                return None
            
            # 解析gfxinfo数据
            lines = result.split('\n')
            total_frames = 0
            janky_frames = 0
            
            for line in lines:
                line = line.strip()
                if "Total frames rendered:" in line:
                    try:
                        total_frames = int(line.split(':')[1].strip())
                    except (ValueError, IndexError):
                        pass
                elif "Janky frames:" in line:
                    try:
                        # 解析 "Janky frames: 7 (6.36%)" 格式
                        janky_part = line.split(':')[1].strip()
                        janky_frames = int(janky_part.split(' ')[0])
                    except (ValueError, IndexError):
                        pass
            
            if total_frames >= 0:  # 允许0帧的情况，表示没有新帧
                logger.debug(f"[FPS] gfxinfo: total_frames={total_frames}, janky_frames={janky_frames}")
                return {
                    'total_frames': total_frames,
                    'janky_frames': janky_frames,
                    'timestamp': timestamp
                }
            else:
                logger.warning("[FPS] gfxinfo: No valid frame data found")
                return None
                
        except Exception as e:
            logger.error(f"[FPS] gfxinfo method failed: {str(e)}")
            return None


class Monitor(object):
    def __init__(self, **kwargs):
        self.config = kwargs
        self.matched_data = {}

    def start(self):
        logger.warn("请在%s类中实现start方法" % type(self))

    def clear(self):
        self.matched_data = {}

    def stop(self):
        logger.warning("请在%s类中实现stop方法" % type(self))

    def save(self):
        logger.warning("请在%s类中实现save方法" % type(self))


class TimeUtils(object):
    UnderLineFormatter = "%Y_%m_%d_%H_%M_%S"
    NormalFormatter = "%Y-%m-%d %H-%M-%S"
    ColonFormatter = "%Y-%m-%d %H:%M:%S"

    @staticmethod
    def getCurrentTimeUnderline():
        return time.strftime(TimeUtils.UnderLineFormatter, time.localtime(time.time()))


class FPSMonitor(Monitor):
    def __init__(self, device_id, package_name=None, frequency=1.0, timeout=24 * 60 * 60, fps_queue=None,
                 jank_threshold=166, use_legacy=False, surfaceview=True, start_time=None, **kwargs):
        super().__init__(**kwargs)
        self.start_time = start_time
        self.use_legacy = use_legacy
        self.frequency = frequency  # 取样频率
        self.jank_threshold = jank_threshold
        self.device = device_id
        self.timeout = timeout
        self.surfaceview = surfaceview
        self.package = package_name
        self.fpscollector = SurfaceStatsCollector(self.device, self.frequency, package_name, fps_queue,
                                                  self.jank_threshold, self.surfaceview, self.use_legacy)

    def start(self):
        self.fpscollector.start(self.start_time)

    def stop(self):
        global collect_fps
        global collect_jank
        self.fpscollector.stop()
        return collect_fps, collect_jank

    def save(self):
        pass

    def parse(self, file_path):
        pass

    def get_fps_collector(self):
        return self.fpscollector
