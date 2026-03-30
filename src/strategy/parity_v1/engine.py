from __future__ import annotations

from pydantic import BaseModel, Field


class ParityInputs(BaseModel):
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    fee_rate: float = 0.0
    paired_inventory: float = 0.0
    book_unwind_value: float | None = None


class ParitySignal(BaseModel):
    full_set_buy_edge: float
    full_set_sell_edge: float
    merge_value: float
    should_buy_full_set: bool
    should_sell_full_set: bool
    should_merge_inventory: bool
    notes: list[str] = Field(default_factory=list)


def compute_parity(inputs: ParityInputs) -> ParitySignal:
    fee_adjustment = inputs.fee_rate * ((inputs.yes_ask * (1.0 - inputs.yes_ask)) + (inputs.no_ask * (1.0 - inputs.no_ask)))
    full_set_buy_cost = inputs.yes_ask + inputs.no_ask + fee_adjustment
    full_set_sell_value = inputs.yes_bid + inputs.no_bid - fee_adjustment
    buy_edge = 1.0 - full_set_buy_cost
    sell_edge = full_set_sell_value - 1.0
    unwind_value = inputs.book_unwind_value if inputs.book_unwind_value is not None else full_set_sell_value
    merge_value = inputs.paired_inventory * max(0.0, 1.0 - unwind_value)
    notes: list[str] = []
    if buy_edge > 0:
        notes.append("full_set_buy_below_par")
    if sell_edge > 0:
        notes.append("full_set_sell_above_par")
    if merge_value > 0:
        notes.append("merge_beats_book_unwind")
    return ParitySignal(
        full_set_buy_edge=buy_edge,
        full_set_sell_edge=sell_edge,
        merge_value=merge_value,
        should_buy_full_set=buy_edge > 0.001,
        should_sell_full_set=sell_edge > 0.001,
        should_merge_inventory=inputs.paired_inventory > 0 and merge_value > 0.001,
        notes=notes,
    )

