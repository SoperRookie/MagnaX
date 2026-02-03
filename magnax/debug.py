import multiprocessing
import subprocess
import time
import os
import webbrowser
import requests
import socket
import psutil
import sys
from view.apis import api
from view.pages import page
from loguru import logger
from flask import Flask
from pyfiglet import Figlet
from magnax import __version__

app = Flask(__name__, template_folder='templates', static_folder='static')
app.register_blueprint(api)
app.register_blueprint(page)


def ip() -> str:
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except:
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
        logger.info('start magnax server ...')
        f = Figlet(font="slant", width=300)
        print(f.renderText("MAGNAX {}".format(__version__)))
        flag = status(host, port)
    webbrowser.open('http://{}:{}/?platform=Android&lan=en'.format(host, port), new=2)
    logger.info('Running on http://{}:{}/?platform=Android&lan=en (Press CTRL+C to quit)'.format(host, port))


def start(host: str, port: int):
    logger.info('Running on http://{}:{}/?platform=Android&lan=en (Press CTRL+C to quit)'.format(host, port))
    app.run(host=host, port=port, debug=True)

def main(host=ip(), port=50003):
    start(host, port)      


if __name__ == '__main__':
    main()