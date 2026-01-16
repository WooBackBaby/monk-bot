# Monk Bot - BTC/ETH Divergence Alert Bot

A lightweight Python bot that monitors BTC/ETH price divergence and sends Telegram alerts for trading signals.

## Strategy

The bot implements a pairs trading strategy based on BTC/ETH relative performance over a configurable lookback period (default: 1 hour).

**Strategy 1 (S1): Long BTC / Short ETH**
- Triggers when ETH pumps more than BTC (gap >= +2%)
- ETH outperforming = expect reversion

**Strategy 2 (S2): Long ETH / Short BTC**  
- Triggers when ETH dumps more than BTC (gap <= -2%)
- ETH underperforming = expect reversion

### How It Works

1. Bot scans BTC and ETH mark prices every 5 minutes
2. Calculates rolling % change over the lookback period (1h-24h)
3. Gap = ETH % change - BTC % change
4. If gap exceeds threshold, sends Telegram alert

### Signal Types

| Signal | Condition | Action |
|--------|-----------|--------|
| **S1 ENTRY** | Gap >= +2.0% | Long BTC / Short ETH |
| **S2 ENTRY** | Gap <= -2.0% | Long ETH / Short BTC |
| **EXIT** | Gap returns to ±0.5% | Close positions |
| **INVALIDATION** | Gap exceeds ±4.0% | Stop loss |

## Telegram Commands

Control the bot directly from Telegram by messaging it:

| Command | Description |
|---------|-------------|
| `/settings` | View current settings |
| `/lookback <hours>` | Set lookback period (1-24h) |
| `/interval <seconds>` | Set scan interval (60-3600s) |
| `/heartbeat <minutes>` | Set status update interval (0 to disable) |
| `/threshold entry <val>` | Set entry threshold % |
| `/threshold exit <val>` | Set exit threshold % |
| `/threshold invalid <val>` | Set invalidation threshold % |
| `/status` | View bot status and data collection progress |
| `/help` | Show all commands |

Commands respond instantly using Telegram long polling.

The bot sends a heartbeat message every 30 minutes (configurable) with a summary of scans performed and current prices.

## Requirements

- Python 3.10+
- Linux server (Ubuntu 22.04/24.04 recommended)
- Telegram bot token

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/WooBackBaby/monk-bot.git
cd monk-bot
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp env.template .env
nano .env
```

Add your Telegram credentials:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
LOG_LEVEL=INFO
```

**Getting Telegram credentials:**
1. Create a bot via [@BotFather](https://t.me/botfather) → get token
2. Message [@userinfobot](https://t.me/userinfobot) → get chat ID

### 4. Test Run

```bash
source venv/bin/activate
export $(cat .env | xargs)
python bot.py
```

## Production Deployment (Ubuntu)

### Automated Install

```bash
sudo ./deploy/install.sh
sudo nano /opt/monk_bot/.env  # Add credentials
sudo systemctl start omni_pairs_bot
sudo systemctl enable omni_pairs_bot
```

### Manual Install

See [detailed deployment guide](deploy/README.md) for step-by-step instructions with security hardening.

### Check Status

```bash
sudo systemctl status omni_pairs_bot
sudo journalctl -u omni_pairs_bot -f
```

## Configuration

Default settings (all configurable via Telegram commands):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `lookback_hours` | 1 | Lookback period for % change (1-24h) |
| `scan_interval` | 300 | Time between scans in seconds (5 min) |
| `heartbeat_minutes` | 30 | Status update interval (0 to disable) |
| `entry_threshold` | 2.0 | Gap % to trigger entry |
| `exit_threshold` | 0.5 | Gap % to trigger exit |
| `invalidation_threshold` | 4.0 | Gap % for stop loss |

**Note:** With 1h lookback, the bot starts sending signals after ~1 hour of data collection. Use `/lookback 24` for daily timeframe analysis.

## API

Uses [Variational Omni API](https://docs.variational.io/technical-documentation/api) for price data:
- Endpoint: `GET /metadata/stats`
- Rate limit: 10 req/10s per IP
- No API key required

## Contributing

Pull requests welcome! Please open an issue first to discuss changes.

## License

MIT License - see [LICENSE](LICENSE) file.

## Disclaimer

This bot is for informational purposes only. Not financial advice. Trade at your own risk.
