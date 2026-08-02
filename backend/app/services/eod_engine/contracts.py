"""Pydantic contracts for Institutional EOD Analysis Engine artifacts."""
from __future__ import annotations

import json
import os
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class TradeOutcome(str, Enum):
    TARGET_HIT = "TARGET_HIT"
    STOP_HIT = "STOP_HIT"
    NO_ENTRY = "NO_ENTRY"
    TRAILED_EXIT = "TRAILED_EXIT"
    EOD_SQUAREOFF = "EOD_SQUAREOFF"


class MarketRegimeLabel(str, Enum):
    BULL_TRENDING = "BULL_TRENDING"
    BEAR_TRENDING = "BEAR_TRENDING"
    HIGH_VOLATILITY_SIDEWAYS = "HIGH_VOLATILITY_SIDEWAYS"
    LOW_VOLATILITY_COMPRESSION = "LOW_VOLATILITY_COMPRESSION"
    SECTOR_ROTATION_SELECTIVE = "SECTOR_ROTATION_SELECTIVE"


class ProposalStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INSUFFICIENT_SAMPLES = "INSUFFICIENT_SAMPLES"


class TCABasis(str, Enum):
    MODELED = "MODELED"
    OBSERVED = "OBSERVED"


class ModeledTCA(BaseModel):
    """Transaction cost analysis. Fill-dependent fields are null or MODELED."""

    implementation_shortfall_bps: Optional[float] = None
    delay_cost_bps: Optional[float] = None
    spread_cost_bps: Optional[float] = None
    market_impact_bps: Optional[float] = None
    opportunity_cost_bps: Optional[float] = None
    basis: TCABasis = TCABasis.MODELED


class EfficiencyMetrics(BaseModel):
    mae_pct: Optional[float] = None
    mfe_pct: Optional[float] = None
    realized_return_ratio: Optional[float] = None
    stop_efficiency_index: Optional[float] = None


class AttributionBreakdown(BaseModel):
    alpha_score: Optional[float] = None
    volume_expansion_contrib: Optional[float] = None
    vwap_alignment_contrib: Optional[float] = None
    momentum_velocity_contrib: Optional[float] = None
    sector_relative_strength_contrib: Optional[float] = None
    open_interest_buildup_contrib: Optional[float] = None
    news_sentiment_contrib: Optional[float] = None
    allocation_effect: Optional[float] = None
    selection_effect: Optional[float] = None
    interaction_effect: Optional[float] = None


class CounterfactualScenario(BaseModel):
    scenario_name: str
    simulated_outcome: str
    simulated_pnl_pct: Optional[float] = None
    pnl_delta_vs_actual_pct: Optional[float] = None
    max_drawdown_during_trade_pct: Optional[float] = None


class TradeScorecardNode(BaseModel):
    trade_id: str
    ticker: str
    direction: Literal["LONG", "SHORT"]
    confidence_score: float = Field(ge=0.0, le=1.0)
    confidence_basis: Literal["FACTOR_SCORE"] = "FACTOR_SCORE"
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    stop_loss: float
    target_price: float
    signal_entry_price: Optional[float] = None
    outcome: TradeOutcome
    realized_pnl_pct: float = 0.0
    realized_pnl_abs: Optional[float] = None
    holding_duration_mins: Optional[int] = None
    sector: Optional[str] = None
    score: Optional[float] = None
    qty: Optional[int] = None
    deployed_capital: Optional[float] = None
    risk_per_share: Optional[float] = None
    tca: ModeledTCA
    efficiency: EfficiencyMetrics
    attribution: AttributionBreakdown
    counterfactuals: list[CounterfactualScenario] = Field(default_factory=list)
    success_factors: list[str] = Field(default_factory=list)
    failure_factors: list[str] = Field(default_factory=list)
    root_cause: Optional[str] = None
    false_positive: Optional[bool] = None
    timeline_events: list[dict[str, Any]] = Field(default_factory=list)
    factor_breakdown: Optional[dict[str, Any]] = None


class AuditTrailEntry(BaseModel):
    action: Literal["APPROVE", "REJECT"]
    reviewed_at: str
    reviewer: Optional[str] = None
    note: Optional[str] = None


class StrategyImprovementProposal(BaseModel):
    proposal_id: str
    parameter_name: str
    current_value: str
    proposed_value: str
    expected_pnl_uplift_pct: Optional[float] = None
    confidence_interval: Optional[str] = None
    supporting_evidence: dict[str, Any] = Field(default_factory=dict)
    status: ProposalStatus
    sample_count: int = 0
    audit_trail: list[AuditTrailEntry] = Field(default_factory=list)


