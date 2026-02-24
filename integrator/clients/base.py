from abc import ABC, abstractmethod

import requests


class BaseClient(ABC):
    @abstractmethod
    def make_session(self) -> requests.Session:
        """Create and configure an HTTP session with auth headers."""

    @abstractmethod
    def send(self, session, payload, is_update=False):
        """Send a single product payload to the target API."""
