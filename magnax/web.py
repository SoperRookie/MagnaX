from __future__ import absolute_import
import multiprocessing
import subprocess
import time
import os
import platform
import re
import webbrowser
import requests
import socket
import sys
import psutil
import atexit
from loguru import logger
from threading import Lock
from flask import Flask
from pyfiglet import Figlet
from magnax.view.apis import api
from magnax.view.pages import page
from magnax import __version__

# Global reference to tunneld process
_tunneld_process = None

app = Flask(__name__, template_folder='templates', static_folder='static')
app.register_blueprint(api)
app.register_blueprint(page)

# socketio = SocketIO(app, cors_allowed_origins="*")
# thread = True
# thread_lock = Lock()


# @socketio.on('connect', namespace='/logcat')
# def connect():
#     socketio.emit('start connect', {'data': 'Connected'}, namespace='/logcat')
#     logDir = os.path.join(os.getcwd(),'adblog')
#     if not os.path.exists(logDir):
#         os.mkdir(logDir)
#     global thread
#     thread = True
#     with thread_lock:
#         if thread:
#             thread = socketio.start_background_task(target=backgroundThread)


# def backgroundThread():
#     global thread
#     try:
#         current_time = time.strftime("%Y%m%d%H", time.localtime())
#         logPath = os.path.join(os.getcwd(),'adblog',f'{current_time}.log')
#         logcat = subprocess.Popen(f'adb logcat *:E > {logPath}', stdout=subprocess.PIPE,
#                                   shell=True)
#         with open(logPath, "r") as f:
#             while thread:
#                 socketio.sleep(1)
#                 for line in f.readlines():
#                     socketio.emit('message', {'data': line}, namespace='/logcat')
#         if logcat.poll() == 0:
#             thread = False
#     except Exception:
#         pass


# @socketio.on('disconnect_request', namespace='/logcat')
# def disconnect():
#     global thread
#     logger.warning('Logcat client disconnected')
#     thread = False
#     disconnect()

def ip() -> str:
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except:
        logger.info('hostname:{}'.format(socket.gethostname()))
        logger.warning('config [127.0.0.1 hostname] in /etc/hosts file')
        ip = '127.0.0.1'    
    return ip


def listen(port):
    net_connections = psutil.net_connections()
    conn = [c for c in net_connections if c.status == "LISTEN" and c.laddr.port == port]
    if conn:
        pid = conn[0].pid
        logger.warning('Port {} is used by process {}'.format(port, pid))
        logger.info('you can start magnax : python -m magnax --host={ip} --port={port}')
        return False
    return True

def status(host: str, port: int):
    r = requests.get('http://{}:{}'.format(host, port), timeout=2.0)
    flag = (True, False)[r.status_code == 200]
    return flag


def open_url(host: str, port: int):
    flag = True
    while flag:
        logger.info('start magnax service')
        f = Figlet(font="slant", width=300)
        print(f.renderText("MAGNAX {}".format(__version__)))
        flag = status(host, port)
    try:    
        webbrowser.open('http://{}:{}/?platform=Android&lan=en'.format(host, port), new=2)
    except Exception as e:
        logger.exception(e)    
    logger.info('Running on http://{}:{}/?platform=Android&lan=en (Press CTRL+C to quit)'.format(host, port))


def start(host: str, port: int):
    app.run(host=host, port=port, debug=False)


def check_ios17_device():
    """Check if there are iOS 17+ devices connected."""
    try:
        from pymobiledevice3.usbmux import list_devices
        from pymobiledevice3.lockdown import create_using_usbmux

        devices = list_devices()
        for device in devices:
            try:
                lockdown = create_using_usbmux(serial=device.serial)
                version = lockdown.product_version
                if version:
                    major = int(version.split('.')[0])
                    if major >= 17:
                        return True
            except:
                pass
        return False
    except ImportError:
        return False
    except Exception:
        return False


def is_tunneld_running():
    """Check if tunneld is already running."""
    try:
        from pymobiledevice3.tunneld.api import get_tunneld_devices
        devices = get_tunneld_devices()
        return len(devices) > 0
    except:
        return False


