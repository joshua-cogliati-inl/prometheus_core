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

"""Relationship models for the storage client."""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from .item import value_of


class RelationshipBase(BaseModel):
    """Base model for relationship data."""

    from_item_id: int = Field(..., description="Source item ID")
    to_item_id: int = Field(..., description="Target item ID")
    relationship_type: str = Field(..., description="Type of relationship")
    properties: Dict[str, Any] = Field(
        default_factory=dict, description="Custom properties for the relationship"
    )

    model_config = {"from_attributes": True}


class RelationshipCreate(RelationshipBase):
    """Model for creating a new relationship."""

    pass


class Relationship(RelationshipBase):
    """Full relationship model including system fields."""

    id: int = Field(default=0, description="Relationship ID")
    relationship_type: str = Field(default="", description="Type of relationship")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")

    # System fields (from DeepLynx)
    relationship_pair_id: Optional[int] = Field(None, description="Internal relationship pair ID")
    data_source_id: Optional[int] = Field(None, description="Source data identifier")

    model_config = {"from_attributes": True}

    @field_validator("properties", mode="before")
    @classmethod
    def _decode_json_properties(cls, value: Any) -> Any:
        """Accept the JSON-encoded string DeepLynx returns for edge properties.

        The edge endpoints return ``properties`` as a string (for example ``"{}"``) or ``null``,
        not as an object. Undecodable or non-object strings become an empty dict, matching how
        item properties are parsed.
        """
        if value is None:
            return {}
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except (TypeError, ValueError):
                return {}
            return decoded if isinstance(decoded, dict) else {}
        return value

    @classmethod
    def from_generated(cls, dto: Any) -> "Relationship":
        """Build a relationship from a generated ``EdgeResponseDto``.

        ``properties`` is the JSON string (or null) Nexus returns and is decoded by the model.
        The edge response carries ``relationshipId`` but not the relationship's name, so
        ``relationship_type`` stays empty. Raises ``ValueError`` without origin and destination IDs.
        """
        origin_id = value_of(dto, "origin_id")
        destination_id = value_of(dto, "destination_id")
        if origin_id is None or destination_id is None:
            raise ValueError(
                "API response missing required node ID fields. Expected 'originId' and "
                f"'destinationId'; got {sorted(getattr(dto, 'additional_properties', {}))}."
            )
        relationship_id = value_of(dto, "relationship_id")
        data_source_id = value_of(dto, "data_source_id")
        return cls(
            id=int(dto.id),
            from_item_id=int(origin_id),
            to_item_id=int(destination_id),
            properties=value_of(dto, "properties"),
            created_at=None,
            updated_at=value_of(dto, "last_updated_at"),
            relationship_pair_id=None if relationship_id is None else int(relationship_id),
            data_source_id=None if data_source_id is None else int(data_source_id),
        )

    @classmethod
    def from_related_record(cls, dto: Any, item_id: int, outgoing: bool) -> "Relationship":
        """Build a relationship from a generated ``RelatedRecordsResponseDto``.

        The list-by-record route returns only the related record and the relationship's name,
        so ``id`` is 0 and ``properties`` is empty; ``item_id`` is the origin when ``outgoing``.
        """
        related = value_of(dto, "related_record_id")
        if related is None:
            raise ValueError("API response missing 'relatedRecordId' for a related record.")
        return cls(
            from_item_id=item_id if outgoing else int(related),
            to_item_id=int(related) if outgoing else item_id,
            relationship_type=value_of(dto, "relationship_name") or "",
            created_at=None,
            updated_at=None,
            relationship_pair_id=None,
            data_source_id=None,
        )


class BulkRelationshipCreate(BaseModel):
    """Wrapper for bulk relationship creation operations."""

    relationships: List[RelationshipCreate] = Field(
        ..., description="List of relationships to create"
    )

    model_config = {"from_attributes": True}
