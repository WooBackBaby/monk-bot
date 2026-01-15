#!/usr/bin/env python3
"""
Monk Bot - BTC/ETH Divergence Alert Bot

Monitors BTC/ETH price divergence and sends Telegram alerts
for ENTRY, EXIT, and INVALIDATION signals.
"""
import time
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional, Tuple, List, NamedTuple

import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    API_BASE_URL,
    API_ENDPOINT,
    SCAN_INTERVAL_SECONDS,
    TRACK_INTERVAL_SECONDS,
    FRESHNESS_THRESHOLD_MINUTES,
    ENTRY_THRESHOLD,
    EXIT_THRESHOLD,
    INVALIDATION_THRESHOLD,
    logger,
)


# =============================================================================
# Constants
# =============================================================================
DEFAULT_LOOKBACK_HOURS = 1  # Default to 1h for faster startup
HISTORY_BUFFER_MINUTES = 30  # Extra buffer beyond lookback period


# =============================================================================
# Data Structures
# =============================================================================
class Mode(Enum):
    SCAN = "SCAN"
    TRACK = "TRACK"


class Strategy(Enum):
    S1 = "S1"  # Long BTC / Short ETH (when ETH pumps more)
    S2 = "S2"  # Long ETH / Short BTC (when ETH dumps more)


class PricePoint(NamedTuple):
    timestamp: datetime
    btc: Decimal
    eth: Decimal


class PriceData(NamedTuple):
    btc_price: Decimal
    eth_price: Decimal
    btc_updated_at: datetime
    eth_updated_at: datetime


# =============================================================================
# Global State
# =============================================================================
price_history: List[PricePoint] = []
current_mode: Mode = Mode.SCAN
active_strategy: Optional[Strategy] = None

# Runtime settings (can be changed via Telegram commands)
settings = {
    "scan_interval": SCAN_INTERVAL_SECONDS,
    "entry_threshold": ENTRY_THRESHOLD,
    "exit_threshold": EXIT_THRESHOLD,
    "invalidation_threshold": INVALIDATION_THRESHOLD,
    "lookback_hours": DEFAULT_LOOKBACK_HOURS,
}

# Track last processed update to avoid duplicates
last_update_id: int = 0


