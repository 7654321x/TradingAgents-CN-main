from __future__ import annotations

import math
import re
from typing import Any


CLAIM_FIELDS = (
    "primary_reasons",
    "positive_factors",
    "negative_factors",
    "risk_factors",
    "invalidation_conditions",
    "key_uncertainties",
    "adjustment_reasons",
    "risk_warnings",
    "decision_limitations",
    "required_follow_up",
)


class EvidenceAuditService:
    def audit(self, evidence: dict[str, Any], *outputs: dict[str, Any]) -> dict[str, Any]:
        index = evidence.get("evidence_index", {})
        analysis_date = evidence.get("analysis_date")
        symbol = evidence.get("symbol")
        violations: list[dict[str, Any]] = []
        checked_refs = 0
        checked_claims = 0
        for output_name, output in zip(("trader", "risk"), outputs, strict=False):
            claims_to_check: list[tuple[str, dict[str, Any]]] = []
            for field in CLAIM_FIELDS:
                for item_number, claim in enumerate(output.get(field, []) or []):
                    claims_to_check.append((f"{output_name}.{field}[{item_number}]", claim))
            for scenario, claim in (output.get("position_scenarios") or {}).items():
                if isinstance(claim, dict):
                    claims_to_check.append((f"{output_name}.position_scenarios.{scenario}", {"text": claim.get("reason", ""), "evidence_refs": claim.get("evidence_refs", [])}))
            for path, claim in claims_to_check:
                checked_claims += 1
                if not isinstance(claim, dict) or not claim.get("evidence_refs"):
                    violations.append(self._violation("MISSING_EVIDENCE_REFS", path, str(claim)))
                    continue
                text = str(claim.get("text", ""))
                records = []
                for ref in claim["evidence_refs"]:
                    checked_refs += 1
                    record = index.get(ref)
                    if record is None:
                        violations.append(self._violation("UNKNOWN_EVIDENCE_REF", path, text, ref))
                        continue
                    records.append((ref, record))
                    if record.get("status") != "SUCCESS":
                        violations.append(self._violation("INVALID_EVIDENCE_STATUS", path, text, ref))
                    if record.get("value") is None:
                        violations.append(self._violation("MISSING_EVIDENCE_VALUE", path, text, ref))
                    if record.get("data_cutoff") and analysis_date and record["data_cutoff"] > analysis_date:
                        violations.append(self._violation("FUTURE_EVIDENCE", path, text, ref))
                self._numeric_audit(text, records, path, violations)
                self._semantic_audit(text, [ref for ref, _ in records], evidence, path, violations)
                if symbol and re.search(r"\b\d{6}\.(?:SZ|SS)\b", text):
                    for found in re.findall(r"\b\d{6}\.(?:SZ|SS)\b", text):
                        if found != symbol:
                            violations.append(self._violation("OTHER_SYMBOL_REFERENCE", path, text, found))
        return {
            "status": "PASSED" if not violations else "CONTENT_AUDIT_FAILED",
            "schema_version": "stock_evidence_audit_v1",
            "symbol": symbol,
            "analysis_date": analysis_date,
            "checked_claim_count": checked_claims,
            "checked_evidence_ref_count": checked_refs,
            "violations": violations,
            "rules": [
                "evidence_ref_exists",
                "evidence_status_success",
                "no_future_evidence",
                "numeric_rounding_consistency",
                "percentage_unit_consistency",
                "missing_news_not_neutral",
                "missing_fundamentals_not_positive",
                "adx_not_direction_alone",
            ],
        }

    @staticmethod
    def _violation(rule: str, path: str, snippet: str, evidence_ref: str | None = None) -> dict[str, Any]:
        return {"rule": rule, "field_path": path, "evidence_ref": evidence_ref, "llm_snippet": snippet[:500]}

    def _numeric_audit(self, text, records, path, violations):
        percentages = [float(value) for value in re.findall(r"([-+]?\d+(?:\.\d+)?)\s*%", text)]
        candidates = [float(record["value"]) for _, record in records if record.get("unit") == "percent" and isinstance(record.get("value"), (int, float)) and math.isfinite(float(record["value"]))]
        if percentages and not candidates:
            violations.append(self._violation("PERCENTAGE_UNIT_MISMATCH", path, text))
            return
        for shown in percentages:
            if not any(abs(shown - actual) <= 0.011 for actual in candidates):
                violations.append(self._violation("NUMERIC_VALUE_MISMATCH", path, text))
        decimals = [
            float(match.group(0))
            for match in re.finditer(r"(?<![\d.])[-+]?\d+\.\d+(?![\d.]|\s*%)", text)
        ]
        numeric_candidates = [
            float(record["value"])
            for _, record in records
            if isinstance(record.get("value"), (int, float))
            and math.isfinite(float(record["value"]))
        ]
        for shown in decimals:
            if not any(
                math.isclose(shown, actual, rel_tol=1e-3, abs_tol=5e-4)
                for actual in numeric_candidates
            ):
                violations.append(self._violation("NUMERIC_VALUE_MISMATCH", path, text))

    def _semantic_audit(self, text, refs, evidence, path, violations):
        if "基本面" in text and "fundamentals.status" not in refs:
            violations.append(self._violation("MISSING_FUNDAMENTALS_STATUS_REF", path, text))
        if "新闻" in text and "news.status" not in refs:
            violations.append(self._violation("MISSING_NEWS_STATUS_REF", path, text))
        if evidence.get("news", {}).get("status") == "SUCCESS_NO_DATA" and any(phrase in text for phrase in ("新闻中性", "没有利空", "没有重大事件")):
            violations.append(self._violation("NEWS_NO_DATA_MISINTERPRETED", path, text))
        if evidence.get("fundamentals", {}).get("status") == "FUNDAMENTALS_UNAVAILABLE" and any(phrase in text for phrase in ("基本面稳定", "估值合理", "盈利良好")):
            violations.append(self._violation("FUNDAMENTALS_UNAVAILABLE_MISINTERPRETED", path, text))
        adx_refs = [ref for ref in refs if ref.endswith("adx14")]
        directional_refs = [ref for ref in refs if any(part in ref for part in ("return_", "short_structure", "plus_di14", "minus_di14", "technical_score"))]
        if adx_refs and not directional_refs and any(phrase in text for phrase in ("看涨", "上涨", "多头", "偏强")):
            violations.append(self._violation("ADX_DIRECTION_MISINTERPRETED", path, text, adx_refs[0]))
