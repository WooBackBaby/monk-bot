#!/usr/bin/env python3
"""
Monk Bot - BTC/ETH Divergence Alert Bot

Monitors BTC/ETH price divergence and sends Telegram alerts
for ENTRY, EXIT, and INVALIDATION signals.
"""
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional, Tuple, NamedTuple

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
# Data Structures
# =============================================================================
class Mode(Enum):
    SCAN = "SCAN"
    TRACK = "TRACK"


class Strategy(Enum):
    S1 = "S1"  # Long BTC / Short ETH (when ETH pumps more)
    S2 = "S2"  # Long ETH / Short BTC (when ETH dumps more)


class PriceData(NamedTuple):
    btc_price: Decimal
    eth_price: Decimal
    btc_updated_at: datetime
    eth_updated_at: datetime


# =============================================================================
# Global State
# =============================================================================
previous_btc: Optional[Decimal] = None
previous_eth: Optional[Decimal] = None
current_mode: Mode = Mode.SCAN
active_strategy: Optional[Strategy] = None


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
def build_entry_message(strategy: Strategy, btc_ret: Decimal, eth_ret: Decimal, gap: Decimal) -> str:
    """Build ENTRY alert message."""
    if strategy == Strategy.S1:
        direction = "📈 Long BTC / Short ETH"
        reason = "ETH pumped more than BTC"
    else:
        direction = "📈 Long ETH / Short BTC"
        reason = "ETH dumped more than BTC"

    return (
        f"🚨 *ENTRY SIGNAL: {strategy.value}*\n"
        f"\n"
        f"{direction}\n"
        f"_{reason}_\n"
        f"\n"
        f"*Change Since Last Scan:*\n"
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
    return (
        f"✅ *EXIT SIGNAL*\n"
        f"\n"
        f"Gap converged - position profitable.\n"
        f"\n"
        f"*Change Since Last Scan:*\n"
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
    return (
        f"⚠️ *INVALIDATION: {strategy.value}*\n"
        f"\n"
        f"Gap widened further - consider closing.\n"
        f"\n"
        f"*Change Since Last Scan:*\n"
        f"┌─────────────────────\n"
        f"│ BTC:  {format_value(btc_ret)}%\n"
        f"│ ETH:  {format_value(eth_ret)}%\n"
        f"│ Gap:  {format_value(gap)}%\n"
        f"└─────────────────────\n"
        f"\n"
        f"🔍 Returning to scan mode"
    )


def build_no_signal_message(btc_price: Decimal, eth_price: Decimal, btc_ret: Decimal, eth_ret: Decimal, gap: Decimal) -> str:
    """Build no-signal status message."""
    return (
        f"🔍 *Scan Complete*\n"
        f"\n"
        f"No divergence detected.\n"
        f"\n"
        f"💰 *Current Prices:*\n"
        f"┌─────────────────────\n"
        f"│ BTC: ${float(btc_price):,.2f}\n"
        f"│ ETH: ${float(eth_price):,.2f}\n"
        f"└─────────────────────\n"
        f"\n"
        f"*Change Since Last Scan:*\n"
        f"┌─────────────────────\n"
        f"│ BTC:  {format_value(btc_ret)}%\n"
        f"│ ETH:  {format_value(eth_ret)}%\n"
        f"│ Gap:  {format_value(gap)}%\n"
        f"└─────────────────────\n"
        f"\n"
        f"⏳ Next scan in 5 minutes..."
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
# Return Calculation
# =============================================================================
def compute_returns(
    btc_now: Decimal, eth_now: Decimal, btc_prev: Decimal, eth_prev: Decimal
) -> Tuple[Decimal, Decimal, Decimal]:
    """
    Compute percentage change since last scan and gap.
    Returns: (btc_change_pct, eth_change_pct, gap)
    Gap = ETH change - BTC change
    Positive gap = ETH moved more than BTC (pumped more or dumped less)
    Negative gap = BTC moved more than ETH (pumped more or dumped less)
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
    
    if current_mode == Mode.SCAN:
        # Check for entry signals
        if gap_float >= ENTRY_THRESHOLD:
            # S1: Long BTC / Short ETH
            active_strategy = Strategy.S1
            current_mode = Mode.TRACK
            message = build_entry_message(Strategy.S1, btc_ret, eth_ret, gap)
            send_alert(message)
            logger.info(f"ENTRY S1 triggered. Gap: {gap_float:.2f}%")
        
        elif gap_float <= -ENTRY_THRESHOLD:
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
        if abs(gap_float) <= EXIT_THRESHOLD:
            message = build_exit_message(btc_ret, eth_ret, gap)
            send_alert(message)
            logger.info(f"EXIT triggered. Gap: {gap_float:.2f}%")
            current_mode = Mode.SCAN
            active_strategy = None
            return
        
        # Check for invalidation
        if active_strategy == Strategy.S1 and gap_float >= INVALIDATION_THRESHOLD:
            message = build_invalidation_message(Strategy.S1, btc_ret, eth_ret, gap)
            send_alert(message)
            logger.info(f"INVALIDATION S1 triggered. Gap: {gap_float:.2f}%")
            current_mode = Mode.SCAN
            active_strategy = None
            return
        
        if active_strategy == Strategy.S2 and gap_float <= -INVALIDATION_THRESHOLD:
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
    
    message = (
        "🤖 *Monk Bot Started*\n"
        f"{price_info}"
        "\n"
        f"📈 Entry threshold: ±{ENTRY_THRESHOLD}%\n"
        f"📉 Exit threshold: ±{EXIT_THRESHOLD}%\n"
        f"⚠️ Invalidation: ±{INVALIDATION_THRESHOLD}%\n"
        "\n"
        "🔍 Scanning for BTC/ETH divergence..."
    )
    return send_alert(message)


# =============================================================================
# Main Loop
# =============================================================================
def main_loop() -> None:
    """Main polling and evaluation loop."""
    global current_mode, active_strategy, previous_btc, previous_eth

    logger.info("=" * 60)
    logger.info("Monk Bot starting")
    logger.info(f"Thresholds - Entry: {ENTRY_THRESHOLD}%, Exit: {EXIT_THRESHOLD}%, Invalidation: {INVALIDATION_THRESHOLD}%")
    logger.info(f"Scan interval: {SCAN_INTERVAL_SECONDS}s")
    logger.info("=" * 60)

    # Send startup message to verify Telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        if send_startup_message():
            logger.info("Startup message sent to Telegram")
        else:
            logger.error("Failed to send startup message - check credentials")

    while True:
        try:
            now = datetime.now(timezone.utc)
            signal_triggered = False
            
            # Fetch prices
            price_data = fetch_prices()
            
            if price_data is None:
                logger.warning("Failed to fetch prices, skipping this poll")
            else:
                # Check freshness
                if not is_data_fresh(now, price_data.btc_updated_at, price_data.eth_updated_at):
                    logger.warning("Data not fresh, skipping evaluation")
                elif previous_btc is None or previous_eth is None:
                    # First scan - just store prices
                    previous_btc = price_data.btc_price
                    previous_eth = price_data.eth_price
                    logger.info(f"First scan - stored prices. BTC: ${float(previous_btc):,.2f}, ETH: ${float(previous_eth):,.2f}")
                    logger.info("Will compare on next scan in 5 minutes...")
                else:
                    # Compute change since last scan
                    btc_ret, eth_ret, gap = compute_returns(
                        price_data.btc_price,
                        price_data.eth_price,
                        previous_btc,
                        previous_eth,
                    )
                    
                    logger.info(
                        f"Mode: {current_mode.value} | "
                        f"BTC: {format_value(btc_ret)}% | "
                        f"ETH: {format_value(eth_ret)}% | "
                        f"Gap: {format_value(gap)}%"
                    )
                    
                    # Track previous mode to detect signal
                    prev_mode = current_mode
                    
                    # Evaluate state machine
                    evaluate_and_transition(btc_ret, eth_ret, gap)
                    
                    # Check if a signal was triggered (mode changed)
                    if current_mode != prev_mode:
                        signal_triggered = True
                    
                    # Send status message when in SCAN mode and no signal found
                    if current_mode == Mode.SCAN and not signal_triggered:
                        message = build_no_signal_message(
                            price_data.btc_price,
                            price_data.eth_price,
                            btc_ret, eth_ret, gap
                        )
                        send_alert(message)
                        logger.info("No signal - status sent")
                    
                    # Update previous prices for next comparison
                    previous_btc = price_data.btc_price
                    previous_eth = price_data.eth_price
            
            # Sleep based on current mode
            sleep_time = TRACK_INTERVAL_SECONDS if current_mode == Mode.TRACK else SCAN_INTERVAL_SECONDS
            logger.debug(f"Sleeping for {sleep_time} seconds")
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
