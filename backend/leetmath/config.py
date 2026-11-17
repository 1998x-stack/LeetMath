"""Runtime configuration (env-driven, 12-factor)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "LEETMATH_DATABASE_URL", f"sqlite:///{ROOT / 'var' / 'leetmath.db'}"
        )
    )
    # Object storage root for raw import archives / assets (S3 in production).
    storage_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("LEETMATH_STORAGE_DIR", ROOT / "var" / "objects"))
    )
    session_ttl_hours: int = int(os.environ.get("LEETMATH_SESSION_TTL_HOURS", "72"))
    # Grader sandbox limits (docs/06 §3)
    grader_timeout_s: float = float(os.environ.get("LEETMATH_GRADER_TIMEOUT_S", "4"))
    grader_memory_mb: int = int(os.environ.get("LEETMATH_GRADER_MEMORY_MB", "512"))
    grader_max_input_len: int = 500
    grader_max_depth: int = 40
    # Workflow policy (docs/08 §2): math and rights reviewers must be different people.
    require_distinct_reviewers: bool = os.environ.get("LEETMATH_DISTINCT_REVIEWERS", "1") == "1"
    rate_limit_per_minute: int = int(os.environ.get("LEETMATH_RATE_LIMIT_PER_MIN", "120"))


settings = Settings()
