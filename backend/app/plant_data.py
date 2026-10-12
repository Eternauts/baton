"""Simulated plant feed and permits used by the safety rules. This is mock data, not live telemetry."""
from __future__ import annotations

from typing import Any, Dict, List

MOCK_DCS_TELEMETRY: Dict[str, Any] = {
    "P-201B": {"status": "OPEN", "pressure": 12.4, "temp_c": 64.2},
    "V-102": {"status": "CLOSED", "flow_rate": 0.0},
    "ESDV-301": {"status": "BYPASS", "active": True},
    "TK-501": {"status": "ACTIVE", "level_pct": 82.5},
}

MOCK_ACTIVE_PERMITS: List[Dict[str, Any]] = [
    {"id": "PERMIT-HW-409", "type": "HOT_WORK", "title": "Unit 3 Flare Line Welding", "status": "OPEN"},
    {"id": "PERMIT-M-102", "type": "MAINTENANCE", "title": "Pump Gasket Replacement", "status": "EXPIRED", "expired": True},
]
