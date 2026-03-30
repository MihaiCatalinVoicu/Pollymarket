from __future__ import annotations

import json
from dataclasses import dataclass
from time import sleep
from typing import Any

import requests
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak

from src.common.http_client import JsonHttpClient
from src.ops.venue_identity import PROXY_FACTORY_ADDRESS, VenueIdentity, normalize_address


RELAY_HUB_ADDRESS = "0xD216153c06E857cD7f72665E0aF1d7D82172F494"
DEFAULT_PROXY_GAS_LIMIT = 10_000_000
GET_NONCE = "/nonce"
GET_RELAY_PAYLOAD = "/relay-payload"
GET_TRANSACTION = "/transaction"
GET_TRANSACTIONS = "/transactions"
SUBMIT_TRANSACTION = "/submit"
TERMINAL_STATES = {"STATE_MINED", "STATE_CONFIRMED"}
FAILED_STATE = "STATE_FAILED"
CALL_TYPE_CALL = "1"
MAX_UINT256 = (1 << 256) - 1


@dataclass(frozen=True)
class StaticHeaderPayload:
    headers: dict[str, str]

    def to_dict(self) -> dict[str, str]:
        return dict(self.headers)


@dataclass(frozen=True)
class RelayerApiKeyConfig:
    api_key: str
    address: str

    def to_headers(self) -> dict[str, str]:
        return {
            "RELAYER_API_KEY": self.api_key,
            "RELAYER_API_KEY_ADDRESS": normalize_address(self.address),
        }

    def generate_builder_headers(
        self,
        method: str,
        path: str,
        body: str | None = None,
        timestamp: int | None = None,
    ) -> StaticHeaderPayload:
        return StaticHeaderPayload(self.to_headers())


@dataclass(frozen=True)
class ProxyTransaction:
    to: str
    data: str
    value: str = "0"
    type_code: str = CALL_TYPE_CALL


class ProxyRelayerError(RuntimeError):
    pass


class ProxyRelayerTransactionResponse:
    def __init__(self, transaction_id: str, state: str | None, transaction_hash: str | None, client: "ProxyRelayerClient"):
        self.transaction_id = transaction_id
        self.state = state
        self.transaction_hash = transaction_hash
        self.client = client

    def get_transaction(self) -> list[dict[str, Any]]:
        return self.client.get_transaction(self.transaction_id)

    def wait(self, *, max_polls: int = 30, poll_interval_seconds: float = 2.0) -> dict[str, Any] | None:
        return self.client.poll_until_terminal_state(
            self.transaction_id,
            max_polls=max_polls,
            poll_interval_seconds=poll_interval_seconds,
        )


def _bytes_from_hex(value: str) -> bytes:
    normalized = str(value or "").strip()
    if normalized.startswith("0x"):
        normalized = normalized[2:]
    if len(normalized) % 2 != 0:
        normalized = "0" + normalized
    return bytes.fromhex(normalized)


def _uint256(value: str | int) -> bytes:
    return int(value).to_bytes(32, byteorder="big", signed=False)


def encode_proxy_transaction_data(transactions: list[ProxyTransaction]) -> str:
    selector = keccak(text="proxy((uint8,address,uint256,bytes)[])")[:4]
    args = [
        (
            int(tx.type_code),
            normalize_address(tx.to),
            int(tx.value),
            _bytes_from_hex(tx.data),
        )
        for tx in transactions
    ]
    payload = selector + abi_encode(["(uint8,address,uint256,bytes)[]"], [args])
    return "0x" + payload.hex()


def encode_erc20_approve(spender: str, amount: int = MAX_UINT256) -> str:
    selector = keccak(text="approve(address,uint256)")[:4]
    payload = selector + abi_encode(["address", "uint256"], [normalize_address(spender), int(amount)])
    return "0x" + payload.hex()


