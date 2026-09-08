from __future__ import annotations

import pytest

from opcoes.auth import (
    clear_login_rate_limit,
    get_login_block_remaining_seconds,
    record_failed_login_attempt,
)


pytestmark = pytest.mark.requires_postgres


@pytest.mark.parametrize("max_attempts", [1, 2, 5])
def test_rate_limit_blocks_at_configured_threshold_and_resets(max_attempts):
    client_key = "192.0.2.30"
    for _cycle in range(2):
        assert (
            get_login_block_remaining_seconds(client_key=client_key, window_seconds=120)
            is None
        )
        for _attempt in range(max_attempts - 1):
            assert (
                record_failed_login_attempt(
                    client_key=client_key,
                    window_seconds=120,
                    block_seconds=120,
                    max_attempts=max_attempts,
                )
                is None
            )
        remaining = record_failed_login_attempt(
            client_key=client_key,
            window_seconds=120,
            block_seconds=120,
            max_attempts=max_attempts,
        )
        assert remaining is not None and 0 < remaining <= 120
        assert (
            get_login_block_remaining_seconds(client_key=client_key, window_seconds=120)
            is not None
        )
        assert (
            get_login_block_remaining_seconds(
                client_key="192.0.2.31", window_seconds=120
            )
            is None
        )
        clear_login_rate_limit(client_key=client_key)
