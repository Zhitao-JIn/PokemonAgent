"""道具名字与价格：表内名字、表外 Hex、名字反查的折叠、HM / TM 与 BCD 解码。"""

from pokemon_agent.world.items import ITEM_PRICES, item_id, item_name, item_price

MASTER_BALL = 1
POKE_BALL = 4
FIRST_TM = 0xC9
BLANK_ROM = bytes(0x5000)


def test_item_name_returns_table_name_for_known_id() -> None:
    assert item_name(MASTER_BALL) == "MASTER BALL"


def test_item_name_writes_unknown_id_as_hex() -> None:
    assert item_name(98) == "ITEM_0x62"


def test_item_id_round_trips_through_item_name() -> None:
    assert item_id(item_name(POKE_BALL)) == POKE_BALL


def test_item_id_folds_case_and_accents() -> None:
    assert item_id("poké ball") == POKE_BALL
    assert item_id("POKE BALL") == POKE_BALL


def test_item_id_returns_none_for_unknown_name() -> None:
    assert item_id("NOT AN ITEM") is None


def test_item_price_is_zero_for_the_hm_range() -> None:
    assert [item_price(BLANK_ROM, item) for item in range(0xC4, 0xC9)] == [0] * 5


def test_item_price_is_none_for_tm_and_out_of_range_ids() -> None:
    assert item_price(BLANK_ROM, FIRST_TM) is None
    assert item_price(BLANK_ROM, 0x54) is None
    assert item_price(BLANK_ROM, 0) is None


def test_item_price_decodes_bcd_from_rom() -> None:
    rom = bytearray(ITEM_PRICES + 3)
    rom[ITEM_PRICES : ITEM_PRICES + 3] = bytes([0x00, 0x03, 0x00])

    assert item_price(bytes(rom), 1) == 300
