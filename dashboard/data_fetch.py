INTERVAL_SAMPLE_STEPS = {
    "1 sec": None,
    "5 sec": 5,
    "30 sec": 30,
    "1 min": 60,
    "5 min": 300,
    "15 min": 900,
}


def interval_to_sample_step(interval: str) -> int | None:
    try:
        return INTERVAL_SAMPLE_STEPS[interval]
    except KeyError as exc:
        raise ValueError(f"Unsupported interval: {interval}") from exc
