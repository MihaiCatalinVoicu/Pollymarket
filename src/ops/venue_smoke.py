from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any

from src.config import Settings
from src.inventory.proxy_relayer import (
    ProxyRelayerClient,
    ProxyTransaction,
    RelayerApiKeyConfig,
    encode_erc20_approve,
    reconcile_proxy_inventory_results,
)
from src.ops.venue_identity import VenueIdentity, resolve_venue_identity

try:
    from eth_abi import encode as abi_encode
    from eth_utils import keccak
    from py_builder_signing_sdk.config import BuilderConfig
    from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import (
        ApiCreds,
        BalanceAllowanceParams,
        OrderArgs,
        OrderType,
        PartialCreateOrderOptions,
    )
except ImportError:
    abi_encode = None
    keccak = None
    BuilderConfig = None
    BuilderApiKeyCreds = None
    ClobClient = None
    ApiCreds = None
    BalanceAllowanceParams = None
    OrderArgs = None
    OrderType = None
    PartialCreateOrderOptions = None


CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDCE_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
ZERO_BYTES32 = "0x" + ("00" * 32)


@dataclass
class VenueSmokeConfig:
    private_key: str | None
    api_key: str | None
    api_secret: str | None
    api_passphrase: str | None
    funder: str | None
    proxy_address: str | None
    signature_type: int
    token_id: str | None
    condition_id: str | None
    order_size: float
    split_amount_usdce: float
    rpc_url: str | None
    relayer_url: str
    relayer_api_key: str | None
    relayer_api_key_address: str | None
    builder_api_key: str | None
    builder_secret: str | None
    builder_passphrase: str | None

    @classmethod
    def from_env(cls) -> "VenueSmokeConfig":
        return cls(
            private_key=os.getenv("POLYMARKET_PRIVATE_KEY"),
            api_key=os.getenv("POLYMARKET_API_KEY"),
            api_secret=os.getenv("POLYMARKET_API_SECRET"),
            api_passphrase=os.getenv("POLYMARKET_API_PASSPHRASE"),
            funder=os.getenv("POLYMARKET_FUNDER_ADDRESS"),
            proxy_address=os.getenv("POLYMARKET_PROXY_ADDRESS"),
            signature_type=int(os.getenv("POLYMARKET_SIGNATURE_TYPE", "0")),
            token_id=os.getenv("POLYMARKET_SMOKE_TOKEN_ID"),
            condition_id=os.getenv("POLYMARKET_SMOKE_CONDITION_ID"),
            order_size=float(os.getenv("POLYMARKET_SMOKE_ORDER_SIZE", "1")),
            split_amount_usdce=float(os.getenv("POLYMARKET_SMOKE_SPLIT_USDCE", "1")),
            rpc_url=os.getenv("POLYMARKET_RPC_URL", "https://polygon-bor-rpc.publicnode.com"),
            relayer_url=os.getenv("POLYMARKET_RELAYER_URL", "https://relayer-v2.polymarket.com"),
            relayer_api_key=os.getenv("POLYMARKET_RELAYER_API_KEY"),
            relayer_api_key_address=os.getenv("POLYMARKET_RELAYER_API_KEY_ADDRESS"),
            builder_api_key=os.getenv("POLYMARKET_BUILDER_API_KEY"),
            builder_secret=os.getenv("POLYMARKET_BUILDER_SECRET"),
            builder_passphrase=os.getenv("POLYMARKET_BUILDER_PASSPHRASE"),
        )


@dataclass
class SmokeStage:
    ok: bool | None = None
    details: dict[str, Any] = field(default_factory=dict)
    blocked_reason: str | None = None


@dataclass
class VenueSmokeReport:
    checked_at: str
    public: SmokeStage = field(default_factory=SmokeStage)
    l1_auth: SmokeStage = field(default_factory=SmokeStage)
    l2_auth: SmokeStage = field(default_factory=SmokeStage)
    post_only_order: SmokeStage = field(default_factory=SmokeStage)
    split_merge: SmokeStage = field(default_factory=SmokeStage)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(
            stage.ok is not False
            for stage in (self.public, self.l1_auth, self.l2_auth, self.post_only_order, self.split_merge)
        )


