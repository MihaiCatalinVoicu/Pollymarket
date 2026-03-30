# STRATEGY_POLY_MM_V1

## Thesis

`polymarket_mm_v1` is not a generic prediction bot. It is a narrow maker lane for binary objective markets where microstructure, inventory handling, settlement mechanics, and reward-aware quoting are the primary edge sources.

## Core Edge

`expected_edge = spread_capture - adverse_selection - resolution_risk + rewards + rebates - ops_failures`

The strategy is valid only if the base engine still makes operational sense when rewards are materially reduced.

## In Scope

- Fee-enabled binary markets
- `enableOrderBook = true`
- Objective categories: crypto, finance, tech, economics
- Passive `GTC` and `GTD` quoting
- Explicit split, merge, and redeem inventory workflows
- Full-set parity monitoring and inventory recycle

## Out Of Scope

- Sports
- Politics and geopolitics
- Augmented neg-risk placeholders
- `Other` outcomes
- Taker-only news sniping
- Generic “AI fair value for every market”

## Rollout

1. Research and market registry freeze
2. Data capture and shadow replay
3. One-sided micro-live
4. Two-sided micro-live
5. Latency overlay on a smaller subset