def create_proxy_struct_hash(
    *,
    owner_address: str,
    to: str,
    data: str,
    nonce: str | int,
    gas_price: str | int,
    gas_limit: str | int,
    relay_hub: str,
    relay_address: str,
    relayer_fee: str | int = 0,
) -> bytes:
    data_to_hash = b"rlx:"
    data_to_hash += _bytes_from_hex(owner_address)
    data_to_hash += _bytes_from_hex(to)
    data_to_hash += _bytes_from_hex(data)
    data_to_hash += _uint256(relayer_fee)
    data_to_hash += _uint256(gas_price)
    data_to_hash += _uint256(gas_limit)
    data_to_hash += _uint256(nonce)
    data_to_hash += _bytes_from_hex(relay_hub)
    data_to_hash += _bytes_from_hex(relay_address)
    return keccak(data_to_hash)


def build_proxy_transaction_request(
    *,
    private_key: str,
    identity: VenueIdentity,
    relay_address: str,
    nonce: str | int,
    transactions: list[ProxyTransaction],
    proxy_data: str | None = None,
    metadata: str | None = None,
    gas_price: str = "0",
    gas_limit: str = str(DEFAULT_PROXY_GAS_LIMIT),
    relayer_fee: str = "0",
) -> dict[str, Any]:
    if not identity.proxy_address:
        raise ProxyRelayerError("proxy wallet identity is required for PROXY relayer transactions")
    if identity.derived_proxy_address and identity.proxy_address.lower() != identity.derived_proxy_address.lower():
        raise ProxyRelayerError("explicit proxy wallet does not match the deterministic proxy wallet")

    proxy_data = proxy_data or encode_proxy_transaction_data(transactions)
    struct_hash = create_proxy_struct_hash(
        owner_address=identity.owner_address,
        to=PROXY_FACTORY_ADDRESS,
        data=proxy_data,
        nonce=nonce,
        gas_price=gas_price,
        gas_limit=gas_limit,
        relay_hub=RELAY_HUB_ADDRESS,
        relay_address=relay_address,
        relayer_fee=relayer_fee,
    )
    signature = Account.sign_message(encode_defunct(struct_hash), private_key).signature.hex()
    return {
        "from": identity.owner_address,
        "to": PROXY_FACTORY_ADDRESS,
        "proxyWallet": identity.proxy_address,
        "data": proxy_data,
        "nonce": str(nonce),
        "signature": "0x" + signature,
        "signatureParams": {
            "gasPrice": gas_price,
            "gasLimit": gas_limit,
            "relayerFee": relayer_fee,
            "relayHub": RELAY_HUB_ADDRESS,
            "relay": normalize_address(relay_address),
        },
        "type": "PROXY",
        "metadata": metadata or "",
    }


def reconcile_proxy_inventory_results(
    identity: VenueIdentity,
    *,
    split_result: dict[str, Any] | None,
    merge_result: dict[str, Any] | None,
) -> dict[str, Any]:
    issues: list[str] = []
    for label, result in (("split", split_result), ("merge", merge_result)):
        if not result:
            issues.append(f"{label}_missing")
            continue
        if str(result.get("type") or "").upper() != "PROXY":
            issues.append(f"{label}_not_proxy")
        result_proxy = str(result.get("proxyAddress") or "")
        if result_proxy.lower() != str(identity.proxy_address or "").lower():
            issues.append(f"{label}_wrong_proxy")
        result_owner = str(result.get("from") or "")
        if result_owner.lower() != identity.owner_address.lower():
            issues.append(f"{label}_wrong_owner")
        if str(result.get("state") or "") not in TERMINAL_STATES:
            issues.append(f"{label}_not_confirmed")
    return {
        "reconciliation_clean": not issues,
        "issues": issues,
    }


