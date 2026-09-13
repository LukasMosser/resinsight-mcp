"""Serialize explicit values shared by simulator input writers."""

from resinsight_mcp.contracts.errors import ContractError, Error, ErrorCode


def deck_text(value: str | int | float) -> str:
    if isinstance(value, str):
        if "'" in value or "\n" in value or "\r" in value:
            raise ContractError(
                Error(
                    code=ErrorCode.INVALID_MODEL,
                    message="Schedule serialization cannot preserve quoted or multiline strings.",
                )
            )
        return f"'{value}'"
    return format(value, ".17g") if isinstance(value, float) else str(value)


def control_keyword(
    name: str, status: str, mode: str, rate: float | None, bhp: float, phase: str | None
) -> str:
    target = "1*" if rate is None else deck_text(rate)
    if phase is None:
        row = (
            f" {deck_text(name)} {deck_text(status)} {deck_text(mode)} "
            f"{target} 4* {deck_text(bhp)} /\n"
        )
        return "WCONPROD\n" + row + "/\n"
    row = (
        f" {deck_text(name)} {deck_text(phase)} {deck_text(status)} "
        f"{deck_text(mode)} {target} 1* {deck_text(bhp)} /\n"
    )
    return "WCONINJE\n" + row + "/\n"
