from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


class BudgetExceeded(ValueError):
    """Raised when an operation exceeds a configured cost or query budget."""


@dataclass(frozen=True)
class Scope:
    project_name: str
    project_id: str
    source_stream_name: str
    source_stream_id: str
    telemetry_stream_name: str
    telemetry_stream_id: str | None = None

    def public_dict(self) -> dict[str, str | None]:
        return {
            "project": self.project_name,
            "project_id": self.project_id,
            "source_log_stream": self.source_stream_name,
            "source_log_stream_id": self.source_stream_id,
            "telemetry_log_stream": self.telemetry_stream_name,
            "telemetry_log_stream_id": self.telemetry_stream_id,
        }


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime

    @classmethod
    def recent_hours(cls, hours: int, max_hours: int) -> "TimeWindow":
        if hours < 1:
            raise BudgetExceeded("Lookback must be at least one hour.")
        if hours > max_hours:
            raise BudgetExceeded(f"Lookback of {hours} hours exceeds the limit of {max_hours} hours.")
        end = datetime.now(timezone.utc)
        return cls(start=end - timedelta(hours=hours), end=end)

    def public_dict(self) -> dict[str, str]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass(frozen=True)
class OperationPreview:
    operation: str
    project: str
    resource: str
    records: int
    estimated_generation_calls: int = 0
    estimated_evaluator_calls: int = 0
    details: dict[str, Any] | None = None

    def lines(self) -> list[str]:
        lines = [
            f"Operation: {self.operation}",
            f"Project:   {self.project}",
            f"Resource:  {self.resource}",
            f"Records:   {self.records}",
        ]
        if self.estimated_generation_calls:
            lines.append(f"Estimated generation calls: {self.estimated_generation_calls}")
        if self.estimated_evaluator_calls:
            lines.append(f"Estimated evaluator calls:  up to {self.estimated_evaluator_calls}")
        if self.details:
            for key, value in self.details.items():
                lines.append(f"{key}: {value}")
        return lines
