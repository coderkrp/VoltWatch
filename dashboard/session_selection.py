def resolve_selected_session(
    session_ids: list[int],
    prior_selected_session_id: int | None,
    active_session_id: int | None,
    latest_session_id: int | None,
    live_mode: bool,
) -> tuple[int, str | None]:
    if not session_ids:
        raise ValueError("session_ids must not be empty")

    default_session_id = latest_session_id if latest_session_id in session_ids else session_ids[0]
    selected_session_id = (
        prior_selected_session_id if prior_selected_session_id in session_ids else default_session_id
    )
    info_message = None

    if live_mode:
        target_session_id = None
        if active_session_id in session_ids:
            target_session_id = active_session_id
            if selected_session_id != target_session_id:
                info_message = f"Auto-switched to active session {target_session_id}."
        elif latest_session_id in session_ids:
            target_session_id = latest_session_id
            if selected_session_id != target_session_id:
                info_message = f"Active session unavailable. Showing latest session {target_session_id}."

        if target_session_id is not None:
            selected_session_id = target_session_id

    return selected_session_id, info_message