def _require_optional_deps() -> None:
    if ClobClient is None or ApiCreds is None or OrderArgs is None or PartialCreateOrderOptions is None:
        raise RuntimeError('Install optional smoke dependencies with `py -m pip install -e ".[clob]"`.')


def _normalize_bytes32(value: str) -> bytes:
    normalized = value.lower()
    if normalized.startswith("0x"):
        normalized = normalized[2:]
    if len(normalized) != 64:
        raise ValueError("condition_id must be a 32-byte hex string")
    return bytes.fromhex(normalized)


def _round_down_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    steps = (value / tick).to_integral_value(rounding=ROUND_FLOOR)
    return steps * tick


def derive_passive_buy_price(best_bid: str | None, best_ask: str | None, tick_size: str, midpoint: str | None = None) -> Decimal:
    tick = Decimal(tick_size)
    bid = Decimal(best_bid) if best_bid is not None else None
    ask = Decimal(best_ask) if best_ask is not None else None
    mid = Decimal(midpoint) if midpoint is not None else None

    if bid is not None:
        candidate = bid
    elif ask is not None:
        candidate = ask - tick
    elif mid is not None:
        candidate = mid - tick
    else:
        candidate = Decimal("0.50") - tick

    if ask is not None and candidate >= ask:
        candidate = ask - tick

    candidate = min(candidate, Decimal("0.99"))
    candidate = max(candidate, tick)
    rounded = _round_down_to_tick(candidate, tick)
    if rounded < tick:
        rounded = tick
    return rounded


def encode_ctf_call(function_signature: str, condition_id: str, amount_base_units: int | None = None) -> str:
    if abi_encode is None or keccak is None:
        raise RuntimeError('Install optional smoke dependencies with `py -m pip install -e ".[clob]"`.')

    function_map = {
        "splitPosition(address,bytes32,bytes32,uint256[],uint256)": (
            ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
            [USDCE_ADDRESS, _normalize_bytes32(ZERO_BYTES32), _normalize_bytes32(condition_id), [1, 2], int(amount_base_units or 0)],
        ),
        "mergePositions(address,bytes32,bytes32,uint256[],uint256)": (
            ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
            [USDCE_ADDRESS, _normalize_bytes32(ZERO_BYTES32), _normalize_bytes32(condition_id), [1, 2], int(amount_base_units or 0)],
        ),
    }
    if function_signature not in function_map:
        raise ValueError(f"unsupported function signature: {function_signature}")

    arg_types, args = function_map[function_signature]
    selector = keccak(text=function_signature)[:4]
    payload = selector + abi_encode(arg_types, args)
    return "0x" + payload.hex()


def _extract_best_prices(order_book: Any) -> tuple[str | None, str | None]:
    bids = getattr(order_book, "bids", None) or []
    asks = getattr(order_book, "asks", None) or []
    best_bid = bids[0].price if bids else None
    best_ask = asks[0].price if asks else None
    return best_bid, best_ask


def _build_api_creds(config: VenueSmokeConfig) -> Any:
    if config.api_key and config.api_secret and config.api_passphrase:
        return ApiCreds(
            api_key=config.api_key,
            api_secret=config.api_secret,
            api_passphrase=config.api_passphrase,
        )
    return None


def _build_builder_config(config: VenueSmokeConfig):
    if not (config.builder_api_key and config.builder_secret and config.builder_passphrase):
        return None
    return BuilderConfig(
        local_builder_creds=BuilderApiKeyCreds(
            key=config.builder_api_key,
            secret=config.builder_secret,
            passphrase=config.builder_passphrase,
        )
    )


def _build_relayer_auth_config(config: VenueSmokeConfig):
    if config.relayer_api_key and config.relayer_api_key_address:
        return RelayerApiKeyConfig(
            api_key=config.relayer_api_key,
            address=config.relayer_api_key_address,
        )
    return _build_builder_config(config)


