# Quoteable Window Monitor Deploy

Canonical server layout:

- repo: `/root/polymarket-bot`
- env file: `/etc/default/polymarket-bot`
- samples: `/root/polymarket-bot/data/reports/quoteable_window_monitor_samples.jsonl`
- latest json: `/root/polymarket-bot/data/reports/quoteable_window_monitor_latest.json`
- latest md: `/root/polymarket-bot/data/reports/quoteable_window_monitor_latest.md`

Recommended model:

- `pm-quoteable-window-monitor.service` runs as `Type=oneshot`
- `pm-quoteable-window-monitor.timer` triggers every 5 minutes
- each run fetches one sample, appends JSONL, rebuilds latest JSON/MD, then exits

Suggested `/etc/default/polymarket-bot`:

```bash
POLYMARKET_BOT_REPO_ROOT=/root/polymarket-bot
POLYMARKET_BOT_PYTHON=/root/polymarket-bot/.venv/bin/python
POLYMARKET_ENV=research
POLYMARKET_CONFIG_PATH=config.yaml
POLYMARKET_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/polymarket_bot
POLYMARKET_GAMMA_API_URL=https://gamma-api.polymarket.com
POLYMARKET_CLOB_API_URL=https://clob.polymarket.com
POLYMARKET_DATA_API_URL=https://data-api.polymarket.com
POLYMARKET_CHAIN_ID=137
POLYMARKET_ENABLE_LIVE_TRADING=false
```

Install steps:

```bash
cd /root
git clone https://github.com/MihaiCatalinVoicu/Pollymarket.git polymarket-bot
cd /root/polymarket-bot
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -e ".[dev,clob]"
cp config.yaml.example config.yaml
install -d /etc/default
cp /root/polymarket-bot/ops/systemd/pm-quoteable-window-monitor.service /etc/systemd/system/
cp /root/polymarket-bot/ops/systemd/pm-quoteable-window-monitor.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now pm-quoteable-window-monitor.timer
systemctl start pm-quoteable-window-monitor.service
```

Smoke checks:

```bash
systemctl status pm-quoteable-window-monitor.service --no-pager
systemctl status pm-quoteable-window-monitor.timer --no-pager
journalctl -u pm-quoteable-window-monitor.service -n 100 --no-pager
cat /root/polymarket-bot/data/reports/quoteable_window_monitor_latest.json
```
