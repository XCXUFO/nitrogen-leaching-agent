import sys

from loguru import logger


def configure_logging(log_level: str) -> None:
    normalized_level = log_level.upper()
    logger.remove()
    logger.add(sys.stderr, level=normalized_level)
