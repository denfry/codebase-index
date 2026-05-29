"""Token helpers (fixture)."""


def refresh_access_token(refresh_token: str) -> str:
    """Exchange a refresh token for a new access token."""
    return "access-" + refresh_token


def login(refresh_token: str) -> str:
    """Calls refresh_access_token so refs/impact tests have an edge."""
    return refresh_access_token(refresh_token)