def _run_with_sudo_macos(cmd_args):
    """Run command with sudo using macOS GUI password prompt."""
    try:
        # Use osascript to get admin privileges with GUI prompt
        cmd_str = ' '.join(cmd_args)
        apple_script = f'''
        do shell script "{cmd_str} > /dev/null 2>&1 &" with administrator privileges
        '''
        result = subprocess.run(
            ['osascript', '-e', apple_script],
            capture_output=True,
            timeout=60  # Give user time to enter password
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.warning('[iOS] Password prompt timed out')
        return False
    except Exception as e:
        logger.debug(f'[iOS] osascript failed: {e}')
        return False


def _run_with_sudo_linux(cmd_args):
    """Run command with sudo using Linux GUI password prompt (if available)."""
    try:
        # Try pkexec (PolicyKit) for GUI prompt
        result = subprocess.run(
            ['which', 'pkexec'],
            capture_output=True
        )
        if result.returncode == 0:
            subprocess.Popen(
                ['pkexec'] + cmd_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            return True
    except:
        pass

    # Try zenity/kdialog for password input
    try:
        # Try zenity (GNOME)
        result = subprocess.run(
            ['zenity', '--password', '--title=MagnaX - iOS tunneld'],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0 and result.stdout:
            password = result.stdout.strip()
            proc = subprocess.Popen(
                ['sudo', '-S'] + cmd_args,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True
            )
            proc.stdin.write(f'{password}\n'.encode())
            proc.stdin.close()
            return True
    except:
        pass

    return False


def start_tunneld():
    """Start tunneld daemon for iOS 17+ devices."""
    global _tunneld_process

    # Only run on macOS/Linux
    if platform.system() == 'Windows':
        logger.warning('[iOS] tunneld is not supported on Windows')
        return False

    # Check if already running
    if is_tunneld_running():
        logger.info('[iOS] tunneld is already running')
        return True

    # Check if iOS 17+ device exists
    if not check_ios17_device():
        logger.debug('[iOS] No iOS 17+ device found, skipping tunneld')
        return True

    logger.info('[iOS] iOS 17+ device detected, starting tunneld...')

    tunneld_cmd = [sys.executable, '-m', 'pymobiledevice3', 'remote', 'tunneld']

    # Try to start tunneld
    try:
        # First try without sudo (might work if user has permissions)
        _tunneld_process = subprocess.Popen(
            tunneld_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # Wait a moment and check if it's working
        time.sleep(2)
        if is_tunneld_running():
            logger.info('[iOS] tunneld started successfully')
            return True

        # If not working, kill it and try with sudo
        if _tunneld_process:
            try:
                _tunneld_process.terminate()
            except:
                pass
            _tunneld_process = None

        # Try with GUI sudo prompt based on platform
        logger.info('[iOS] Requesting administrator privileges for tunneld...')

        if platform.system() == 'Darwin':
            # macOS: Use osascript for GUI password prompt
            if _run_with_sudo_macos(tunneld_cmd):
                # Wait for tunneld to start
                for _ in range(10):
                    time.sleep(1)
                    if is_tunneld_running():
                        logger.info('[iOS] tunneld started successfully')
                        return True
        else:
            # Linux: Try GUI methods
            if _run_with_sudo_linux(tunneld_cmd):
                for _ in range(10):
                    time.sleep(1)
                    if is_tunneld_running():
                        logger.info('[iOS] tunneld started successfully')
                        return True

        # Last resort: try terminal sudo (will prompt in terminal)
        logger.info('[iOS] Trying terminal sudo (enter password if prompted)...')
        subprocess.Popen(
            ['sudo'] + tunneld_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        for _ in range(15):
            time.sleep(1)
            if is_tunneld_running():
                logger.info('[iOS] tunneld started successfully')
                return True

        logger.warning('[iOS] Could not start tunneld automatically')
        logger.warning('[iOS] Please run manually: sudo python3 -m pymobiledevice3 remote tunneld')
        return False

    except Exception as e:
        logger.warning(f'[iOS] Failed to start tunneld: {e}')
        logger.warning('[iOS] Please run manually: sudo python3 -m pymobiledevice3 remote tunneld')
        return False


def stop_tunneld():
    """Stop tunneld daemon if we started it."""
    global _tunneld_process
    if _tunneld_process:
        try:
            _tunneld_process.terminate()
            _tunneld_process.wait(timeout=5)
        except:
            try:
                _tunneld_process.kill()
            except:
                pass
        _tunneld_process = None


# Register cleanup on exit
atexit.register(stop_tunneld)


def main(host=ip(), port=50003):
    # Start tunneld for iOS 17+ devices if needed
    start_tunneld()

    try:
        pool = multiprocessing.Pool(processes=2)
        pool.apply_async(start, (host, port))
        pool.apply_async(open_url, (host, port))
        pool.close()
        pool.join()
    except KeyboardInterrupt:
        logger.info('stop magnax success')
        sys.exit()
    except Exception as e:
        logger.exception(e)            
