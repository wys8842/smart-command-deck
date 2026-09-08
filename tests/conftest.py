# -*- coding: utf-8 -*-
"""pytest 共享配置：安装 Python 3.10 asyncio.timeout 兼容垫片。"""
from app.core.compat import install_asyncio_timeout_compat

install_asyncio_timeout_compat()
