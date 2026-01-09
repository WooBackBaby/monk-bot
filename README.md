# Monk Bot - BTC/ETH Divergence Alert Bot

A lightweight Python bot that monitors BTC/ETH price divergence and sends Telegram alerts for trading signals.

## Strategy

The bot implements a pairs trading strategy based on BTC/ETH relative performance:

**Strategy 1 (S1): Long BTC / Short ETH**
- Triggers when ETH pumps more than BTC (gap >= +2%)
- ETH outperforming = expect reversion

**Strategy 2 (S2): Long ETH / Short BTC**  
- Triggers when ETH dumps more than BTC (gap <= -2%)
- ETH underperforming = expect reversion

### How It Works

1. Bot scans BTC and ETH prices every 5 minutes
2. Calculates % change since last scan for each
3. Gap = ETH change - BTC change
4. If gap exceeds threshold, sends alert

### Signal Types

| Signal | Condition | Action |
|--------|-----------|--------|
| **S1 ENTRY** | Gap >= +2.0% | Long BTC / Short ETH |
| **S2 ENTRY** | Gap <= -2.0% | Long ETH / Short BTC |
| **EXIT** | Gap returns to ±0.5% | Close positions |
| **INVALIDATION** | Gap exceeds ±4.0% | Stop loss |

## Requirements

- Python 3.10+
- Linux server (Ubuntu 22.04/24.04 recommended)
- Telegram bot token

## Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/monk-bot.git
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

Edit `config.py` to customize thresholds:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `ENTRY_THRESHOLD` | 2.0 | Gap % to trigger entry |
| `EXIT_THRESHOLD` | 0.5 | Gap % to trigger exit |
| `INVALIDATION_THRESHOLD` | 4.0 | Gap % for stop loss |
| `SCAN_INTERVAL_SECONDS` | 300 | Time between scans (5 min) |

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
