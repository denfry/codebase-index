"""User model (fixture) - imported widely for impact tests."""


class User:
    def __init__(self, name: str) -> None:
        self.name = name