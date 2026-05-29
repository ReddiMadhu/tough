"""
Migration Pydantic models and enums for the ThoughtSpot → Power BI API.
"""
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────────────────────

class MigrationStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED  = "completed"
    FAILED     = "failed"


class ConfidenceLevel(str, Enum):
    HIGH   = "high"    # >= 0.9
    MEDIUM = "medium"  # >= 0.6
    LOW    = "low"     # < 0.6

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        if score >= 0.9:
            return cls.HIGH
        if score >= 0.6:
            return cls.MEDIUM
        return cls.LOW


class DAXPattern(str, Enum):
    DIRECT_AGG          = "DIRECT_AGG"
    CALCULATE_ALLEXCEPT = "CALCULATE_ALLEXCEPT"
    CALCULATE_ALL       = "CALCULATE_ALL"
    PERCENT_OF_TOTAL    = "PERCENT_OF_TOTAL"
    DYNAMIC_GROUPING    = "DYNAMIC_GROUPING"
    RUNNING_TOTAL       = "RUNNING_TOTAL"
    MOVING_AVERAGE      = "MOVING_AVERAGE"
    CONDITIONAL         = "CONDITIONAL"
    DATE_FUNCTION       = "DATE_FUNCTION"
    TEXT_FUNCTION       = "TEXT_FUNCTION"
    ARITHMETIC          = "ARITHMETIC"
    FALLBACK            = "FALLBACK"
    EMPTY               = "EMPTY"


# ── Upload / Start ─────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    migration_id: str
    status: MigrationStatus = MigrationStatus.PROCESSING
    file_count: int
    message: str


# ── Status ─────────────────────────────────────────────────────────────────────

class MigrationStats(BaseModel):
    tables:              int = 0
    formulas_converted:  int = 0
    high_confidence:     int = 0
    medium_confidence:   int = 0
    low_confidence:      int = 0
    requires_review:     int = 0
    elapsed_seconds:     float = 0.0


class MigrationStatusResponse(BaseModel):
    migration_id:   str
    status:         MigrationStatus
    file_count:     int = 0
    tables:         int = 0
    formulas_converted: int = 0
    high_confidence:    int = 0
    medium_confidence:  int = 0
    low_confidence:     int = 0
    requires_review:    int = 0
    error_message:      Optional[str] = None
    elapsed_seconds:    Optional[float] = None
    created_at:         Optional[str] = None
    completed_at:       Optional[str] = None
    narrative_summary:  Optional[str] = None



# ── Conversions ────────────────────────────────────────────────────────────────

class DAXConversionItem(BaseModel):
    conversion_id:      str
    measure_name:       str
    original_formula:   str
    dax_formula:        str
    confidence:         float = Field(ge=0.0, le=1.0)
    pattern:            str
    notes:              List[str] = []
    requires_review:    bool = False
    source_object:      str = ""
    source_object_type: str = ""
    format_pattern:     str = ""

    @property
    def confidence_level(self) -> ConfidenceLevel:
        return ConfidenceLevel.from_score(self.confidence)


class ConversionsResponse(BaseModel):
    migration_id: str
    conversions:  List[Dict[str, Any]]


# ── Error ──────────────────────────────────────────────────────────────────────

class ErrorDetail(BaseModel):
    code:    str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