class PMCommentary(BaseModel):
    executive_summary: str
    attribution_narrative: str
    execution_and_slippage_review: str
    actionable_directives: list[str] = Field(default_factory=list)
    source: Literal["LLM", "DETERMINISTIC_FALLBACK"] = "DETERMINISTIC_FALLBACK"


class RegimeBreadth(BaseModel):
    market_regime: MarketRegimeLabel
    raw_regime_label: Optional[str] = None
    bias: Optional[str] = None
    nifty_change_pct: Optional[float] = None
    bank_nifty_change_pct: Optional[float] = None
    india_vix: Optional[float] = None
    advance_decline_ratio: Optional[float] = None
    advances: Optional[int] = None
    declines: Optional[int] = None
    sector_rotation: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class MissedOpportunity(BaseModel):
    ticker: str
    day_change_pct: Optional[float] = None
    filter_reasons: list[str] = Field(default_factory=list)
    potential_move_pct: Optional[float] = None


class ExecutiveSummary(BaseModel):
    overall_institutional_score: float = Field(ge=0, le=10)
    total_trades: int = Field(ge=0)
    win_trades: int = Field(ge=0)
    loss_trades: int = Field(ge=0)
    no_entry_trades: int = Field(ge=0)
    win_rate_pct: Optional[float] = None
    average_risk_reward: Optional[float] = None
    net_strategy_return_pct: Optional[float] = None
    capital_efficiency_pct: Optional[float] = None
    expected_calibration_error: Optional[float] = None
    brier_score: Optional[float] = None
    market_regime: MarketRegimeLabel
    regime_breadth: Optional[RegimeBreadth] = None
    missed_opportunities: list[MissedOpportunity] = Field(default_factory=list)
    false_positive_count: int = 0


class CompleteEODAnalysisPayload(BaseModel):
    analysis_date: str
    generated_at: str
    status: Literal["OK", "NO_PICKS", "PARTIAL"] = "OK"
    notes: list[str] = Field(default_factory=list)
    executive_summary: ExecutiveSummary
    scorecards: list[TradeScorecardNode] = Field(default_factory=list)
    learning_proposals: list[StrategyImprovementProposal] = Field(default_factory=list)
    pm_commentary: PMCommentary
    schema_version: str = "1.0.0"


# ---------------------------------------------------------------------------
# Static JSON Schema emission (once under data/eod/eod_schema.json)
# ---------------------------------------------------------------------------

_SCHEMA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "eod")
)


