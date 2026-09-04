"""Optional FastAPI adapter above the platform and application layers."""

from squadopt.api.app import DEFAULT_SITE_DATA_ROOT, app, create_app
from squadopt.api.views import (
    FilePublishedViewStore,
    JsonDocument,
    PublishedViewError,
    PublishedViewIntegrityError,
    PublishedViewNotFoundError,
    PublishedViewStore,
)

__all__ = [
    "DEFAULT_SITE_DATA_ROOT",
    "FilePublishedViewStore",
    "JsonDocument",
    "PublishedViewError",
    "PublishedViewIntegrityError",
    "PublishedViewNotFoundError",
    "PublishedViewStore",
    "app",
    "create_app",
]