class ProxyRelayerClient:
    def __init__(
        self,
        relayer_url: str,
        chain_id: int,
        *,
        private_key: str,
        auth_config: Any,
        http_client: JsonHttpClient | None = None,
        default_gas_limit: int = DEFAULT_PROXY_GAS_LIMIT,
        rpc_url: str | None = None,
    ) -> None:
        if chain_id != 137:
            raise ProxyRelayerError("proxy relayer flow is only configured for Polygon mainnet in this lane")
        self.relayer_url = relayer_url.rstrip("/")
        self.chain_id = chain_id
        self.private_key = private_key
        self.auth_config = auth_config
        self.http = http_client or JsonHttpClient(self.relayer_url)
        self.default_gas_limit = default_gas_limit
        self.rpc_url = rpc_url

    def get_relay_payload(self, owner_address: str) -> dict[str, Any]:
        return self.http.get(
            GET_RELAY_PAYLOAD,
            params={"address": normalize_address(owner_address), "type": "PROXY"},
        )

    def get_transaction(self, transaction_id: str) -> list[dict[str, Any]]:
        payload = self.http.get(GET_TRANSACTION, params={"id": transaction_id})
        return payload if isinstance(payload, list) else []

    def get_transactions(self) -> list[dict[str, Any]]:
        payload = self.http.get(GET_TRANSACTIONS, headers=self._headers("GET", GET_TRANSACTIONS))
        return payload if isinstance(payload, list) else []

    def poll_until_terminal_state(
        self,
        transaction_id: str,
        *,
        max_polls: int = 30,
        poll_interval_seconds: float = 2.0,
    ) -> dict[str, Any] | None:
        for _ in range(max_polls):
            transactions = self.get_transaction(transaction_id)
            if transactions:
                txn = transactions[0]
                state = str(txn.get("state") or "")
                if state in TERMINAL_STATES:
                    return txn
                if state == FAILED_STATE:
                    return None
            sleep(poll_interval_seconds)
        return None

    def execute(
        self,
        *,
        identity: VenueIdentity,
        transactions: list[ProxyTransaction],
        metadata: str | None = None,
    ) -> ProxyRelayerTransactionResponse:
        if not identity.proxy_address:
            raise ProxyRelayerError("proxy relayer execution requires an explicit proxy wallet identity")
        relay_payload = self.get_relay_payload(identity.owner_address)
        relay_address = relay_payload.get("address")
        nonce = relay_payload.get("nonce")
        if not relay_address or nonce is None:
            raise ProxyRelayerError("relayer did not return a valid relay payload for the owner address")
        proxy_data = encode_proxy_transaction_data(transactions)
        gas_limit = str(self.estimate_proxy_gas(identity.owner_address, proxy_data))
        request = build_proxy_transaction_request(
            private_key=self.private_key,
            identity=identity,
            relay_address=relay_address,
            nonce=nonce,
            transactions=transactions,
            proxy_data=proxy_data,
            metadata=metadata,
            gas_limit=gas_limit,
        )
        response = self.http.post(SUBMIT_TRANSACTION, json_payload=request, headers=self._headers("POST", SUBMIT_TRANSACTION, request))
        transaction_id = response.get("transactionID")
        if not transaction_id:
            raise ProxyRelayerError("relayer did not return a transactionID")
        return ProxyRelayerTransactionResponse(
            transaction_id=transaction_id,
            state=response.get("state"),
            transaction_hash=response.get("transactionHash"),
            client=self,
        )

    def _headers(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, str]:
        if hasattr(self.auth_config, "generate_builder_headers"):
            serialized_body = json.dumps(body, separators=(",", ":"), ensure_ascii=True) if body is not None else None
            payload = self.auth_config.generate_builder_headers(method, path, serialized_body)
            if payload is not None and hasattr(payload, "to_dict"):
                return payload.to_dict()
        if hasattr(self.auth_config, "to_headers"):
            return self.auth_config.to_headers()
        raise ProxyRelayerError("relayer auth config cannot generate request headers")

    def estimate_proxy_gas(self, owner_address: str, proxy_data: str) -> int:
        if not self.rpc_url:
            return self.default_gas_limit
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_estimateGas",
            "params": [
                {
                    "from": normalize_address(owner_address),
                    "to": PROXY_FACTORY_ADDRESS,
                    "data": proxy_data,
                }
            ],
        }
        try:
            response = requests.post(self.rpc_url, json=payload, timeout=30)
            response.raise_for_status()
            body = response.json()
            result = body.get("result")
            if result is None:
                return self.default_gas_limit
            return int(str(result), 16)
        except Exception:
            return self.default_gas_limit
