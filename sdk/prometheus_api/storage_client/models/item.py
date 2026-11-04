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

"""Item models for the storage client."""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class Tag(BaseModel):
    """Represents a tag associated with an item."""

    id: Optional[int] = Field(None, description="Tag ID")
    name: str = Field(..., description="Tag name")

    model_config = {"from_attributes": True}


class ItemBase(BaseModel):
    """Base model for item data."""

    name: str = Field(..., description="Item name")
    description: Optional[str] = Field(None, description="Item description")
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Custom properties/metadata for the item"
    )
    class_id: Optional[int] = Field(None, description="Class identifier for the item")
    original_id: Optional[str] = Field(None, description="Original identifier from source system")

    model_config = {"from_attributes": True}


class ItemCreate(ItemBase):
    """Model for creating a new item."""

    tags: Optional[List[str]] = Field(
        default=None, description="List of tag names to associate with the item"
    )

    def to_generated(self, original_id: str) -> Any:
        """Build a generated ``CreateRecordRequestDto``.

        Nexus rejects an empty description, so the name is used when none is given.
        """
        from ..nexus_client import ensure_nexus_client

        models = ensure_nexus_client().models
        optional: Dict[str, Any] = {}
        if self.class_id:
            optional["class_id"] = self.class_id
        return models.CreateRecordRequestDto(
            name=self.name,
            description=self.description or self.name,
            properties=models.JsonObject.from_dict(self.properties),
            original_id=original_id,
            **optional,
        )


class ItemUpdate(BaseModel):
    """Model for updating an existing item. All fields are optional."""

    name: Optional[str] = Field(None, description="Item name")
    description: Optional[str] = Field(None, description="Item description")
    properties: Optional[Dict[str, Any]] = Field(None, description="Custom properties/metadata")
    class_id: Optional[int] = Field(None, description="Class identifier")
    original_id: Optional[str] = Field(None, description="Original identifier")

    model_config = {"from_attributes": True}

    def to_generated(self) -> Any:
        """Build a generated ``UpdateRecordRequestDto`` holding only the provided fields."""
        from ..nexus_client import ensure_nexus_client

        models = ensure_nexus_client().models
        fields: Dict[str, Any] = {}
        if self.name is not None:
            fields["name"] = self.name
        if self.description is not None:
            fields["description"] = self.description
        if self.properties is not None:
            fields["properties"] = models.JsonObject.from_dict(self.properties)
        if self.class_id is not None:
            fields["class_id"] = self.class_id
        if self.original_id is not None:
            fields["original_id"] = self.original_id
        return models.UpdateRecordRequestDto(**fields)


class Item(ItemBase):
    """Full item model including system fields."""

    id: int = Field(..., description="Item ID")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    tags: List[Tag] = Field(default_factory=list, description="Associated tags")

    # System fields (from DeepLynx)
    metatype_id: Optional[int] = Field(None, description="Internal metatype identifier")
    metatype_name: Optional[str] = Field(None, description="Internal metatype name")
    data_source_id: Optional[int] = Field(None, description="Source data identifier")

    model_config = {"from_attributes": True}

    @classmethod
    def from_generated(cls, dto: Any) -> "Item":
        """Build an item from a generated ``RecordResponseDto``.

        Unset fields become ``None`` (or the defaults of the hand-written parser): Nexus sends
        ``properties`` as a JSON string, which is decoded here (an invalid string becomes
        ``{}``); ``className`` is not a declared field of the DTO, so it is read from the
        extra properties; and ``lastUpdatedAt`` is used for both timestamps, falling back to now.
        """

        properties = value_of(dto, "properties") or {}
        if isinstance(properties, str):
            try:
                properties = json.loads(properties)
            except ValueError:
                properties = {}
        if not isinstance(properties, dict):
            properties = {}

        timestamp = value_of(dto, "last_updated_at") or datetime.now()
        class_id = value_of(dto, "class_id")
        data_source_id = value_of(dto, "data_source_id")
        tags = [
            Tag(id=value_of(t, "id"), name=value_of(t, "name") or "")
            for t in (value_of(dto, "tags") or [])
        ]
        return cls(
            id=int(dto.id),
            name=value_of(dto, "name") or "",
            description=value_of(dto, "description"),
            properties=properties,
            class_id=None if class_id is None else int(class_id),
            original_id=value_of(dto, "original_id"),
            created_at=timestamp,
            updated_at=timestamp,
            tags=tags,
            metatype_id=None if class_id is None else int(class_id),
            metatype_name=(getattr(dto, "additional_properties", None) or {}).get("className"),
            data_source_id=None if data_source_id is None else int(data_source_id),
        )


def value_of(obj: Any, name: str) -> Any:
    """Return an attribute of a generated DTO, or ``None`` when it is ``UNSET``."""
    found = getattr(obj, name, None)
    return found if type(found).__name__ != "Unset" else None


class BulkItemCreate(BaseModel):
    """Wrapper for bulk item creation operations."""

    items: List[ItemCreate] = Field(..., description="List of items to create")

    model_config = {"from_attributes": True}
