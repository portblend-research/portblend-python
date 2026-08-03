"""
PortBlend Python SDK (`portblend`)

Official Python client library for PortBlend strategy correlation calculation,
portfolio weight optimization, and quantitative risk management.
"""

from portblend.client import PortBlendClient
from portblend.models import BlendResult
from portblend.transform import DataTransformer
from portblend.logging import setup_logger, get_logger

__version__ = "0.2.0"

__all__ = [
    "PortBlendClient",
    "BlendResult",
    "DataTransformer",
    "setup_logger",
    "get_logger",
    "__version__",
]
