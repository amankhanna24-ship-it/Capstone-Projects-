"""
messages.py - the STRUCTURED MESSAGES agents pass to each other.

WHY STRUCTURED MESSAGES?
------------------------
If agents just chatted in free text, the Coordinator would have to guess where
the important bits are. Instead, each agent must fill in a "form" with fixed
boxes. Pydantic is the Python library that defines those forms and checks
they have been filled in correctly.

Analogy: a hospital uses a standard referral form, not a handwritten letter,
so the next doctor always knows where to find the blood pressure reading.

These forms also give us an AUDIT TRAIL. We save every filled-in form to
outputs/*_trace.json, so a reviewer can see exactly what each specialist said.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SpecialistName = Literal["financial_analyst", "risk_assessor", "news_researcher", "compliance_checker"]


class Source(BaseModel):
    """One citation. Every fact in the final note must point to one of these."""
    title: str = Field(description="Short name of the source, e.g. 'Yahoo Finance - NVDA key-statistics'.")
    url: str = Field(description="Link to the source, or 'local://sample-data' for sample data.")


class DispatchPlan(BaseModel):
    """What the Coordinator decides BEFORE any work starts: who does what."""
    query: str
    ticker: str
    specialists: list[SpecialistName]
    focus: list[str] = Field(default_factory=list, description="Themes spotted in the question, e.g. 'earnings', 'risk'.")
    reasoning: str = Field(description="Why these specialists were chosen.")


class SpecialistFinding(BaseModel):
    """What each specialist hands back to the Coordinator."""
    agent: str = Field(description="Which specialist produced this finding.")
    headline: str = Field(description="One-sentence takeaway.")
    key_points: list[str] = Field(description="3-6 bullet points, each with a figure where possible.")
    risks_or_caveats: list[str] = Field(description="What could go wrong, or what the data cannot tell us.")
    confidence: Literal["low", "medium", "high"]
    data_mode: Literal["live", "sample", "mixed"] = Field(description="Whether the tools returned live or sample data.")
    sources: list[Source] = Field(description="Every source used, copied from the tool outputs.")


class CritiqueResult(BaseModel):
    """What the Compliance Checker returns after reviewing a draft."""
    passed: bool = Field(description="True only if there are no blocking issues.")
    blocking_issues: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    rule_check_output: str = Field(description="Short summary of what the check_compliance tool returned.")
