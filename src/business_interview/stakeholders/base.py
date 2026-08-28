"""Shared base behavior for deeply immutable stakeholder value models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Self

from pydantic import BaseModel, ConfigDict


class _DeeplyImmutableModel(BaseModel):
    """Freeze nested collections and validate Pydantic copy operations too.

    Mapping fields are stored as read-only proxies by their concrete models.
    Rebuilding through validation here keeps ``model_copy`` from bypassing
    those post-validation normalization steps.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Return a freshly validated immutable copy.

        Pydantic's default implementation deliberately skips validation for
        ``update`` and cannot deepcopy ``MappingProxyType``. Re-validating the
        serialized value preserves the immutable contract for both forms.
        """
        del deep
        data = self.model_dump(mode="python")
        if update is not None:
            data.update(update)
        return self.__class__.model_validate(data)