# =============================================================================
# Telegram Bot
# =============================================================================
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def send_alert(message: str) -> bool:
    """Send a Telegram alert message via HTTP API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured, skipping alert")
        return False

    try:
        response = requests.post(
            TELEGRAM_API_URL,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        logger.info("Alert sent successfully")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send Telegram alert: {e}")
        return False


# =============================================================================
# Telegram Command Handling
# =============================================================================
# Long polling timeout - Telegram keeps connection open until update arrives
LONG_POLL_TIMEOUT = 30  # seconds


def get_telegram_updates() -> list:
    """
    Fetch new messages/commands from Telegram using long polling.
    
    Long polling is Telegram's recommended approach - the connection stays
    open until an update arrives (or timeout), avoiding constant requests.
    """
    global last_update_id
    
    if not TELEGRAM_BOT_TOKEN:
        return []
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        # Long polling: Telegram holds connection open until update or timeout
        params = {"offset": last_update_id + 1, "timeout": LONG_POLL_TIMEOUT}
        # Request timeout must be > long poll timeout
        response = requests.get(url, params=params, timeout=LONG_POLL_TIMEOUT + 5)
        response.raise_for_status()
        data = response.json()
        
        if data.get("ok") and data.get("result"):
            updates = data["result"]
            if updates:
                last_update_id = updates[-1]["update_id"]
            return updates
    except requests.RequestException as e:
        logger.debug(f"Failed to get updates: {e}")
    
    return []


def process_commands() -> None:
    """Process incoming Telegram commands."""
    updates = get_telegram_updates()
    
    for update in updates:
        message = update.get("message", {})
        text = message.get("text", "")
        chat_id = str(message.get("chat", {}).get("id", ""))
        user_id = str(message.get("from", {}).get("id", ""))
        
        # Accept commands from the configured channel/group OR from DMs
        # For DMs, the chat_id equals the user_id
        is_authorized = (chat_id == TELEGRAM_CHAT_ID) or (chat_id == user_id)
        
        if not is_authorized:
            logger.debug(f"Ignoring command from unauthorized chat: {chat_id}")
            continue
        
        if not text.startswith("/"):
            continue
        
        # Store the reply chat for command responses
        reply_chat = chat_id
        
        parts = text.split()
        command = parts[0].lower().split("@")[0]  # Handle /command@botname format
        args = parts[1:] if len(parts) > 1 else []
        
        logger.info(f"Processing command: {command} from chat {chat_id}")
        
        if command == "/settings":
            handle_settings_command(reply_chat)
        elif command == "/interval":
            handle_interval_command(args, reply_chat)
        elif command == "/threshold":
            handle_threshold_command(args, reply_chat)
        elif command == "/help":
            handle_help_command(reply_chat)
        elif command == "/status":
            handle_status_command(reply_chat)
        elif command == "/lookback":
            handle_lookback_command(args, reply_chat)
        elif command == "/start":
            handle_help_command(reply_chat)


def send_reply(message: str, chat_id: str) -> bool:
    """Send a reply to a specific chat."""
    if not TELEGRAM_BOT_TOKEN:
        return False
    
    try:
        response = requests.post(
            TELEGRAM_API_URL,
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to send reply: {e}")
        return False


def handle_settings_command(reply_chat: str) -> None:
    """Show current settings."""
    message = (
        "⚙️ *Current Settings*\n"
        "\n"
        f"📊 Scan Interval: {settings['scan_interval']} seconds ({settings['scan_interval'] // 60} min)\n"
        f"🕐 Lookback Period: {settings['lookback_hours']}h\n"
        f"📈 Entry Threshold: ±{settings['entry_threshold']}%\n"
        f"📉 Exit Threshold: ±{settings['exit_threshold']}%\n"
        f"⚠️ Invalidation: ±{settings['invalidation_threshold']}%\n"
        "\n"
        "*Commands:*\n"
        "`/interval <seconds>` - Set scan interval\n"
        "`/lookback <hours>` - Set lookback (1-24h)\n"
        "`/threshold <type> <value>` - Set thresholds\n"
        "`/help` - Show all commands"
    )
    send_reply(message, reply_chat)


def handle_interval_command(args: list, reply_chat: str) -> None:
    """Set scan interval."""
    if not args:
        send_reply("❌ Usage: `/interval <seconds>`\nExample: `/interval 300`", reply_chat)
        return
    
    try:
        new_interval = int(args[0])
        if new_interval < 60:
            send_reply("❌ Minimum interval is 60 seconds", reply_chat)
            return
        if new_interval > 3600:
            send_reply("❌ Maximum interval is 3600 seconds (1 hour)", reply_chat)
            return
        
        settings["scan_interval"] = new_interval
        send_reply(f"✅ Scan interval set to *{new_interval} seconds* ({new_interval // 60} min)", reply_chat)
        logger.info(f"Scan interval changed to {new_interval}s via command")
    except ValueError:
        send_reply("❌ Invalid number. Usage: `/interval <seconds>`", reply_chat)


def handle_threshold_command(args: list, reply_chat: str) -> None:
    """Set thresholds."""
    if len(args) < 1:
        send_reply(
            "❌ Usage:\n"
            "`/threshold entry <value>` - Set entry threshold\n"
            "`/threshold exit <value>` - Set exit threshold\n"
            "`/threshold invalid <value>` - Set invalidation\n"
            "\nExample: `/threshold entry 2.5`",
            reply_chat
        )
        return
    
    if len(args) < 2:
        send_reply("❌ Please provide a value. Example: `/threshold entry 2.5`", reply_chat)
        return
    
    try:
        threshold_type = args[0].lower()
        value = float(args[1])
        
        if value <= 0:
            send_reply("❌ Threshold must be positive", reply_chat)
            return
        if value > 20:
            send_reply("❌ Maximum threshold is 20%", reply_chat)
            return
        
        if threshold_type == "entry":
            settings["entry_threshold"] = value
            send_reply(f"✅ Entry threshold set to *±{value}%*", reply_chat)
        elif threshold_type == "exit":
            settings["exit_threshold"] = value
            send_reply(f"✅ Exit threshold set to *±{value}%*", reply_chat)
        elif threshold_type in ("invalid", "invalidation"):
            settings["invalidation_threshold"] = value
            send_reply(f"✅ Invalidation threshold set to *±{value}%*", reply_chat)
        else:
            send_reply("❌ Unknown threshold type. Use: `entry`, `exit`, or `invalid`", reply_chat)
        
        logger.info(f"Threshold {threshold_type} changed to {value} via command")
    except ValueError:
        send_reply("❌ Invalid number", reply_chat)


def handle_lookback_command(args: list, reply_chat: str) -> None:
    """Set lookback period in hours."""
    global price_history
    
    if not args:
        send_reply(
            f"📊 Current lookback: *{settings['lookback_hours']}h*\n\n"
            "Usage: `/lookback <hours>`\n"
            "Example: `/lookback 1` or `/lookback 24`",
            reply_chat
        )
        return
    
    try:
        new_lookback = int(args[0])
        if new_lookback < 1:
            send_reply("❌ Minimum lookback is 1 hour", reply_chat)
            return
        if new_lookback > 24:
            send_reply("❌ Maximum lookback is 24 hours", reply_chat)
            return
        
        old_lookback = settings["lookback_hours"]
        settings["lookback_hours"] = new_lookback
        
        # Clear history when changing lookback to rebuild
        price_history = []
        
        send_reply(
            f"✅ Lookback changed from *{old_lookback}h* to *{new_lookback}h*\n\n"
            f"⚠️ Price history cleared - collecting new {new_lookback}h data...",
            reply_chat
        )
        logger.info(f"Lookback changed from {old_lookback}h to {new_lookback}h via command")
    except ValueError:
        send_reply("❌ Invalid number. Usage: `/lookback <hours>`", reply_chat)


def handle_help_command(reply_chat: str) -> None:
    """Show help message."""
    message = (
        "🤖 *Monk Bot Commands*\n"
        "\n"
        "*Settings:*\n"
        "`/settings` - Show current settings\n"
        "`/interval <sec>` - Set scan interval (60-3600)\n"
        "`/lookback <hours>` - Set lookback period (1-24)\n"
        "`/threshold entry <val>` - Entry threshold %\n"
        "`/threshold exit <val>` - Exit threshold %\n"
        "`/threshold invalid <val>` - Invalidation %\n"
        "\n"
        "*Info:*\n"
        "`/status` - Show bot status\n"
        "`/help` - This message"
    )
    send_reply(message, reply_chat)


def handle_status_command(reply_chat: str) -> None:
    """Show bot status."""
    hours_of_data = len(price_history) * settings["scan_interval"] / 3600
    lookback = settings["lookback_hours"]
    ready = "✅ Ready" if hours_of_data >= lookback else f"⏳ {hours_of_data:.1f}h / {lookback}h"
    
    message = (
        "📊 *Bot Status*\n"
        "\n"
        f"Mode: {current_mode.value}\n"
        f"Active Strategy: {active_strategy.value if active_strategy else 'None'}\n"
        f"Lookback: {lookback}h\n"
        f"History: {ready}\n"
        f"Data Points: {len(price_history)}\n"
    )
    send_reply(message, reply_chat)


# =============================================================================
# Value Formatting
# =============================================================================
def format_value(value: Decimal) -> str:
    """
    Format a percentage value with explicit sign and 1 decimal place.
    Clamps values with abs < 0.05 to +0.0 to avoid -0.0.
    """
    float_val = float(value)
    
    # Clamp near-zero values to avoid -0.0
    if abs(float_val) < 0.05:
        return "+0.0"
    
    if float_val >= 0:
        return f"+{float_val:.1f}"
    else:
        return f"{float_val:.1f}"


# =============================================================================
# Message Building
# =============================================================================
def get_lookback_label() -> str:
    """Get human-readable lookback period label."""
    hours = settings["lookback_hours"]
    if hours == 1:
        return "1h"
    elif hours == 24:
        return "24h"
    else:
        return f"{hours}h"


def build_entry_message(strategy: Strategy, btc_ret: Decimal, eth_ret: Decimal, gap: Decimal) -> str:
    """Build ENTRY alert message."""
    lb = get_lookback_label()
    if strategy == Strategy.S1:
        direction = "📈 Long BTC / Short ETH"
        reason = f"ETH pumped more than BTC ({lb})"
    else:
        direction = "📈 Long ETH / Short BTC"
        reason = f"ETH dumped more than BTC ({lb})"

    return (
        f"🚨 *ENTRY SIGNAL: {strategy.value}*\n"
        f"\n"
        f"{direction}\n"
        f"_{reason}_\n"
        f"\n"
        f"*{lb} Change:*\n"
        f"┌─────────────────────\n"
        f"│ BTC:  {format_value(btc_ret)}%\n"
        f"│ ETH:  {format_value(eth_ret)}%\n"
        f"│ Gap:  {format_value(gap)}%\n"
        f"└─────────────────────\n"
        f"\n"
        f"⏰ Tracking mode activated"
    )


def build_exit_message(btc_ret: Decimal, eth_ret: Decimal, gap: Decimal) -> str:
    """Build EXIT alert message."""
    lb = get_lookback_label()
    return (
        f"✅ *EXIT SIGNAL*\n"
        f"\n"
        f"Gap converged - position profitable.\n"
        f"\n"
        f"*{lb} Change:*\n"
        f"┌─────────────────────\n"
        f"│ BTC:  {format_value(btc_ret)}%\n"
        f"│ ETH:  {format_value(eth_ret)}%\n"
        f"│ Gap:  {format_value(gap)}%\n"
        f"└─────────────────────\n"
        f"\n"
        f"🔍 Returning to scan mode"
    )


def build_invalidation_message(strategy: Strategy, btc_ret: Decimal, eth_ret: Decimal, gap: Decimal) -> str:
    """Build INVALIDATION alert message."""
    lb = get_lookback_label()
    return (
        f"⚠️ *INVALIDATION: {strategy.value}*\n"
        f"\n"
        f"Gap widened further - consider closing.\n"
        f"\n"
        f"*{lb} Change:*\n"
        f"┌─────────────────────\n"
        f"│ BTC:  {format_value(btc_ret)}%\n"
        f"│ ETH:  {format_value(eth_ret)}%\n"
        f"│ Gap:  {format_value(gap)}%\n"
        f"└─────────────────────\n"
        f"\n"
        f"🔍 Returning to scan mode"
    )


# =============================================================================
# API Fetching
# =============================================================================
def parse_iso_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse ISO 8601 timestamp to UTC datetime."""
    try:
        # Handle various ISO formats
        ts_str = ts_str.replace("Z", "+00:00")
        # Remove nanoseconds beyond microseconds
        if "." in ts_str:
            base, frac_and_tz = ts_str.split(".", 1)
            # Find where timezone starts
            tz_start = -1
            for i, c in enumerate(frac_and_tz):
                if c in ("+", "-"):
                    tz_start = i
                    break
            if tz_start > 6:
                frac_and_tz = frac_and_tz[:6] + frac_and_tz[tz_start:]
            ts_str = base + "." + frac_and_tz
        
        dt = datetime.fromisoformat(ts_str)
        # Ensure UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError) as e:
        logger.error(f"Failed to parse timestamp '{ts_str}': {e}")
        return None


