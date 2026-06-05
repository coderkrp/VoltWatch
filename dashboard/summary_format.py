from __future__ import annotations


def format_summary_block(title: str, rows: list[tuple[str, float, str]]) -> str:
    lines = [f"**{title}:**"]
    for label, value, unit in rows:
        lines.append(f"**{label}:** {value:.2f} {unit}")
    return "\n\n".join(lines)


def build_summary_blocks(stats: dict[str, float]) -> tuple[str, str, str]:
    return (
        format_summary_block(
            "Supply Voltage",
            [
                ("Avg", stats["Supply Voltage Avg"], "V"),
                ("Max", stats["Supply Voltage Max"], "V"),
            ],
        ),
        format_summary_block(
            "Current",
            [
                ("Avg", stats["Current Avg"], "mA"),
                ("Max", stats["Current Max"], "mA"),
                ("Charge", stats["Charge Total"], "mAh"),
            ],
        ),
        format_summary_block(
            "Power",
            [
                ("Avg", stats["Power Avg"], "mW"),
                ("Max", stats["Power Max"], "mW"),
                ("Energy", stats["Energy Total"], "mWh"),
            ],
        ),
    )
