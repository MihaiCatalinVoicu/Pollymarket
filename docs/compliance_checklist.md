# Compliance Checklist

## Preflight

- Confirm deploy IP passes Polymarket geoblock checks.
- Confirm operator jurisdiction is permitted for live order placement.
- Confirm wallet signer, funder, and API credentials are dedicated to this lane.
- Confirm the lane runs from isolated infra and does not share secrets with other bots.

## Before Trading

- Run public market-data smoke checks.
- Run authenticated order create and cancel on a tiny size.
- Run small split and merge cycle.
- Confirm heartbeat behavior and cancel-all fallback.
- Confirm incident runbook and cooldown handling.

## Promotion Gate

- No live trading if geoblock or auth status is unclear.
- No live trading without manual review of initial eligible markets.
- No auto-promotion from shadow to micro-live without explicit evidence review.

