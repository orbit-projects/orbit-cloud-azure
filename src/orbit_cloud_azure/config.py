# Copyright 2026-present Orbit Contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Validated Azure Resource Graph settings."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AzureCloudInventoryConfig(BaseModel):
    """Bounded Resource Graph request settings with no embedded credential material.

    The adapter constructs Azure's async ``DefaultAzureCredential`` unless an application
    explicitly injects a credential factory.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    request_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    max_concurrency: int = Field(default=8, ge=1, le=32)
    retry_total: int = Field(default=3, ge=0, le=10)
    retry_initial_backoff_seconds: float = Field(default=0.5, gt=0, le=10)
    retry_max_backoff_seconds: float = Field(default=10.0, gt=0, le=60)

    @model_validator(mode="after")
    def validate_timeouts(self) -> AzureCloudInventoryConfig:
        """Reject non-finite timeout values after field range validation."""
        for name, value in (
            ("request_timeout_seconds", self.request_timeout_seconds),
            ("connect_timeout_seconds", self.connect_timeout_seconds),
            ("retry_initial_backoff_seconds", self.retry_initial_backoff_seconds),
            ("retry_max_backoff_seconds", self.retry_max_backoff_seconds),
        ):
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite.")
        if self.retry_initial_backoff_seconds > self.retry_max_backoff_seconds:
            raise ValueError(
                "retry_initial_backoff_seconds cannot exceed retry_max_backoff_seconds."
            )
        return self


__all__ = ["AzureCloudInventoryConfig"]
