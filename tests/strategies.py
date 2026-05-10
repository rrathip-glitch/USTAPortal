"""Hypothesis strategies shared across unit tests."""

from __future__ import annotations

from hypothesis import strategies as st


def _standard_set_str() -> st.SearchStrategy[str]:
    """A standard tennis set: 6-N (N<=4), 7-5, or 7-6(L) with L<7."""
    six_n = st.integers(min_value=0, max_value=4).map(lambda n: f"6-{n}")
    n_six = st.integers(min_value=0, max_value=4).map(lambda n: f"{n}-6")
    seven_five = st.sampled_from(["7-5", "5-7"])
    tb_loser = st.integers(min_value=0, max_value=20)
    tb_a = tb_loser.map(lambda n: f"7-6({n})")
    tb_b = tb_loser.map(lambda n: f"6-7({n})")
    return st.one_of(six_n, n_six, seven_five, tb_a, tb_b)


def _match_tiebreak_str() -> st.SearchStrategy[str]:
    """A 10-point match tiebreak in either bracket or 1-0(loser) form."""
    loser = st.integers(min_value=0, max_value=20)
    bracket = loser.flatmap(
        lambda lo: st.sampled_from([f"[{max(lo + 2, 10)}-{lo}]", f"[{lo}-{max(lo + 2, 10)}]"])
    )
    paren = loser.flatmap(lambda lo: st.sampled_from([f"1-0({lo})", f"0-1({lo})"]))
    return st.one_of(bracket, paren)


@st.composite
def valid_score_string(draw: st.DrawFn) -> str:
    """Generate well-formed USTA-style score strings.

    Covers walkover/default/unfinished, two- and three-set completed matches
    (with optional final-set match tiebreak), and retirements.
    """
    kind = draw(
        st.sampled_from(
            [
                "walkover",
                "default",
                "unfinished",
                "two_set",
                "three_set",
                "three_set_mtb",
                "retired",
            ]
        )
    )
    if kind == "walkover":
        return draw(st.sampled_from(["W/O", "WO", "walkover", "Walk-Over"]))
    if kind == "default":
        return draw(st.sampled_from(["DEF", "default", "Def."]))
    if kind == "unfinished":
        return draw(st.sampled_from(["", "-", "TBD", "  "]))
    if kind == "two_set":
        return f"{draw(_standard_set_str())} {draw(_standard_set_str())}"
    if kind == "three_set":
        return " ".join(draw(_standard_set_str()) for _ in range(3))
    if kind == "three_set_mtb":
        return f"{draw(_standard_set_str())} {draw(_standard_set_str())} {draw(_match_tiebreak_str())}"
    # retired
    n_sets = draw(st.integers(min_value=1, max_value=3))
    body = " ".join(draw(_standard_set_str()) for _ in range(n_sets))
    suffix = draw(st.sampled_from(["RET", "ret", "ret.", "Retired"]))
    return f"{body} {suffix}"