def eod_schema_dict() -> dict[str, Any]:
    """Draft-07-ish JSON Schema derived from CompleteEODAnalysisPayload."""
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "CompleteEODAnalysisPayload",
        "type": "object",
        "required": [
            "analysis_date",
            "generated_at",
            "executive_summary",
            "scorecards",
            "learning_proposals",
            "pm_commentary",
        ],
        "properties": {
            "analysis_date": {"type": "string", "format": "date"},
            "generated_at": {"type": "string", "format": "date-time"},
            "status": {"type": "string", "enum": ["OK", "NO_PICKS", "PARTIAL"]},
            "notes": {"type": "array", "items": {"type": "string"}},
            "schema_version": {"type": "string"},
            "executive_summary": {
                "type": "object",
                "required": [
                    "overall_institutional_score",
                    "total_trades",
                    "win_trades",
                    "loss_trades",
                    "win_rate_pct",
                    "net_strategy_return_pct",
                    "expected_calibration_error",
                    "market_regime",
                ],
                "properties": {
                    "overall_institutional_score": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 10,
                    },
                    "total_trades": {"type": "integer", "minimum": 0},
                    "win_trades": {"type": "integer", "minimum": 0},
                    "loss_trades": {"type": "integer", "minimum": 0},
                    "no_entry_trades": {"type": "integer", "minimum": 0},
                    "win_rate_pct": {"type": ["number", "null"]},
                    "average_risk_reward": {"type": ["number", "null"]},
                    "net_strategy_return_pct": {"type": ["number", "null"]},
                    "capital_efficiency_pct": {"type": ["number", "null"]},
                    "expected_calibration_error": {"type": ["number", "null"]},
                    "brier_score": {"type": ["number", "null"]},
                    "market_regime": {
                        "type": "string",
                        "enum": [e.value for e in MarketRegimeLabel],
                    },
                    "false_positive_count": {"type": "integer"},
                },
            },
            "scorecards": {
                "type": "array",
                "items": {"$ref": "#/definitions/TradeScorecardNode"},
            },
            "learning_proposals": {
                "type": "array",
                "items": {"$ref": "#/definitions/StrategyImprovementProposal"},
            },
            "pm_commentary": {
                "type": "object",
                "required": [
                    "executive_summary",
                    "attribution_narrative",
                    "execution_and_slippage_review",
                    "actionable_directives",
                ],
                "properties": {
                    "executive_summary": {"type": "string"},
                    "attribution_narrative": {"type": "string"},
                    "execution_and_slippage_review": {"type": "string"},
                    "actionable_directives": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "source": {
                        "type": "string",
                        "enum": ["LLM", "DETERMINISTIC_FALLBACK"],
                    },
                },
            },
        },
        "definitions": {
            "TradeScorecardNode": {
                "type": "object",
                "required": [
                    "trade_id",
                    "ticker",
                    "direction",
                    "confidence_score",
                    "confidence_basis",
                    "stop_loss",
                    "target_price",
                    "outcome",
                    "realized_pnl_pct",
                    "tca",
                    "efficiency",
                    "attribution",
                    "counterfactuals",
                ],
                "properties": {
                    "trade_id": {"type": "string"},
                    "ticker": {"type": "string"},
                    "direction": {"type": "string", "enum": ["LONG", "SHORT"]},
                    "confidence_score": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                    "confidence_basis": {
                        "type": "string",
                        "const": "FACTOR_SCORE",
                    },
                    "entry_price": {"type": ["number", "null"]},
                    "exit_price": {"type": ["number", "null"]},
                    "stop_loss": {"type": "number"},
                    "target_price": {"type": "number"},
                    "outcome": {
                        "type": "string",
                        "enum": [e.value for e in TradeOutcome],
                    },
                    "realized_pnl_pct": {"type": "number"},
                    "holding_duration_mins": {"type": ["integer", "null"]},
                    "tca": {
                        "type": "object",
                        "properties": {
                            "implementation_shortfall_bps": {
                                "type": ["number", "null"]
                            },
                            "delay_cost_bps": {"type": ["number", "null"]},
                            "spread_cost_bps": {"type": ["number", "null"]},
                            "market_impact_bps": {"type": ["number", "null"]},
                            "opportunity_cost_bps": {"type": ["number", "null"]},
                            "basis": {
                                "type": "string",
                                "enum": ["MODELED", "OBSERVED"],
                            },
                        },
                    },
                    "efficiency": {
                        "type": "object",
                        "properties": {
                            "mae_pct": {"type": ["number", "null"]},
                            "mfe_pct": {"type": ["number", "null"]},
                            "realized_return_ratio": {"type": ["number", "null"]},
                            "stop_efficiency_index": {"type": ["number", "null"]},
                        },
                    },
                    "attribution": {
                        "type": "object",
                        "required": ["alpha_score"],
                        "properties": {
                            "alpha_score": {"type": ["number", "null"]},
                            "volume_expansion_contrib": {"type": ["number", "null"]},
                            "vwap_alignment_contrib": {"type": ["number", "null"]},
                            "momentum_velocity_contrib": {"type": ["number", "null"]},
                            "sector_relative_strength_contrib": {
                                "type": ["number", "null"]
                            },
                            "open_interest_buildup_contrib": {
                                "type": ["number", "null"]
                            },
                            "news_sentiment_contrib": {"type": ["number", "null"]},
                        },
                    },
                    "counterfactuals": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "scenario_name",
                                "simulated_outcome",
                                "simulated_pnl_pct",
                                "pnl_delta_vs_actual_pct",
                                "max_drawdown_during_trade_pct",
                            ],
                            "properties": {
                                "scenario_name": {"type": "string"},
                                "simulated_outcome": {"type": "string"},
                                "simulated_pnl_pct": {"type": ["number", "null"]},
                                "pnl_delta_vs_actual_pct": {
                                    "type": ["number", "null"]
                                },
                                "max_drawdown_during_trade_pct": {
                                    "type": ["number", "null"]
                                },
                            },
                        },
                    },
                    "success_factors": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "failure_factors": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
            "StrategyImprovementProposal": {
                "type": "object",
                "required": [
                    "proposal_id",
                    "parameter_name",
                    "current_value",
                    "proposed_value",
                    "status",
                ],
                "properties": {
                    "proposal_id": {"type": "string"},
                    "parameter_name": {"type": "string"},
                    "current_value": {"type": "string"},
                    "proposed_value": {"type": "string"},
                    "expected_pnl_uplift_pct": {"type": ["number", "null"]},
                    "confidence_interval": {"type": ["string", "null"]},
                    "supporting_evidence": {"type": "object"},
                    "status": {
                        "type": "string",
                        "enum": [e.value for e in ProposalStatus],
                    },
                    "sample_count": {"type": "integer"},
                    "audit_trail": {"type": "array"},
                },
            },
        },
    }


def ensure_eod_schema_file() -> str:
    """Write eod_schema.json once under data/eod/ if missing or stale-safe overwrite."""
    os.makedirs(_SCHEMA_DIR, exist_ok=True)
    path = os.path.join(_SCHEMA_DIR, "eod_schema.json")
    payload = eod_schema_dict()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    os.replace(tmp, path)
    return path
