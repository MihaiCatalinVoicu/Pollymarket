# Key Rotation Runbook

## Why This Exists

The current debugging credentials were exposed in screenshots during venue integration. That makes them unsuitable for any serious live capital.

## What The Docs Support

- Polymarket proxy-wallet auth docs and L1 client docs document exporting a private key and creating or deriving L2 API credentials.
- Polymarket relayer docs document creating Relayer API Keys from `Settings > API Keys`.
- I did not find official documentation for rotating an embedded/private key in place. Treat that as an operational inference, not a quoted platform guarantee.

## Safe Rotation Strategy

1. Stop using the exposed wallet for anything beyond debugging.
2. If there are funds left on the exposed wallet, withdraw or move them out first.
3. Create a fresh Polymarket trading identity:
   - either a new embedded/account wallet,
   - or a dedicated external wallet you control.
4. Export the new private key from the new wallet.
5. Create a fresh Relayer API Key from `Settings > API Keys`.
6. Create fresh L2 CLOB credentials for the new signer.

## Required Fresh Secrets

- `POLYMARKET_PRIVATE_KEY`
- `POLYMARKET_API_KEY`
- `POLYMARKET_API_SECRET`
- `POLYMARKET_API_PASSPHRASE`
- `POLYMARKET_RELAYER_API_KEY`
- `POLYMARKET_RELAYER_API_KEY_ADDRESS`
- `POLYMARKET_FUNDER_ADDRESS`
- `POLYMARKET_PROXY_ADDRESS`

## Embedded / Proxy Wallet Mapping

- `POLYMARKET_RELAYER_API_KEY_ADDRESS` = owner / signer address
- `POLYMARKET_FUNDER_ADDRESS` = proxy wallet address
- `POLYMARKET_PROXY_ADDRESS` = proxy wallet address
- `POLYMARKET_SIGNATURE_TYPE=1`

The lane now enforces this identity model and fails closed if the configured proxy does not match the deterministic Polymarket proxy wallet for the owner.

## Refresh `.env`

Update the local `.env` with the fresh values only. Do not commit it.

```env
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_API_KEY=...
POLYMARKET_API_SECRET=...
POLYMARKET_API_PASSPHRASE=...
POLYMARKET_RELAYER_API_KEY=...
POLYMARKET_RELAYER_API_KEY_ADDRESS=0x...
POLYMARKET_FUNDER_ADDRESS=0x...
POLYMARKET_PROXY_ADDRESS=0x...
POLYMARKET_SIGNATURE_TYPE=1
POLYMARKET_RPC_URL=https://polygon-bor-rpc.publicnode.com
```

## Clean Rerun Sequence

Run these commands in order from the repo root:

```powershell
py -m src.app check-geoblock
py -m src.app venue-smoke --allow-live-orders --allow-live-inventory-ops
```

## Expected Pass Criteria

- geoblock returns `blocked=false`
- L1 auth passes
- L2 auth passes
- post-only order is posted and canceled successfully
- approve, split, and merge are mined on the real proxy wallet
- `reconciliation_clean=true`
- no derived/deployed SAFE appears in relayer history

## References

- Authentication / proxy wallet: https://docs.polymarket.com/developers/proxy-wallet
- L1 methods / API key management: https://docs.polymarket.com/trading/clients/l1
- Relayer / gasless transactions: https://docs.polymarket.com/developers/builders/relayer-client
- Relayer transactions API: https://docs.polymarket.com/api-reference/relayer/get-recent-transactions-for-a-user
