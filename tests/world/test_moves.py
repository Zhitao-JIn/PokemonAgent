"""招式名字与比对用的规范形：表内名字、表外 Hex、大写与音符折叠、空白归一。"""

from pokemon_agent.world.moves import fold, move_name


def test_move_name_returns_table_name_for_known_id() -> None:
    assert move_name(1) == "POUND"


def test_move_name_writes_unknown_id_as_hex() -> None:
    assert move_name(166) == "MOVE_0xA6"


def test_fold_uppercases_and_maps_accents() -> None:
    assert fold("pound") == "POUND"
    assert fold("poké ball") == "POKE BALL"
    assert fold("POKÉ BALL") == "POKE BALL"


def test_fold_collapses_whitespace_and_is_idempotent() -> None:
    once = fold("  vice   grip  ")

    assert once == "VICE GRIP"
    assert fold(once) == once
