"""Service layer (fixture) - exercises cross-file edges for impact tests."""

from auth.token import refresh_access_token
from models.user import User


class AdminUser(User):
    """Subclass of User; imported-from edge target for impact tests."""

    def renew(self, refresh_token: str) -> str:
        return refresh_access_token(refresh_token)
