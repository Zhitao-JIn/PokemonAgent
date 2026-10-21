"""历史输入结构化往返；不能无损还原的输入显式计数，不改变 golden。"""

from collections import Counter
from pathlib import Path

from scripts.capture_prompt_golden import GoldenCase, render_case

from .legacy_adapter import UnrestorableRequest, adapt_request

GOLDEN = Path(__file__).parent / "golden"


def test_the_corpus_roundtrips_without_changing_any_old_prompt() -> None:
    paths = sorted(GOLDEN.glob("*/*.req.json"))
    skipped: Counter[str] = Counter()
    restored = 0
    for path in paths:
        case = GoldenCase.model_validate_json(path.read_bytes())
        try:
            adapted = adapt_request(case.request)
        except UnrestorableRequest as error:
            skipped[str(error)] += 1
            continue

        actual = render_case(case.model_copy(update={"request": adapted.request}))
        expected = path.with_name(path.name.removesuffix(".req.json") + ".prompt.txt").read_bytes()

        assert actual == expected, str(path)
        restored += 1
    assert restored + sum(skipped.values()) == len(paths)
    assert sum(skipped.values()) / len(paths) <= 0.2, dict(skipped)
