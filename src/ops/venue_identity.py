from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eth_utils import keccak, to_checksum_address


PROXY_FACTORY_BY_CHAIN: dict[int, str] = {
    137: "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052",
}
PROXY_FACTORY_ADDRESS = PROXY_FACTORY_BY_CHAIN[137]

PROXY_INIT_CODE_HASH_BY_CHAIN: dict[int, str] = {
    137: "0xd21df8dc65880a8606f09fe0ce3df9b8869287ab0b058be05aa9e8af6330a00b",
}


def normalize_address(value: str | None) -> str | None:
    if value in ("", None):
        return None
    return to_checksum_address(str(value).strip())


def derive_proxy_wallet(owner_address: str, chain_id: int) -> str:
    factory = PROXY_FACTORY_BY_CHAIN.get(chain_id)
    init_code_hash = PROXY_INIT_CODE_HASH_BY_CHAIN.get(chain_id)
    if not factory or not init_code_hash:
        raise ValueError(f"unsupported proxy derivation chain_id: {chain_id}")
    owner_bytes = bytes.fromhex(normalize_address(owner_address)[2:])
    factory_bytes = bytes.fromhex(factory[2:])
    salt = keccak(owner_bytes)
    payload = b"\xff" + factory_bytes + salt + bytes.fromhex(init_code_hash[2:])
    return to_checksum_address(keccak(payload)[12:])


def fingerprint(value: str | None) -> str | None:
    if value in ("", None):
        return None
    raw = str(value)
    if len(raw) <= 10:
        return raw
    return f"{raw[:6]}...{raw[-4:]}"


@dataclass(frozen=True)
class VenueIdentity:
    owner_address: str
    proxy_address: str | None
    signer_kind: str
    inventory_wallet_type: str
    chain_id: int
    signature_type: int
    funder_address: str | None
    api_key_fingerprint: str | None = None
    proxy_source: str | None = None

    @property
    def uses_proxy_wallet(self) -> bool:
        return self.inventory_wallet_type == "proxy" and self.proxy_address is not None

    @property
    def derived_proxy_address(self) -> str | None:
        if not self.uses_proxy_wallet:
            return None
        return derive_proxy_wallet(self.owner_address, self.chain_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_address": self.owner_address,
            "proxy_address": self.proxy_address,
            "derived_proxy_address": self.derived_proxy_address,
            "signer_kind": self.signer_kind,
            "inventory_wallet_type": self.inventory_wallet_type,
            "chain_id": self.chain_id,
            "signature_type": self.signature_type,
            "funder_address": self.funder_address,
            "api_key_fingerprint": self.api_key_fingerprint,
            "proxy_source": self.proxy_source,
        }


def _proxy_addresses_from_history(owner_address: str, recent_transactions: list[dict[str, Any]] | None) -> set[str]:
    owner = normalize_address(owner_address)
    proxies: set[str] = set()
    for item in recent_transactions or []:
        tx_type = str(item.get("type") or "").upper()
        proxy_address = normalize_address(item.get("proxyAddress"))
        tx_owner = normalize_address(item.get("owner") or item.get("from"))
        if tx_type != "PROXY" or not proxy_address or tx_owner != owner:
            continue
        proxies.add(proxy_address)
    return proxies


def resolve_venue_identity(
    *,
    owner_address: str,
    chain_id: int,
    signature_type: int,
    funder_address: str | None = None,
    proxy_address: str | None = None,
    api_key: str | None = None,
    recent_transactions: list[dict[str, Any]] | None = None,
) -> VenueIdentity:
    owner = normalize_address(owner_address)
    funder = normalize_address(funder_address)
    explicit_proxy = normalize_address(proxy_address) or funder
    expected_proxy = derive_proxy_wallet(owner, chain_id)
    historical_proxies = _proxy_addresses_from_history(owner, recent_transactions)

    if explicit_proxy and explicit_proxy != expected_proxy:
        raise ValueError(
            f"configured proxy {explicit_proxy} does not match deterministic Polymarket proxy {expected_proxy}"
        )

    if historical_proxies and historical_proxies != {expected_proxy}:
        mismatch = ", ".join(sorted(historical_proxies))
        raise ValueError(
            f"relayer transaction history for owner {owner} does not align to a single proxy wallet: {mismatch}"
        )

    if signature_type == 0 and funder in (None, owner) and not historical_proxies:
        return VenueIdentity(
            owner_address=owner,
            proxy_address=None,
            signer_kind="eoa",
            inventory_wallet_type="eoa",
            chain_id=chain_id,
            signature_type=signature_type,
            funder_address=funder,
            api_key_fingerprint=fingerprint(api_key),
            proxy_source=None,
        )

    if explicit_proxy:
        proxy = explicit_proxy
        proxy_source = "configured_proxy"
    elif historical_proxies:
        proxy = next(iter(historical_proxies))
        proxy_source = "relayer_history"
    else:
        raise ValueError(
            "proxy wallet is required for proxy inventory operations; set POLYMARKET_PROXY_ADDRESS or POLYMARKET_FUNDER_ADDRESS"
        )

    return VenueIdentity(
        owner_address=owner,
        proxy_address=proxy,
        signer_kind="embedded_proxy" if signature_type != 0 else "proxy",
        inventory_wallet_type="proxy",
        chain_id=chain_id,
        signature_type=signature_type,
        funder_address=funder,
        api_key_fingerprint=fingerprint(api_key),
        proxy_source=proxy_source,
    )
