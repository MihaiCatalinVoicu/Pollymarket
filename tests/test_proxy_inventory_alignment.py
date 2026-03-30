from __future__ import annotations

import pytest
from eth_account import Account

from src.inventory.proxy_relayer import (
    ProxyRelayerClient,
    ProxyRelayerError,
    ProxyTransaction,
    RelayerApiKeyConfig,
    build_proxy_transaction_request,
    reconcile_proxy_inventory_results,
)
from src.ops.venue_identity import derive_proxy_wallet, resolve_venue_identity


SAMPLE_PRIVATE_KEY = "0x" + ("11" * 32)
OWNER_ADDRESS = Account.from_key(SAMPLE_PRIVATE_KEY).address
PROXY_ADDRESS = derive_proxy_wallet(OWNER_ADDRESS, 137)
RELAY_ADDRESS = "0x" + ("22" * 20)


class FakeHttpClient:
    def __init__(self, identity) -> None:
        self.identity = identity
        self.get_calls: list[tuple[str, dict | None, dict | None]] = []
        self.post_calls: list[tuple[str, dict, dict | None]] = []

    def get(self, path: str, *, params: dict | None = None, headers: dict | None = None):
        self.get_calls.append((path, params, headers))
        if path == "/relay-payload":
            return {"address": RELAY_ADDRESS, "nonce": "7"}
        if path == "/transaction":
            return [
                {
                    "transactionID": "tx-1",
                    "transactionHash": "0x" + ("ab" * 32),
                    "from": self.identity.owner_address,
                    "to": "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052",
                    "proxyAddress": self.identity.proxy_address,
                    "state": "STATE_CONFIRMED",
                    "type": "PROXY",
                }
            ]
        if path == "/transactions":
            return [
                {
                    "type": "PROXY",
                    "owner": self.identity.owner_address,
                    "proxyAddress": self.identity.proxy_address,
                }
            ]
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, *, json_payload: dict, headers: dict | None = None):
        self.post_calls.append((path, json_payload, headers))
        if path != "/submit":
            raise AssertionError(f"unexpected POST {path}")
        return {
            "transactionID": "tx-1",
            "state": "STATE_NEW",
            "transactionHash": "0x" + ("cd" * 32),
        }


def test_embedded_identity_routes_inventory_to_existing_proxy_wallet() -> None:
    identity = resolve_venue_identity(
        owner_address=OWNER_ADDRESS,
        chain_id=137,
        signature_type=1,
        funder_address=PROXY_ADDRESS,
        proxy_address=PROXY_ADDRESS,
        api_key="pm_api_key_example",
        recent_transactions=[
            {
                "type": "PROXY",
                "owner": OWNER_ADDRESS,
                "proxyAddress": PROXY_ADDRESS,
            }
        ],
    )
    fake_http = FakeHttpClient(identity)
    client = ProxyRelayerClient(
        "https://relayer-v2.polymarket.com",
        137,
        private_key=SAMPLE_PRIVATE_KEY,
        auth_config=RelayerApiKeyConfig(api_key="relayer-key-123", address=identity.owner_address),
        http_client=fake_http,
    )

    response = client.execute(
        identity=identity,
        transactions=[ProxyTransaction(to="0x" + ("33" * 20), data="0x1234")],
        metadata="inventory smoke",
    )
    result = response.wait(max_polls=1, poll_interval_seconds=0)

    assert result is not None
    assert fake_http.post_calls
    _, payload, headers = fake_http.post_calls[0]
    assert payload["type"] == "PROXY"
    assert payload["proxyWallet"] == identity.proxy_address
    assert payload["from"] == identity.owner_address
    assert payload["to"] == "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052"
    assert headers["RELAYER_API_KEY_ADDRESS"] == identity.owner_address


def test_inventory_path_fails_closed_when_proxy_identity_mismatches() -> None:
    mismatched_identity = type(
        "Identity",
        (),
        {
            "owner_address": OWNER_ADDRESS,
            "proxy_address": "0x" + ("44" * 20),
            "derived_proxy_address": PROXY_ADDRESS,
        },
    )()

    with pytest.raises(ProxyRelayerError, match="deterministic proxy wallet"):
        build_proxy_transaction_request(
            private_key=SAMPLE_PRIVATE_KEY,
            identity=mismatched_identity,
            relay_address=RELAY_ADDRESS,
            nonce="7",
            transactions=[ProxyTransaction(to="0x" + ("33" * 20), data="0x1234")],
        )


def test_history_proxy_mismatch_blocks_identity_resolution() -> None:
    with pytest.raises(ValueError, match="does not align to a single proxy wallet"):
        resolve_venue_identity(
            owner_address=OWNER_ADDRESS,
            chain_id=137,
            signature_type=1,
            funder_address=PROXY_ADDRESS,
            proxy_address=PROXY_ADDRESS,
            recent_transactions=[
                {
                    "type": "PROXY",
                    "owner": OWNER_ADDRESS,
                    "proxyAddress": "0x" + ("55" * 20),
                }
            ],
        )


def test_reconciliation_marks_wrong_proxy_as_dirty() -> None:
    identity = resolve_venue_identity(
        owner_address=OWNER_ADDRESS,
        chain_id=137,
        signature_type=1,
        funder_address=PROXY_ADDRESS,
        proxy_address=PROXY_ADDRESS,
    )

    snapshot = reconcile_proxy_inventory_results(
        identity,
        split_result={
            "state": "STATE_CONFIRMED",
            "type": "PROXY",
            "proxyAddress": PROXY_ADDRESS,
            "from": OWNER_ADDRESS,
        },
        merge_result={
            "state": "STATE_CONFIRMED",
            "type": "PROXY",
            "proxyAddress": "0x" + ("55" * 20),
            "from": OWNER_ADDRESS,
        },
    )

    assert snapshot["reconciliation_clean"] is False
    assert "merge_wrong_proxy" in snapshot["issues"]
