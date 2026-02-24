from abc import ABC, abstractmethod


class BaseSource(ABC):
    @abstractmethod
    def load(self) -> list[dict]:
        """Load raw product data from the ERP source."""
