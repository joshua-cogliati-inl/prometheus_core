# This file is part of Prometheus
# https://inl.gov/super-intelligence/prometheus/
#
# Copyright 2026 Battelle Energy Alliance, LLC
# All rights reserved, see NOTICE.txt for full restrictions
# https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
#
# Licensed under the MIT License, please see LICENSE for details
# https://github.com/idaholab/prometheus_core/blob/main/LICENSE
#
# SPDX-License-Identifier: MIT

"""Tag models for the storage client."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class TagModel(BaseModel):
    """Represents a tag that can be attached to items."""

    id: Optional[int] = Field(None, description="Tag ID")
    name: str = Field(..., description="Tag name")

    model_config = {"from_attributes": True}

    @classmethod
    def from_generated(cls, dto: Any) -> "TagModel":
        """Build a tag from a generated ``TagResponseDto`` (unset fields become ``None``)."""
        tag_id = getattr(dto, "id", None)
        return cls(
            id=int(tag_id) if isinstance(tag_id, (int, str)) and tag_id != "" else None,
            name=str(dto.name),
        )
