#!/usr/bin/env python
# coding: utf-8
#
# Licensed under MIT
#
import os
import re
import setuptools

# Read version from __init__.py without importing
def get_version():
    init_file = os.path.join(os.path.dirname(__file__), 'magnax', '__init__.py')
    with open(init_file, 'r', encoding='utf-8') as f:
        content = f.read()
    match = re.search(r"__version__\s*=\s*['\"]([^'\"]+)['\"]", content)
    if match:
        return match.group(1)
    raise RuntimeError("Unable to find version string.")

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name='magnax',
    version=get_version(),
    author='SoperRookie',
    author_email='rookiessmall@gmail.com',
    description='MagnaX - Real-time collection tool for Android/iOS performance data.',
    long_description=long_description,
    long_description_content_type="text/markdown",
    url='https://github.com/smart-test-ti/MagnaX',
    license='MIT',
    python_requires='>=3.10',
    packages=setuptools.find_packages(include=["magnax", "magnax.*"]),
    include_package_data=True,
    install_requires=[
        'flask>=3.1.0',
        'requests>=2.28.2',
        'loguru',
        'fire',
        'tqdm',
        'openpyxl>=3.1.0',
        'pyfiglet',
        'psutil',
        'opencv-python',
        'pymobiledevice3>=2.0.0',
    ],
    entry_points={
        'console_scripts': [
            'magnax=magnax.__main__:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Console',
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
        'Topic :: Software Development :: Testing',
        'Topic :: System :: Monitoring',
    ],
    keywords='android ios performance testing monitoring apm',
)
