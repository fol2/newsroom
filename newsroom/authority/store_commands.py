from __future__ import annotations

from .store_commit import AuthorityStoreCommitMixin
from .store_read import AuthorityStoreReadMixin
from .store_results import AuthorityStoreResultsMixin


class AuthorityStoreCommandsMixin(
    AuthorityStoreCommitMixin,
    AuthorityStoreResultsMixin,
    AuthorityStoreReadMixin,
):
    """Command, result and read behaviours composed over the SQLite base."""

    pass