def _identity_details(identity: VenueIdentity) -> dict[str, Any]:
    return identity.to_dict()


def _allowance_balance_base_units(allowance_payload: Any) -> int | None:
    if not isinstance(allowance_payload, dict):
        return None
    raw_balance = allowance_payload.get("balance")
    try:
        return int(raw_balance)
    except (TypeError, ValueError):
        return None


def run_venue_smoke(
    settings: Settings,
    *,
    config: VenueSmokeConfig | None = None,
    allow_create_api_key: bool = False,
    allow_live_orders: bool = False,
    allow_live_inventory_ops: bool = False,
) -> VenueSmokeReport:
    _require_optional_deps()
    cfg = config or VenueSmokeConfig.from_env()
    report = VenueSmokeReport(checked_at=datetime.now(timezone.utc).isoformat())

    public_client = ClobClient(settings.clob_api_url, settings.chain_id)
    report.public.details["health"] = public_client.get_ok()

    if cfg.token_id:
        order_book = public_client.get_order_book(cfg.token_id)
        tick_size = public_client.get_tick_size(cfg.token_id)
        best_bid, best_ask = _extract_best_prices(order_book)
        midpoint_raw = public_client.get_midpoint(cfg.token_id)
        midpoint = midpoint_raw.get("mid") if isinstance(midpoint_raw, dict) else None
        fee_rate_bps = public_client.get_fee_rate_bps(cfg.token_id)
        report.public.details.update(
            {
                "token_id": cfg.token_id,
                "tick_size": tick_size,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "midpoint": midpoint,
                "fee_rate_bps": fee_rate_bps,
            }
        )
    report.public.ok = True

    if not cfg.private_key:
        report.l1_auth.ok = False
        report.l1_auth.blocked_reason = "POLYMARKET_PRIVATE_KEY is not set"
        report.notes.append("L1/L2 auth, order smoke, and split/merge were skipped because no private key is configured.")
        return report

    l1_client = ClobClient(settings.clob_api_url, settings.chain_id, key=cfg.private_key)
    wallet_address = l1_client.get_address()
    report.l1_auth.ok = True
    report.l1_auth.details["wallet_address"] = wallet_address

    relayer_auth_config = _build_relayer_auth_config(cfg)
    recent_relayer_transactions: list[dict[str, Any]] | None = None
    if relayer_auth_config is not None:
        try:
            recent_relayer_transactions = ProxyRelayerClient(
                cfg.relayer_url,
                settings.chain_id,
                private_key=cfg.private_key,
                auth_config=relayer_auth_config,
                rpc_url=cfg.rpc_url,
            ).get_transactions()
        except Exception as exc:
            report.notes.append(f"Recent relayer transactions could not be fetched: {exc}")

    try:
        identity = resolve_venue_identity(
            owner_address=wallet_address,
            chain_id=settings.chain_id,
            signature_type=cfg.signature_type,
            funder_address=cfg.funder,
            proxy_address=cfg.proxy_address,
            api_key=cfg.api_key,
            recent_transactions=recent_relayer_transactions,
        )
    except Exception as exc:
        report.l2_auth.ok = False
        report.l2_auth.blocked_reason = "venue identity resolution failed"
        report.l2_auth.details["error"] = str(exc)
        return report

    report.l1_auth.details["identity"] = _identity_details(identity)

    creds = _build_api_creds(cfg)
    if creds is None:
        try:
            creds = l1_client.derive_api_key()
            report.notes.append("Derived existing L2 credentials from L1 auth.")
        except Exception as exc:
            if allow_create_api_key:
                creds = l1_client.create_or_derive_api_creds()
                report.notes.append("Created or derived L2 credentials because --allow-create-api-key was enabled.")
            else:
                report.l2_auth.ok = False
                report.l2_auth.blocked_reason = (
                    "No L2 creds were provided and derive failed. "
                    "Set POLYMARKET_API_KEY/SECRET/PASSPHRASE or rerun with --allow-create-api-key."
                )
                report.l2_auth.details["error"] = str(exc)
                return report

    funder = identity.funder_address or wallet_address
    l2_client = ClobClient(
        settings.clob_api_url,
        settings.chain_id,
        key=cfg.private_key,
        creds=creds,
        signature_type=cfg.signature_type,
        funder=funder,
    )
    report.l2_auth.details.update(
        {
            "wallet_address": wallet_address,
            "funder": funder,
            "signature_type": cfg.signature_type,
            "proxy_address": identity.proxy_address,
        }
    )
    try:
        allowance = l2_client.get_balance_allowance(
            BalanceAllowanceParams(asset_type="COLLATERAL", signature_type=cfg.signature_type)
        )
        report.l2_auth.details["collateral_allowance"] = allowance
    except Exception as exc:
        report.l2_auth.ok = False
        report.l2_auth.blocked_reason = "L2 auth failed while reading balance allowance"
        report.l2_auth.details["error"] = str(exc)
        return report
    report.l2_auth.ok = True

    if allow_live_orders:
        if not cfg.token_id:
            report.post_only_order.ok = False
            report.post_only_order.blocked_reason = "POLYMARKET_SMOKE_TOKEN_ID is required for live order smoke"
        else:
            order_book = public_client.get_order_book(cfg.token_id)
            tick_size = public_client.get_tick_size(cfg.token_id)
            best_bid, best_ask = _extract_best_prices(order_book)
            midpoint_raw = public_client.get_midpoint(cfg.token_id)
            midpoint = midpoint_raw.get("mid") if isinstance(midpoint_raw, dict) else None
            price = derive_passive_buy_price(best_bid, best_ask, tick_size, midpoint)
            fee_rate_bps = int(public_client.get_fee_rate_bps(cfg.token_id))
            order_args = OrderArgs(
                token_id=cfg.token_id,
                price=float(price),
                size=cfg.order_size,
                side="BUY",
                fee_rate_bps=fee_rate_bps,
            )
            created = l2_client.create_order(
                order_args,
                PartialCreateOrderOptions(tick_size=tick_size, neg_risk=bool(getattr(order_book, "neg_risk", False))),
            )
            posted = l2_client.post_order(created, orderType=OrderType.GTC, post_only=True)
            order_id = (
                posted.get("orderID")
                or posted.get("id")
                or posted.get("orderId")
                or (posted.get("order") or {}).get("id")
            )
            report.post_only_order.details.update(
                {
                    "price": str(price),
                    "size": cfg.order_size,
                    "response": posted,
                }
            )
            if not order_id:
                report.post_only_order.ok = False
                report.post_only_order.blocked_reason = "Order was posted but no order id was returned"
            else:
                cancel_response = l2_client.cancel(order_id)
                report.post_only_order.ok = True
                report.post_only_order.details["order_id"] = order_id
                report.post_only_order.details["cancel_response"] = cancel_response
    else:
        report.post_only_order.blocked_reason = "Live order smoke skipped; rerun with --allow-live-orders to post and cancel a passive order."

    if allow_live_inventory_ops:
        if not cfg.condition_id:
            report.split_merge.ok = False
            report.split_merge.blocked_reason = "POLYMARKET_SMOKE_CONDITION_ID is required for split/merge smoke"
        elif cfg.relayer_api_key_address and cfg.relayer_api_key_address.lower() != identity.owner_address.lower():
            report.split_merge.ok = False
            report.split_merge.blocked_reason = "POLYMARKET_RELAYER_API_KEY_ADDRESS must equal the owner/signer address"
        elif relayer_auth_config is None:
            report.split_merge.ok = False
            report.split_merge.blocked_reason = (
                "Relayer credentials are missing. "
                "Set POLYMARKET_RELAYER_API_KEY and POLYMARKET_RELAYER_API_KEY_ADDRESS, "
                "or provide Builder credentials if you are using the Builder Program."
            )
        elif not identity.uses_proxy_wallet:
            report.split_merge.ok = False
            report.split_merge.blocked_reason = "proxy inventory path requires an explicit proxy wallet identity"
        else:
            try:
                amount_base_units = int(Decimal(str(cfg.split_amount_usdce)) * Decimal("1000000"))
                relay = ProxyRelayerClient(
                    cfg.relayer_url,
                    settings.chain_id,
                    private_key=cfg.private_key,
                    auth_config=relayer_auth_config,
                    rpc_url=cfg.rpc_url,
                )
                pre_allowance = l2_client.get_balance_allowance(
                    BalanceAllowanceParams(asset_type="COLLATERAL", signature_type=cfg.signature_type)
                )
                approve_response = relay.execute(
                    identity=identity,
                    transactions=[
                        ProxyTransaction(
                            to=USDCE_ADDRESS,
                            data=encode_erc20_approve(CTF_ADDRESS),
                        )
                    ],
                    metadata="Polymarket MM V1 smoke approve USDC.e for CTF",
                )
                approve_result = approve_response.wait()
                split_response = relay.execute(
                    identity=identity,
                    transactions=[
                        ProxyTransaction(
                            to=CTF_ADDRESS,
                            data=encode_ctf_call(
                                "splitPosition(address,bytes32,bytes32,uint256[],uint256)",
                                cfg.condition_id,
                                amount_base_units,
                            ),
                        )
                    ],
                    metadata="Polymarket MM V1 smoke split",
                )
                split_result = split_response.wait()
                merge_response = relay.execute(
                    identity=identity,
                    transactions=[
                        ProxyTransaction(
                            to=CTF_ADDRESS,
                            data=encode_ctf_call(
                                "mergePositions(address,bytes32,bytes32,uint256[],uint256)",
                                cfg.condition_id,
                                amount_base_units,
                            ),
                        )
                    ],
                    metadata="Polymarket MM V1 smoke merge",
                )
                merge_result = merge_response.wait()
                reconciliation = reconcile_proxy_inventory_results(
                    identity,
                    split_result=split_result,
                    merge_result=merge_result,
                )
                post_allowance = l2_client.get_balance_allowance(
                    BalanceAllowanceParams(asset_type="COLLATERAL", signature_type=cfg.signature_type)
                )
                pre_balance = _allowance_balance_base_units(pre_allowance)
                post_balance = _allowance_balance_base_units(post_allowance)
                balance_roundtrip_clean = True
                if pre_balance is not None and post_balance is not None:
                    balance_roundtrip_clean = abs(post_balance - pre_balance) <= amount_base_units
                reconciliation_clean = bool(approve_result) and reconciliation["reconciliation_clean"] and balance_roundtrip_clean
                report.split_merge.ok = bool(split_result) and bool(merge_result) and reconciliation_clean
                report.split_merge.details.update(
                    {
                        "identity": _identity_details(identity),
                        "amount_base_units": amount_base_units,
                        "approve_transaction_id": approve_response.transaction_id,
                        "approve_transaction_hash": approve_response.transaction_hash,
                        "approve_result": approve_result,
                        "split_transaction_id": split_response.transaction_id,
                        "split_transaction_hash": split_response.transaction_hash,
                        "split_result": split_result,
                        "merge_transaction_id": merge_response.transaction_id,
                        "merge_transaction_hash": merge_response.transaction_hash,
                        "merge_result": merge_result,
                        "pre_allowance": pre_allowance,
                        "post_allowance": post_allowance,
                        "reconciliation_clean": reconciliation_clean,
                        "reconciliation_issues": reconciliation["issues"],
                        "balance_roundtrip_clean": balance_roundtrip_clean,
                    }
                )
            except Exception as exc:
                report.split_merge.ok = False
                report.split_merge.details.update(
                    {
                        "identity": _identity_details(identity),
                        "error": str(exc),
                    }
                )
    else:
        report.split_merge.blocked_reason = "Live inventory smoke skipped; rerun with --allow-live-inventory-ops after relayer creds are configured."

    return report


def write_venue_smoke_report(path: str | Path, report: VenueSmokeReport) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    return output
