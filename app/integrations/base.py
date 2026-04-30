from abc import ABC, abstractmethod


class BaseIntegrationProvider(ABC):
    def __init__(self, config: dict) -> None:
        self.config = config

    @abstractmethod
    async def test_connection(self) -> bool: ...
