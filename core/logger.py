"""APEX OMEGA — core/logger.py"""
import logging
import sys

def setup_logging(level=logging.INFO):
    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    logging.basicConfig(stream=sys.stdout, level=level, format=fmt)
    # Silence noisy libs
    for lib in ("httpx", "telegram", "apscheduler", "urllib3"):
        logging.getLogger(lib).setLevel(logging.WARNING)

setup_logging()
