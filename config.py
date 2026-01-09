"""
Configuration for Monk Bot - BTC/ETH Divergence Alert Bot
"""
import os
import logging

# =============================================================================
# Environment Variables
# =============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# =============================================================================
# API Configuration
# =============================================================================
API_BASE_URL = "https://omni-client-api.prod.ap-northeast-1.variational.io"
API_ENDPOINT = "/metadata/stats"

# =============================================================================
# Timing Configuration (in minutes unless noted)
# =============================================================================
SCAN_INTERVAL_SECONDS = 300      # 5 minutes
TRACK_INTERVAL_SECONDS = 300     # 5 minutes
FRESHNESS_THRESHOLD_MINUTES = 10

# =============================================================================
# Strategy Thresholds (percentage points)
# =============================================================================
ENTRY_THRESHOLD = 2.0
EXIT_THRESHOLD = 0.5
INVALIDATION_THRESHOLD = 4.0

# =============================================================================
# Logging Setup
# =============================================================================
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("monk_bot")
