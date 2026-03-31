# polymarket-bot

Standalone Polymarket lane for `polymarket_mm_v1`: reward-aware passive market making on binary objective markets, with full-set parity monitoring and a tightly gated latency-sensitive repricing overlay.

## Scope Freeze

- Trade only fee-enabled, orderbook-enabled, objective binary markets with clear rules.
- Start one-sided passive, then two-sided passive, then latency overlay on a smaller subset.
- Do not trade sports, politics, geopolitics, augmented neg-risk placeholders, `Other`, taker-only news, or generic narrative probability strategies.

## Setup

```powershell
cp .env.example .env
cp config.yaml.example config.yaml
py -m pip install -e ".[dev,clob]"
```

## CLI

```powershell
python -m src.app fetch-markets --limit 50 --output data/registry/raw_markets.json
python -m src.app build-registry --raw data/registry/raw_markets.json --output data/registry/market_registry_snapshot.json
python -m src.app filter-eligible --snapshot data/registry/market_registry_snapshot.json --output data/registry/eligible_markets_latest.json
python -m src.app emit-run-manifest --metrics data/reports/sample_metrics.json --output data/runtime/run_manifests/sample_run_manifest_v1.json
python -m src.app check-geoblock --output data/runtime/geoblock_check.json
python -m src.app venue-smoke --output data/runtime/venue_smoke.json
python -m src.app run-shadow-a --snapshot data/registry/market_registry_snapshot.json --eligibility data/registry/eligible_markets_latest.json --report-output data/shadow/shadow_a_latest.json
python -m pytest -q
```

## Live Smoke Notes

- `check-geoblock` calls the live Polymarket geoblock endpoint and records the deploy IP returned by the venue.
- `venue-smoke` is guarded by flags so it does not create/rotate API keys or place live orders unless you explicitly opt in.
- For authenticated smoke you need `POLYMARKET_PRIVATE_KEY`; for existing L2 auth you also need `POLYMARKET_API_KEY`, `POLYMARKET_API_SECRET`, and `POLYMARKET_API_PASSPHRASE`.
- If you deliberately want the tool to create or derive L2 credentials from L1 auth, pass `--allow-create-api-key`. Do not do this casually: creating a fresh key can invalidate a currently active one.
- For split/merge smoke you need either relayer credentials from `Settings > API Keys` (`POLYMARKET_RELAYER_API_KEY` + `POLYMARKET_RELAYER_API_KEY_ADDRESS`) or builder credentials if you are in the Builder Program.
- Embedded/Google Polymarket accounts must model two identities explicitly:
  - `POLYMARKET_RELAYER_API_KEY_ADDRESS` and the L1 signer are the owner address.
  - `POLYMARKET_PROXY_ADDRESS` and `POLYMARKET_FUNDER_ADDRESS` are the proxy wallet address used for trading and inventory.
  - `POLYMARKET_SIGNATURE_TYPE=1` for proxy wallets. The lane will fail closed if the explicit proxy address does not match the deterministic Polymarket proxy wallet for the owner.
- `POLYMARKET_RPC_URL` is used to estimate proxy relayer gas before signing. Leave the default unless you run your own Polygon RPC.

## Runtime Layout

- `data/registry/`: raw market pulls, normalized snapshots, eligibility outputs
- `data/marketdata/`: book, trades, history, account/reward recon
- `data/runtime/`: runtime state, arming state, run manifests
- `data/reports/`: daily reports, promotion summaries
- `data/shadow/`: shadow-only fills and replay artifacts
- `data/micro_live/`: micro-live metrics and reconciliations

## Control Plane Contract

- Emit RunManifest v1 with `source_repo="polymarket-bot"` and `market_type="polymarket_binary"`.
- Keep `research-orchestrator` additive-only. No new manifest version.
- Preserve the state ladder `research -> paper/shadow -> ARMED_REAL_MICRO -> REAL_MICRO_ACTIVE -> AUTO_DISARMED/DISARMED`.
