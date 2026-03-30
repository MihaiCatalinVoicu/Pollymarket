from decimal import Decimal

from src.ops.geoblock import GeoblockStatus
from src.ops.venue_smoke import RelayerApiKeyConfig, encode_ctf_call, derive_passive_buy_price


def test_geoblock_status_ok_flag_is_inverse_of_blocked() -> None:
    status = GeoblockStatus(
        blocked=False,
        ip="178.132.109.120",
        country="RO",
        region="B",
        checked_at="2026-03-30T00:00:00+00:00",
        raw={"blocked": False},
    )
    assert status.geoblock_ok is True


def test_derive_passive_buy_price_stays_inside_book() -> None:
    price = derive_passive_buy_price(best_bid="0.44", best_ask="0.46", tick_size="0.01", midpoint="0.45")
    assert price == Decimal("0.44")


def test_derive_passive_buy_price_uses_tick_floor_when_book_missing() -> None:
    price = derive_passive_buy_price(best_bid=None, best_ask=None, tick_size="0.01", midpoint=None)
    assert price == Decimal("0.49")


def test_encode_ctf_call_prefixes_split_selector() -> None:
    payload = encode_ctf_call(
        "splitPosition(address,bytes32,bytes32,uint256[],uint256)",
        "0x" + ("11" * 32),
        1_000_000,
    )
    assert payload.startswith("0x")
    assert len(payload) > 10


def test_relayer_api_key_config_emits_expected_headers() -> None:
    cfg = RelayerApiKeyConfig(api_key="key123", address="0x" + ("1" * 40))
    headers = cfg.generate_builder_headers("GET", "/transactions").to_dict()
    assert headers["RELAYER_API_KEY"] == "key123"
    assert headers["RELAYER_API_KEY_ADDRESS"].lower() == ("0x" + ("1" * 40)).lower()
