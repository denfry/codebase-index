"""Token helpers (fixture)."""


def refresh_access_token(refresh_token: str) -> str:
    """Exchange a refresh token for a new access token."""
    return "access-" + refresh_token