def fetch_prices() -> Optional[PriceData]:
    """
    Fetch BTC and ETH prices from the API.
    Returns None if required data is missing or request fails.
    """
    url = f"{API_BASE_URL}{API_ENDPOINT}"
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        logger.error(f"API request failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"Invalid JSON response: {e}")
        return None

    listings = data.get("listings", [])
    if not listings:
        logger.warning("No listings in API response")
        return None

    btc_data = None
    eth_data = None

    for listing in listings:
        ticker = listing.get("ticker", "").upper()
        if ticker == "BTC":
            btc_data = listing
        elif ticker == "ETH":
            eth_data = listing

    if not btc_data or not eth_data:
        logger.warning(f"Missing BTC or ETH data. BTC: {btc_data is not None}, ETH: {eth_data is not None}")
        return None

    # Extract mark_price
    btc_price_str = btc_data.get("mark_price")
    eth_price_str = eth_data.get("mark_price")

    if not btc_price_str or not eth_price_str:
        logger.warning("Missing mark_price field")
        return None

    try:
        btc_price = Decimal(btc_price_str)
        eth_price = Decimal(eth_price_str)
    except InvalidOperation as e:
        logger.error(f"Invalid price format: {e}")
        return None

    # Extract updated_at from quotes
    btc_quotes = btc_data.get("quotes", {})
    eth_quotes = eth_data.get("quotes", {})

    btc_updated_str = btc_quotes.get("updated_at")
    eth_updated_str = eth_quotes.get("updated_at")

    if not btc_updated_str or not eth_updated_str:
        logger.warning("Missing quotes.updated_at field")
        return None

    btc_updated_at = parse_iso_timestamp(btc_updated_str)
    eth_updated_at = parse_iso_timestamp(eth_updated_str)

    if not btc_updated_at or not eth_updated_at:
        return None

    logger.debug(f"Fetched prices - BTC: {btc_price}, ETH: {eth_price}")
    return PriceData(btc_price, eth_price, btc_updated_at, eth_updated_at)


# =============================================================================
# Price History Management
# =============================================================================
def append_price(timestamp: datetime, btc: Decimal, eth: Decimal) -> None:
    """Append a new price point to history."""
    price_history.append(PricePoint(timestamp, btc, eth))
    logger.debug(f"Stored price point: BTC=${float(btc):,.2f}, ETH=${float(eth):,.2f}")


def prune_history(now: datetime) -> None:
    """Remove price points older than lookback period + buffer."""
    global price_history
    lookback = settings["lookback_hours"]
    cutoff = now - timedelta(hours=lookback, minutes=HISTORY_BUFFER_MINUTES)
    original_len = len(price_history)
    price_history = [p for p in price_history if p.timestamp >= cutoff]
    pruned = original_len - len(price_history)
    if pruned > 0:
        logger.debug(f"Pruned {pruned} old price points, {len(price_history)} remaining")


def get_lookback_price(now: datetime) -> Optional[PricePoint]:
    """
    Find the price point closest to lookback_hours ago.
    Returns None if no data from that time exists.
    """
    lookback = settings["lookback_hours"]
    target_time = now - timedelta(hours=lookback)
    
    # Find the closest point to target time (within 30 min tolerance)
    best_point = None
    best_diff = timedelta(minutes=30)  # Max tolerance
    
    for point in price_history:
        diff = abs(point.timestamp - target_time)
        if diff < best_diff:
            best_diff = diff
            best_point = point
    
    return best_point


# =============================================================================
# Return Calculation
# =============================================================================
def compute_returns(
    btc_now: Decimal, eth_now: Decimal, btc_prev: Decimal, eth_prev: Decimal
) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Compute percentage change and gap.
    Formula: (Current - Previous) / Previous × 100
    Returns: (btc_change_pct, eth_change_pct, gap)
    Gap = ETH change - BTC change
    Positive gap = ETH outperformed BTC
    Negative gap = BTC outperformed ETH
    """
    btc_change = (btc_now - btc_prev) / btc_prev * Decimal("100")
    eth_change = (eth_now - eth_prev) / eth_prev * Decimal("100")
    gap = eth_change - btc_change
    return btc_change, eth_change, gap


# =============================================================================
# Freshness Check
# =============================================================================
def is_data_fresh(now: datetime, btc_updated: datetime, eth_updated: datetime) -> bool:
    """Check if both BTC and ETH data are fresh (updated within threshold)."""
    threshold = timedelta(minutes=FRESHNESS_THRESHOLD_MINUTES)
    btc_age = now - btc_updated
    eth_age = now - eth_updated
    
    if btc_age > threshold:
        logger.debug(f"BTC data stale: {btc_age}")
        return False
    if eth_age > threshold:
        logger.debug(f"ETH data stale: {eth_age}")
        return False
    
    return True


# =============================================================================
# State Machine
# =============================================================================
def evaluate_and_transition(
    btc_ret: Decimal, eth_ret: Decimal, gap: Decimal
) -> None:
    """Evaluate gap and perform state transitions."""
    global current_mode, active_strategy

    gap_float = float(gap)
    
    entry_thresh = settings["entry_threshold"]
    exit_thresh = settings["exit_threshold"]
    invalid_thresh = settings["invalidation_threshold"]
    
    if current_mode == Mode.SCAN:
        # Check for entry signals
        if gap_float >= entry_thresh:
            # S1: Long BTC / Short ETH
            active_strategy = Strategy.S1
            current_mode = Mode.TRACK
            message = build_entry_message(Strategy.S1, btc_ret, eth_ret, gap)
            send_alert(message)
            logger.info(f"ENTRY S1 triggered. Gap: {gap_float:.2f}%")
        
        elif gap_float <= -entry_thresh:
            # S2: Long ETH / Short BTC
            active_strategy = Strategy.S2
            current_mode = Mode.TRACK
            message = build_entry_message(Strategy.S2, btc_ret, eth_ret, gap)
            send_alert(message)
            logger.info(f"ENTRY S2 triggered. Gap: {gap_float:.2f}%")
        
        else:
            logger.debug(f"SCAN: No entry signal. Gap: {gap_float:.2f}%")
    
    elif current_mode == Mode.TRACK:
        # Check for exit
        if abs(gap_float) <= exit_thresh:
            message = build_exit_message(btc_ret, eth_ret, gap)
            send_alert(message)
            logger.info(f"EXIT triggered. Gap: {gap_float:.2f}%")
            current_mode = Mode.SCAN
            active_strategy = None
            return
        
        # Check for invalidation
        if active_strategy == Strategy.S1 and gap_float >= invalid_thresh:
            message = build_invalidation_message(Strategy.S1, btc_ret, eth_ret, gap)
            send_alert(message)
            logger.info(f"INVALIDATION S1 triggered. Gap: {gap_float:.2f}%")
            current_mode = Mode.SCAN
            active_strategy = None
            return
        
        if active_strategy == Strategy.S2 and gap_float <= -invalid_thresh:
            message = build_invalidation_message(Strategy.S2, btc_ret, eth_ret, gap)
            send_alert(message)
            logger.info(f"INVALIDATION S2 triggered. Gap: {gap_float:.2f}%")
            current_mode = Mode.SCAN
            active_strategy = None
            return
        
        logger.debug(f"TRACK ({active_strategy.value if active_strategy else 'None'}): Gap: {gap_float:.2f}%")


# =============================================================================
# Startup Message
# =============================================================================
def send_startup_message() -> bool:
    """Send a startup test message with current prices."""
    # Fetch current prices
    price_data = fetch_prices()
    
    if price_data:
        btc_price = f"${float(price_data.btc_price):,.2f}"
        eth_price = f"${float(price_data.eth_price):,.2f}"
        price_info = (
            f"\n"
            f"💰 *Current Prices:*\n"
            f"┌─────────────────────\n"
            f"│ BTC: {btc_price}\n"
            f"│ ETH: {eth_price}\n"
            f"└─────────────────────\n"
        )
    else:
        price_info = "\n⚠️ Unable to fetch current prices\n"
    
    lb = get_lookback_label()
    message = (
        "🤖 *Monk Bot Started*\n"
        f"{price_info}"
        "\n"
        f"📊 Rolling {lb} % change (perp-exchange style)\n"
        f"📈 Entry threshold: ±{settings['entry_threshold']}%\n"
        f"📉 Exit threshold: ±{settings['exit_threshold']}%\n"
        f"⚠️ Invalidation: ±{settings['invalidation_threshold']}%\n"
        f"⏱️ Scan interval: {settings['scan_interval']}s\n"
        "\n"
        f"⏳ Building {lb} price history...\n"
        f"_Signals will start after {lb} of data collected_\n"
        "\n"
        "💡 Type `/help` for commands"
    )
    return send_alert(message)


# =============================================================================
# Command Polling Thread
# =============================================================================
command_thread_running = True


def command_polling_thread() -> None:
    """
    Background thread using Telegram long polling.
    
    Long polling keeps the connection open until an update arrives,
    so commands are received instantly without hammering the API.
    """
    global command_thread_running
    
    while command_thread_running:
        try:
            process_commands()
            # No sleep needed - long polling waits up to 30s for updates
        except Exception as e:
            logger.debug(f"Command polling error: {e}")
            time.sleep(5)  # Brief pause only on errors


# =============================================================================
# Main Loop
# =============================================================================
def main_loop() -> None:
    """Main polling and evaluation loop."""
    global current_mode, active_strategy, command_thread_running

    logger.info("=" * 60)
    logger.info("Monk Bot starting")
    logger.info(f"Using rolling {settings['lookback_hours']}h price change (perp-exchange style)")
    logger.info(f"Thresholds - Entry: {settings['entry_threshold']}%, Exit: {settings['exit_threshold']}%, Invalidation: {settings['invalidation_threshold']}%")
    logger.info(f"Scan interval: {settings['scan_interval']}s")
    logger.info("=" * 60)

    # Start command polling thread
    cmd_thread = threading.Thread(target=command_polling_thread, daemon=True)
    cmd_thread.start()
    logger.info("Command listener started (long polling - instant response)")

    # Send startup message to verify Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        if send_startup_message():
            logger.info("Startup message sent to Telegram")
        else:
            logger.error("Failed to send startup message - check credentials")

    while True:
        try:
            now = datetime.now(timezone.utc)
            
            # Fetch prices
            price_data = fetch_prices()
            
            if price_data is None:
                logger.warning("Failed to fetch prices, skipping this poll")
            else:
                # Check freshness
                if not is_data_fresh(now, price_data.btc_updated_at, price_data.eth_updated_at):
                    logger.warning("Data not fresh, skipping evaluation")
                else:
                    # Store current price in history
                    append_price(now, price_data.btc_price, price_data.eth_price)
                    
                    # Prune old data
                    prune_history(now)
                    
                    # Get price from lookback period ago
                    lb = settings["lookback_hours"]
                    price_then = get_lookback_price(now)
                    
                    if price_then is None:
                        hours_of_data = len(price_history) * settings["scan_interval"] / 3600
                        logger.info(f"Building {lb}h history... ({hours_of_data:.1f}h collected, need {lb}h)")
                    else:
                        # Compute % change (perp-exchange style)
                        btc_ret, eth_ret, gap = compute_returns(
                            price_data.btc_price,
                            price_data.eth_price,
                            price_then.btc,
                            price_then.eth,
                        )
                        
                        logger.info(
                            f"Mode: {current_mode.value} | "
                            f"BTC {lb}h: {format_value(btc_ret)}% | "
                            f"ETH {lb}h: {format_value(eth_ret)}% | "
                            f"Gap: {format_value(gap)}%"
                        )
                        
                        # Track previous mode to detect signal
                        prev_mode = current_mode
                        
                        # Evaluate state machine
                        evaluate_and_transition(btc_ret, eth_ret, gap)
                        
                        # Log if no signal triggered (no message sent - alerts only on entry/exit)
                        if current_mode == prev_mode:
                            logger.info(f"No signal | Gap: {float(gap):.2f}%")
            
            # Sleep until next scan (commands handled by background thread)
            sleep_time = settings["scan_interval"]
            logger.debug(f"Next scan in {sleep_time} seconds")
            time.sleep(sleep_time)
            
        except KeyboardInterrupt:
            logger.info("Received interrupt, shutting down")
            break
        except Exception as e:
            logger.exception(f"Unexpected error: {e}")
            time.sleep(60)  # Brief pause before retrying


# =============================================================================
# Entry Point
# =============================================================================
if __name__ == "__main__":
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set - alerts will be logged only")
    if not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_CHAT_ID not set - alerts will be logged only")
    
    main_loop()
