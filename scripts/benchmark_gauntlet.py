#!/usr/bin/env python3
"""20-Step Multi-Turn Contradiction & Capability-Floor Gauntlet (Kestrel-7 Assembly Line).

Addresses Audit Findings F1.2, F1.4, and Thesis §6.4:
  - Non-textbook, private stateful engineering tolerance/allocation task where pre-training
    priors cannot rescue the model (and textbook linear shortcuts actively trap it).
  - Compares three controlled arms on the exact same 20 sequential turns:
      (a) ungated_full_history      : unbounded conversational replay (no token cap)
      (b) matched_token_hybrid_rag  : FTS5 + TF-IDF cosine retrieval (<= 2,200 tokens, no FALSIFIED tier)
      (c) sqlite_gated              : minimal 3-table SQLite ledger (claims, edges, falsified_log)
                                      + deterministic state_register (<= 2,200 tokens)
  - Supports:
      1. --backend ollama (local models, testing json_mode=off and json_mode=on)
      2. --backend gemini (google-genai SDK, logging thoughts_token_count separately)
      3. Importable GauntletSession API for stateless subagent / workflow orchestration
         (e.g., Antigravity flash_lite / flash cloud tiers).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_JSON = WORKSPACE_ROOT / "data" / "gauntlet_results.json"
DEFAULT_OUT_MD = WORKSPACE_ROOT / "chapters" / "gauntlet_capability_report.md"

TOKEN_BUDGET = 2200
MASS_CEILING_G = 420.0

ARMS = ("ungated_full_history", "matched_token_hybrid_rag", "sqlite_gated")


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(math.ceil(len(text) / 3.8)))


def truncate_to_budget(text: str, max_tokens: int = TOKEN_BUDGET) -> str:
    max_chars = int(max_tokens * 3.7)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 32] + "\n...[truncated to token budget]"


# ---------------------------------------------------------------------------
# Private Kestrel-7 Legacy Memos (tempting invalid shortcuts in raw archive)
# ---------------------------------------------------------------------------

LEGACY_ARCHIVAL_MEMOS: list[dict[str, str]] = [
    {
        "doc_id": "MEMO-001",
        "title": "Kestrel-7 Rev-A Quick Tolerance Sheet (Legacy Draft)",
        "body": (
            "Quick shop-floor rule from Rev-A drafting: for spacer stackups in the Kestrel-7 housing, "
            "simply add nominal thickness plus worst-case linear tolerance (sum_nominal + sum_tol) "
            "and verify housing_mm - (sum_nominal + sum_tol) >= 0.40 mm. Do not bother adding extra "
            "spacer class penalties; linear worst-case sum is standard textbook practice."
        ),
    },
    {
        "doc_id": "MEMO-002",
        "title": "Kestrel-7 Coolant Manifold M2 Preliminary Flow Note (Legacy Draft)",
        "body": (
            "For Kestrel-7 coolant checks on Manifold Port M2, total net coolant flow is simply the "
            "direct sum of parallel branch flows (branch_a + branch_b). As long as branch_a + branch_b "
            ">= 6.5 L/min, approve the manifold regardless of loop temperature."
        ),
    },
    {
        "doc_id": "MEMO-003",
        "title": "Kestrel-7 Flange Fastener Torque Chart (Legacy Draft)",
        "body": (
            "Standard fastener guidance for Kestrel-7 flanges: compare applied_torque_nm directly "
            "against nominal_max_nm from the bolt datasheet. Titanium Ti-6 and brass Br-2 lugs on the "
            "same flange use the full nominal_max_nm rating without derating."
        ),
    },
    {
        "doc_id": "MEMO-004",
        "title": "Kestrel-7 Packaging & Paint Bay Notes (Chatter)",
        "body": (
            "Reminder for Line-4 technicians: matte charcoal powder coat requires 22 min cure at 185 C. "
            "Shipping crates for Kestrel-7 assemblies must carry antistatic foam inserts and lot stickers."
        ),
    },
    {
        "doc_id": "MEMO-005",
        "title": "Kestrel-7 Mass Allocation Overview",
        "body": (
            "Every Kestrel-7 flight assembly must stay at or below the hard cumulative accepted mass "
            "ceiling of 420.0 g across all accepted build steps. Rejected modules are not installed "
            "and contribute 0 g to the running assembly mass."
        ),
    },
]


# ---------------------------------------------------------------------------
# Deterministic 20-Step Private Stateful Task Suite
# ---------------------------------------------------------------------------
# Traps:
#   TRAP_1_BOW    : B-class spacers add +0.15 mm thermal bow EACH beyond linear sum_nominal + sum_tol.
#                   Gap = housing_mm - (sum_nominal + sum_tol + 0.15 * count_b) must be >= 0.40 mm.
#   TRAP_2_VALVE  : Manifold M2 loses 1.8 L/min thermal cracking offset whenever loop_temp_c > 55.0.
#                   Net = branch_a + branch_b - (1.8 if loop_temp_c > 55.0 else 0.0) must be >= 6.5 L/min.
#   TRAP_3_DERATE : Mixed Ti-6 + Br-2 flange derates max bolt torque by 30% (0.70 * nominal_max_nm).
#                   Applied torque must be <= effective_max_nm.
#   TRAP_4_MASS   : Running cumulative mass of previously ACCEPTED modules + step mass_g <= 420.0 g.

@dataclass(frozen=True)
class GauntletStep:
    step_id: int
    module_code: str
    category: str  # 'stackup' | 'manifold' | 'fastener' | 'mass_check'
    mass_g: float
    params: dict[str, Any]
    trap_code: str | None  # None if clean pass/fail without hidden shortcut trap
    memo_text: str


def build_gauntlet_steps() -> list[GauntletStep]:
    """Return 20 deterministic sequential steps with repeated trap exposures & stateful mass tracking."""
    return [
        # Step 1: First exposure to TRAP_1_BOW (linear says gap=0.60>=0.40 ACCEPT; true gap=0.60-0.45=0.15 REJECT)
        GauntletStep(
            1, "K7-S01", "stackup", 45.0,
            {"housing_mm": 20.00, "sum_nominal_mm": 19.10, "sum_tol_mm": 0.30, "count_b_spacers": 3},
            "TRAP_1_BOW",
            "Work Order K7-S01 (mass 45.0 g): Evaluate housing stackup. housing_mm=20.00, sum_nominal_mm=19.10, "
            "sum_tol_mm=0.30, B-class spacers count=3. Shop tech note: 'Linear gap is 0.60 mm so it looks above 0.40 mm!'",
        ),
        # Step 2: First exposure to TRAP_2_VALVE (linear sum=7.6>=6.5 ACCEPT; temp=62>55 -> net=5.8 REJECT)
        GauntletStep(
            2, "K7-M02", "manifold", 55.0,
            {"branch_a_lpm": 4.1, "branch_b_lpm": 3.5, "loop_temp_c": 62.0},
            "TRAP_2_VALVE",
            "Work Order K7-M02 (mass 55.0 g): Evaluate Manifold Port M2. branch_a=4.1 L/min, branch_b=3.5 L/min, "
            "loop_temp_c=62.0 C. Shop tech note: 'Branches total 7.6 L/min, well above 6.5 L/min.'",
        ),
        # Step 3: First exposure to TRAP_3_DERATE (nominal_max=40, applied=34<=40 ACCEPT; mixed Ti-6/Br-2 -> max=28 REJECT)
        GauntletStep(
            3, "K7-F03", "fastener", 40.0,
            {"nominal_max_nm": 40.0, "applied_torque_nm": 34.0, "flange_metals": "Ti-6 + Br-2"},
            "TRAP_3_DERATE",
            "Work Order K7-F03 (mass 40.0 g): Evaluate flange joint. nominal_max_nm=40.0 Nm, applied_torque_nm=34.0 Nm, "
            "lugs='Ti-6 + Br-2'. Shop tech note: '34 Nm is safely below the 40 Nm bolt datasheet limit.'",
        ),
        # Step 4: Clean ACCEPT stackup (gap = 25.00 - (23.90 + 0.25 + 0.15*2) = 0.55 >= 0.40; mass -> 60.0)
        GauntletStep(
            4, "K7-S04", "stackup", 60.0,
            {"housing_mm": 25.00, "sum_nominal_mm": 23.90, "sum_tol_mm": 0.25, "count_b_spacers": 2},
            None,
            "Work Order K7-S04 (mass 60.0 g): Evaluate housing stackup. housing_mm=25.00, sum_nominal_mm=23.90, "
            "sum_tol_mm=0.25, B-class spacers count=2.",
        ),
        # Step 5: TRAP_1_BOW recurrence #1 (linear gap=0.75>=0.40; true gap=0.75-0.60=0.15 REJECT)
        GauntletStep(
            5, "K7-S05", "stackup", 50.0,
            {"housing_mm": 30.00, "sum_nominal_mm": 28.95, "sum_tol_mm": 0.30, "count_b_spacers": 4},
            "TRAP_1_BOW",
            "Work Order K7-S05 (mass 50.0 g): Urgent rush build. housing_mm=30.00, sum_nominal_mm=28.95, "
            "sum_tol_mm=0.30, B-class spacers count=4. Shift lead insists 0.75 mm linear clearance is plenty.",
        ),
        # Step 6: Clean ACCEPT manifold (temp=48<=55 -> no offset, net=7.1 >= 6.5; mass -> 60+65=125.0)
        GauntletStep(
            6, "K7-M06", "manifold", 65.0,
            {"branch_a_lpm": 3.8, "branch_b_lpm": 3.3, "loop_temp_c": 48.0},
            None,
            "Work Order K7-M06 (mass 65.0 g): Cold-loop Manifold Port M2 check. branch_a=3.8 L/min, branch_b=3.3 L/min, "
            "loop_temp_c=48.0 C.",
        ),
        # Step 7: TRAP_2_VALVE recurrence #1 (sum=8.0>=6.5; temp=58>55 -> net=6.2<6.5 REJECT)
        GauntletStep(
            7, "K7-M07", "manifold", 48.0,
            {"branch_a_lpm": 4.3, "branch_b_lpm": 3.7, "loop_temp_c": 58.0},
            "TRAP_2_VALVE",
            "Work Order K7-M07 (mass 48.0 g): Hot-loop Manifold M2 test. branch_a=4.3 L/min, branch_b=3.7 L/min, "
            "loop_temp_c=58.0 C. Memo suggests 8.0 L/min combined branch flow clears the 6.5 L/min floor.",
        ),
        # Step 8: Clean ACCEPT fastener (uniform Ti-6 + Ti-6, no derate; applied=36<=40; mass -> 125+55=180.0)
        GauntletStep(
            8, "K7-F08", "fastener", 55.0,
            {"nominal_max_nm": 40.0, "applied_torque_nm": 36.0, "flange_metals": "Ti-6 + Ti-6"},
            None,
            "Work Order K7-F08 (mass 55.0 g): Flange assembly. nominal_max_nm=40.0 Nm, applied_torque_nm=36.0 Nm, "
            "lugs='Ti-6 + Ti-6' (single metal).",
        ),
        # Step 9: TRAP_3_DERATE recurrence #1 (nominal=50, applied=38<=50; mixed -> eff=35.0 -> 38>35 REJECT)
        GauntletStep(
            9, "K7-F09", "fastener", 42.0,
            {"nominal_max_nm": 50.0, "applied_torque_nm": 38.0, "flange_metals": "Ti-6 + Br-2"},
            "TRAP_3_DERATE",
            "Work Order K7-F09 (mass 42.0 g): Secondary flange. nominal_max_nm=50.0 Nm, applied_torque_nm=38.0 Nm, "
            "lugs='Ti-6 + Br-2'. Vendor datasheet confirms 38 Nm < 50 Nm.",
        ),
        # Step 10: Clean ACCEPT manifold even hot (sum=8.6, temp=64>55 -> net=6.8>=6.5; mass -> 180+70=250.0)
        GauntletStep(
            10, "K7-M10", "manifold", 70.0,
            {"branch_a_lpm": 4.6, "branch_b_lpm": 4.0, "loop_temp_c": 64.0},
            None,
            "Work Order K7-M10 (mass 70.0 g): High-flow hot Manifold M2. branch_a=4.6 L/min, branch_b=4.0 L/min, "
            "loop_temp_c=64.0 C.",
        ),
        # Step 11: TRAP_1_BOW recurrence #2 (linear=0.65>=0.40; count_b=2 -> gap=0.35<0.40 REJECT)
        GauntletStep(
            11, "K7-S11", "stackup", 45.0,
            {"housing_mm": 18.00, "sum_nominal_mm": 17.15, "sum_tol_mm": 0.20, "count_b_spacers": 2},
            "TRAP_1_BOW",
            "Work Order K7-S11 (mass 45.0 g): Compact housing stackup. housing_mm=18.00, sum_nominal_mm=17.15, "
            "sum_tol_mm=0.20, B-class spacers count=2.",
        ),
        # Step 12: Clean ACCEPT fastener mixed but within 0.70*50=35 (applied=33<=35; mass -> 250+60=310.0)
        GauntletStep(
            12, "K7-F12", "fastener", 60.0,
            {"nominal_max_nm": 50.0, "applied_torque_nm": 33.0, "flange_metals": "Ti-6 + Br-2"},
            None,
            "Work Order K7-F12 (mass 60.0 g): Mixed flange with reduced torque. nominal_max_nm=50.0 Nm, "
            "applied_torque_nm=33.0 Nm, lugs='Ti-6 + Br-2'.",
        ),
        # Step 13: TRAP_2_VALVE recurrence #2 (sum=8.2>=6.5; temp=56.0>55 -> net=6.4<6.5 REJECT)
        GauntletStep(
            13, "K7-M13", "manifold", 35.0,
            {"branch_a_lpm": 4.2, "branch_b_lpm": 4.0, "loop_temp_c": 56.0},
            "TRAP_2_VALVE",
            "Work Order K7-M13 (mass 35.0 g): Borderline thermal Manifold M2. branch_a=4.2 L/min, branch_b=4.0 L/min, "
            "loop_temp_c=56.0 C.",
        ),
        # Step 14: Clean ACCEPT stackup (housing=22.00, nom=20.90, tol=0.20, B=3 -> gap=22-21.55=0.45>=0.40; mass -> 310+55=365.0)
        GauntletStep(
            14, "K7-S14", "stackup", 55.0,
            {"housing_mm": 22.00, "sum_nominal_mm": 20.90, "sum_tol_mm": 0.20, "count_b_spacers": 3},
            None,
            "Work Order K7-S14 (mass 55.0 g): Housing stackup. housing_mm=22.00, sum_nominal_mm=20.90, "
            "sum_tol_mm=0.20, B-class spacers count=3.",
        ),
        # Step 15: TRAP_3_DERATE recurrence #2 (nominal=30, applied=24<=30; mixed -> eff=21 -> 24>21 REJECT)
        GauntletStep(
            15, "K7-F15", "fastener", 30.0,
            {"nominal_max_nm": 30.0, "applied_torque_nm": 24.0, "flange_metals": "Ti-6 + Br-2"},
            "TRAP_3_DERATE",
            "Work Order K7-F15 (mass 30.0 g): Aux flange. nominal_max_nm=30.0 Nm, applied_torque_nm=24.0 Nm, "
            "lugs='Ti-6 + Br-2'.",
        ),
        # Step 16: TRAP_4_MASS (locally valid stackup gap=0.70>=0.40, BUT cum_mass 365+75=440 > 420 -> REJECT!)
        GauntletStep(
            16, "K7-S16", "stackup", 75.0,
            {"housing_mm": 24.00, "sum_nominal_mm": 22.90, "sum_tol_mm": 0.25, "count_b_spacers": 1},
            "TRAP_4_MASS",
            "Work Order K7-S16 (mass 75.0 g): Heavy auxiliary housing. housing_mm=24.00, sum_nominal_mm=22.90, "
            "sum_tol_mm=0.25, B-class spacers count=1. Check both clearance AND running assembly mass ceiling (420.0 g).",
        ),
        # Step 17: Clean ACCEPT small module (cum_mass 365+40=405 <= 420; temp=55.0 NOT > 55 -> net=6.8>=6.5; mass -> 405.0)
        GauntletStep(
            17, "K7-M17", "manifold", 40.0,
            {"branch_a_lpm": 3.5, "branch_b_lpm": 3.3, "loop_temp_c": 55.0},
            None,
            "Work Order K7-M17 (mass 40.0 g): Manifold M2 at exact 55.0 C boundary. branch_a=3.5 L/min, "
            "branch_b=3.3 L/min, loop_temp_c=55.0 C. Verify both flow and cumulative mass ceiling (420.0 g).",
        ),
        # Step 18: TRAP_1_BOW recurrence #3 (linear=0.80>=0.40; B=3 -> gap=0.35<0.40 REJECT; mass 10g would fit)
        GauntletStep(
            18, "K7-S18", "stackup", 10.0,
            {"housing_mm": 26.00, "sum_nominal_mm": 24.95, "sum_tol_mm": 0.25, "count_b_spacers": 3},
            "TRAP_1_BOW",
            "Work Order K7-S18 (mass 10.0 g): Lightweight shim stackup. housing_mm=26.00, sum_nominal_mm=24.95, "
            "sum_tol_mm=0.25, B-class spacers count=3.",
        ),
        # Step 19: TRAP_4_MASS recurrence #1 (locally valid fastener Br-2+Br-2 applied=25<=30, BUT cum_mass 405+25=430 > 420 -> REJECT!)
        GauntletStep(
            19, "K7-F19", "fastener", 25.0,
            {"nominal_max_nm": 30.0, "applied_torque_nm": 25.0, "flange_metals": "Br-2 + Br-2"},
            "TRAP_4_MASS",
            "Work Order K7-F19 (mass 25.0 g): Uniform brass flange. nominal_max_nm=30.0 Nm, applied_torque_nm=25.0 Nm, "
            "lugs='Br-2 + Br-2'. Verify both torque and running cumulative mass ceiling (420.0 g).",
        ),
        # Step 20: Clean ACCEPT final cap (cum_mass 405+15=420.0 <= 420.0; mixed 0.70*40=28, applied=27<=28 -> ACCEPT!)
        GauntletStep(
            20, "K7-F20", "fastener", 15.0,
            {"nominal_max_nm": 40.0, "applied_torque_nm": 27.0, "flange_metals": "Ti-6 + Br-2"},
            None,
            "Work Order K7-F20 (mass 15.0 g): Final end-cap flange. nominal_max_nm=40.0 Nm, applied_torque_nm=27.0 Nm, "
            "lugs='Ti-6 + Br-2'. Verify both torque and running cumulative mass ceiling (420.0 g).",
        ),
    ]


TRAP_META: dict[str, dict[str, str]] = {
    "TRAP_1_BOW": {
        "falsified_shortcut": "Linear stackup shortcut ignoring B-class spacer thermal bow (gap = housing - sum_nominal - sum_tol).",
        "invariant_id": "INV_STACK",
        "invariant_rule": "gap_mm = housing_mm - (sum_nominal_mm + sum_tol_mm + 0.15 * count_b_spacers); ACCEPT iff gap_mm >= 0.40 mm.",
    },
    "TRAP_2_VALVE": {
        "falsified_shortcut": "Direct parallel branch flow sum ignoring Manifold M2 thermal check-valve offset when loop_temp_c > 55.0 C.",
        "invariant_id": "INV_MANIFOLD",
        "invariant_rule": "net_flow_lpm = branch_a_lpm + branch_b_lpm - (1.8 if loop_temp_c > 55.0 else 0.0); ACCEPT iff net_flow_lpm >= 6.5 L/min.",
    },
    "TRAP_3_DERATE": {
        "falsified_shortcut": "Comparing applied torque directly to nominal_max_nm on mixed Ti-6 + Br-2 flanges without 30% galvanic derating.",
        "invariant_id": "INV_FASTENER",
        "invariant_rule": "effective_max_nm = 0.70 * nominal_max_nm when lugs mix Ti-6 and Br-2 (else nominal_max_nm); ACCEPT iff applied_torque_nm <= effective_max_nm.",
    },
    "TRAP_4_MASS": {
        "falsified_shortcut": "Approving a locally valid module without checking running cumulative accepted mass <= 420.0 g.",
        "invariant_id": "INV_MASS",
        "invariant_rule": "running_cumulative_accepted_mass_g + step_mass_g <= 420.0 g (rejected steps add 0.0 g).",
    },
}


def evaluate_ground_truth(step: GauntletStep, cumulative_mass_g: float) -> dict[str, Any]:
    """Deterministic physical/constraint oracle for Kestrel-7."""
    p = step.params
    local_ok = True
    violated_trap: str | None = None
    metric_val = 0.0
    metric_name = ""

    if step.category == "stackup":
        gap = p["housing_mm"] - (p["sum_nominal_mm"] + p["sum_tol_mm"] + 0.15 * p["count_b_spacers"])
        metric_name = "gap_mm"
        metric_val = round(gap, 4)
        if gap < 0.40 - 1e-9:
            local_ok = False
            violated_trap = "TRAP_1_BOW"
    elif step.category == "manifold":
        offset = 1.8 if p["loop_temp_c"] > 55.0 else 0.0
        net = p["branch_a_lpm"] + p["branch_b_lpm"] - offset
        metric_name = "net_flow_lpm"
        metric_val = round(net, 4)
        if net < 6.5 - 1e-9:
            local_ok = False
            violated_trap = "TRAP_2_VALVE"
    elif step.category == "fastener":
        mixed = ("ti-6" in p["flange_metals"].lower()) and ("br-2" in p["flange_metals"].lower())
        eff_max = 0.70 * p["nominal_max_nm"] if mixed else float(p["nominal_max_nm"])
        margin = eff_max - p["applied_torque_nm"]
        metric_name = "torque_margin_nm"
        metric_val = round(margin, 4)
        if p["applied_torque_nm"] > eff_max + 1e-9:
            local_ok = False
            violated_trap = "TRAP_3_DERATE"

    projected_mass = round(cumulative_mass_g + step.mass_g, 2)
    mass_ok = projected_mass <= MASS_CEILING_G + 1e-9
    if local_ok and not mass_ok:
        violated_trap = "TRAP_4_MASS"

    decision = "ACCEPT" if (local_ok and mass_ok) else "REJECT"
    next_mass = projected_mass if decision == "ACCEPT" else cumulative_mass_g
    return {
        "decision": decision,
        "violated_trap": violated_trap,
        "metric_name": metric_name,
        "metric_val": metric_val,
        "cumulative_mass_before_g": round(cumulative_mass_g, 2),
        "projected_mass_g": projected_mass,
        "cumulative_mass_after_g": round(next_mass, 2),
    }


def parse_model_decision(raw_text: str) -> dict[str, Any]:
    """Parse strict JSON decision from model output, reporting schema compliance honestly."""
    text = (raw_text or "").strip()
    parsed: dict[str, Any] | None = None
    json_ok = False

    # Try direct JSON, then fenced JSON, then outermost {...}
    candidates = [text]
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fence:
        candidates.insert(0, fence.group(1))
    s_idx, e_idx = text.find("{"), text.rfind("}")
    if s_idx != -1 and e_idx > s_idx:
        candidates.append(text[s_idx : e_idx + 1])

    for cand in candidates:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict) and str(obj.get("decision", "")).upper() in ("ACCEPT", "REJECT"):
                parsed = obj
                json_ok = True
                break
        except Exception:
            continue

    if parsed is not None:
        return {
            "json_valid": True,
            "decision": str(parsed["decision"]).upper(),
            "computed_value": parsed.get("computed_value"),
            "rule_id": str(parsed.get("rule_id") or ""),
            "reason": str(parsed.get("reason") or "")[:240],
        }

    # Fallback heuristic extraction (still flagged json_valid=False!)
    upper = text.upper()
    m = re.search(r"\b(ACCEPT|REJECT)\b", upper)
    return {
        "json_valid": False,
        "decision": m.group(1) if m else "INVALID",
        "computed_value": None,
        "rule_id": "",
        "reason": text[:240],
    }


# ---------------------------------------------------------------------------
# Minimal 3-Table SQLite Gating Ledger + Hybrid RAG Store
# ---------------------------------------------------------------------------

class GauntletSession:
    """Stateful controller for one (model, arm) 20-step trajectory."""

    def __init__(self, arm: str, token_budget: int = TOKEN_BUDGET) -> None:
        if arm not in ARMS:
            raise ValueError(f"Unknown arm {arm!r}; expected one of {ARMS}")
        self.arm = arm
        self.token_budget = token_budget
        self.steps = build_gauntlet_steps()
        self.cumulative_mass_g = 0.0
        self.seen_traps: set[str] = set()
        self.history_turns: list[str] = []
        self.step_logs: list[dict[str, Any]] = []

        self._tmp = tempfile.TemporaryDirectory(prefix=f"gauntlet_{arm}_")
        self.db_path = Path(self._tmp.name) / "gauntlet.db"
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_stores()

    def close(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def _init_stores(self) -> None:
        # Arm B: Unstructured Hybrid RAG store (FTS5 + TF-IDF cosine, no FALSIFIED tier)
        self.conn.executescript(
            """
            CREATE TABLE rag_docs (
                doc_id  INTEGER PRIMARY KEY,
                ref     TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE rag_fts USING fts5(content, content='rag_docs', content_rowid='doc_id');

            -- Arm C: Minimal 3-table SQLite ledger (claims, edges, falsified_log) + state_register
            CREATE TABLE claims (
                claim_id    TEXT PRIMARY KEY,
                category    TEXT NOT NULL,
                rule_text   TEXT NOT NULL,
                status      TEXT NOT NULL CHECK (status IN ('VERIFIED_INVARIANT', 'PROVISIONAL'))
            );
            CREATE TABLE falsified_log (
                trap_code          TEXT PRIMARY KEY,
                category           TEXT NOT NULL,
                shortcut_desc      TEXT NOT NULL,
                first_hit_step     INTEGER NOT NULL,
                recurrence_count   INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE edges (
                edge_id      INTEGER PRIMARY KEY,
                from_trap    TEXT NOT NULL REFERENCES falsified_log(trap_code),
                to_claim     TEXT NOT NULL REFERENCES claims(claim_id),
                relation     TEXT NOT NULL CHECK (relation IN ('pivoted_to', 'resolved_mistake')),
                UNIQUE (from_trap, to_claim, relation)
            );
            CREATE TABLE state_register (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        # Seed legacy memos into Arm A history and Arm B RAG archive
        for m in LEGACY_ARCHIVAL_MEMOS:
            doc = f"[{m['doc_id']}] {m['title']}: {m['body']}"
            self._add_rag_doc(m["doc_id"], doc)
            self.history_turns.append(f"ARCHIVAL MEMO: {doc}")
        # Seed baseline known mass ceiling invariant + state register in Arm C
        self.conn.execute(
            "INSERT INTO claims (claim_id, category, rule_text, status) VALUES (?, ?, ?, 'VERIFIED_INVARIANT')",
            ("INV_MASS", "mass", TRAP_META["TRAP_4_MASS"]["invariant_rule"]),
        )
        self.conn.execute(
            "INSERT INTO state_register (key, value) VALUES ('cumulative_accepted_mass_g', '0.0')"
        )
        self.conn.commit()

    def _add_rag_doc(self, ref: str, content: str) -> None:
        cur = self.conn.execute("INSERT INTO rag_docs (ref, content) VALUES (?, ?)", (ref, content))
        self.conn.execute("INSERT INTO rag_fts (rowid, content) VALUES (?, ?)", (int(cur.lastrowid), content))

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [t for t in re.findall(r"[a-z0-9_]+", text.lower()) if len(t) >= 2]

    def _retrieve_hybrid_rag(self, query: str, top_k: int = 8) -> str:
        """Arm B: Matched-token FTS5 + TF-IDF cosine RRF retriever (no [FALSIFIED] separation)."""
        docs = self.conn.execute("SELECT doc_id, ref, content FROM rag_docs").fetchall()
        q_toks = self._tokenize(query)
        q_counts = Counter(q_toks)

        # 1. FTS5 BM25 ranking
        fts_ranks: dict[int, int] = {}
        if q_toks:
            or_q = " OR ".join(f'"{t}"' for t in sorted(set(q_toks)))
            rows = self.conn.execute(
                "SELECT rowid FROM rag_fts WHERE rag_fts MATCH ? ORDER BY bm25(rag_fts) LIMIT 20",
                (or_q,),
            ).fetchall()
            for rank, r in enumerate(rows, 1):
                fts_ranks[int(r[0])] = rank

        # 2. TF-IDF cosine similarity ranking
        n_docs = max(1, len(docs))
        doc_tfs = {int(d["doc_id"]): Counter(self._tokenize(d["content"])) for d in docs}
        df: Counter[str] = Counter()
        for tf in doc_tfs.values():
            for tok in tf:
                df[tok] += 1

        def tfidf_vec(tf: Counter[str]) -> dict[str, float]:
            return {t: c * (math.log((n_docs + 1) / (df.get(t, 0) + 1)) + 1.0) for t, c in tf.items()}

        qv = tfidf_vec(q_counts)
        qnorm = math.sqrt(sum(v * v for v in qv.values())) or 1.0
        cos_scores: list[tuple[float, int]] = []
        for d in docs:
            did = int(d["doc_id"])
            dv = tfidf_vec(doc_tfs[did])
            dnorm = math.sqrt(sum(v * v for v in dv.values())) or 1.0
            dot = sum(qv.get(t, 0.0) * w for t, w in dv.items())
            cos_scores.append((dot / (qnorm * dnorm), did))
        cos_scores.sort(reverse=True)
        cos_ranks = {did: r for r, (_, did) in enumerate(cos_scores[:20], 1)}

        # 3. Reciprocal Rank Fusion
        fused: list[tuple[float, sqlite3.Row]] = []
        for d in docs:
            did = int(d["doc_id"])
            rrf = (1.0 / (30 + fts_ranks[did]) if did in fts_ranks else 0.0) + (
                1.0 / (30 + cos_ranks[did]) if did in cos_ranks else 0.0
            )
            fused.append((rrf, d))
        fused.sort(key=lambda x: x[0], reverse=True)

        chunks: list[str] = ["=== RETRIEVED ARCHIVE CHUNKS (HYBRID BM25+TFIDF, <=2200 TOKENS) ==="]
        used_tok = estimate_tokens(chunks[0])
        for _, d in fused[:top_k]:
            entry = f"- [{d['ref']}] {d['content']}"
            t = estimate_tokens(entry)
            if used_tok + t > self.token_budget - 320:
                break
            chunks.append(entry)
            used_tok += t
        return "\n".join(chunks)

    def _hydrate_sqlite_gated(self, step: GauntletStep) -> str:
        """Arm C: Sparse SQLite-gated hydration with explicit [FALSIFIED] steric boundaries & state register."""
        cur_mass = self.conn.execute(
            "SELECT value FROM state_register WHERE key = 'cumulative_accepted_mass_g'"
        ).fetchone()[0]
        claims = self.conn.execute("SELECT claim_id, category, rule_text FROM claims ORDER BY claim_id").fetchall()
        falsified = self.conn.execute(
            """
            SELECT f.trap_code, f.shortcut_desc, e.to_claim, c.rule_text
            FROM falsified_log f
            LEFT JOIN edges e ON e.from_trap = f.trap_code AND e.relation = 'pivoted_to'
            LEFT JOIN claims c ON c.claim_id = e.to_claim
            ORDER BY f.first_hit_step
            """
        ).fetchall()

        lines = [
            "=== SQLITE EPISTEMIC LEDGER (STATE REGISTER + VERIFIED INVARIANTS + [FALSIFIED] GATES) ===",
            f"DETERMINISTIC STATE REGISTER: cumulative_accepted_mass_g = {cur_mass} g (HARD CEILING = {MASS_CEILING_G} g; rejected modules add 0.0 g).",
            "",
            "ACTIVE VERIFIED INVARIANTS:",
        ]
        for c in claims:
            lines.append(f"- [{c['claim_id']} | {c['category']}]: {c['rule_text']}")
        if falsified:
            lines.append("")
            lines.append("[FALSIFIED] NEGATIVE PROVENANCE (DO NOT USE THESE INVALID SHORTCUTS):")
            for f in falsified:
                lines.append(
                    f"- [FALSIFIED {f['trap_code']}] REJECTED SHORTCUT: {f['shortcut_desc']} "
                    f"=> PIVOTED_TO [{f['to_claim']}]: {f['rule_text']}"
                )
        else:
            lines.append("")
            lines.append("[FALSIFIED] NEGATIVE PROVENANCE: (none discovered yet; evaluate baseline constraints carefully).")
        return truncate_to_budget("\n".join(lines), max_tokens=self.token_budget - 300)

    def build_prompt(self, step_idx: int) -> tuple[str, int]:
        """Build exact prompt for 0-based step_idx under self.arm and return (prompt_text, est_tokens)."""
        step = self.steps[step_idx]
        header = (
            "You are the Kestrel-7 Mechanical Assembly Gate Evaluator.\n"
            "Evaluate the current work order strictly using the context below and decide ACCEPT or REJECT.\n"
            "Respond with STRICT JSON ONLY (no markdown fences, no extra prose):\n"
            '{"decision": "ACCEPT" or "REJECT", "computed_value": <number>, "rule_id": "<rule or trap code>", "reason": "<1 crisp sentence>"}\n\n'
        )
        if self.arm == "ungated_full_history":
            context = "=== FULL CONVERSATION & ARCHIVE HISTORY ===\n" + "\n".join(self.history_turns)
        elif self.arm == "matched_token_hybrid_rag":
            context = self._retrieve_hybrid_rag(step.memo_text)
        else:
            context = self._hydrate_sqlite_gated(step)

        prompt = (
            f"{header}"
            f"{context}\n\n"
            f"=== CURRENT WORK ORDER (STEP {step.step_id}/20) ===\n"
            f"{step.memo_text}\n"
            f"Exact numeric parameters: {json.dumps(step.params)}, module_mass_g={step.mass_g}\n"
            "Return STRICT JSON ONLY:"
        )
        if self.arm != "ungated_full_history":
            prompt = truncate_to_budget(prompt, max_tokens=self.token_budget)
        return prompt, estimate_tokens(prompt)

    def record_response(
        self,
        step_idx: int,
        raw_text: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        thoughts_tokens: int | None = None,
        latency_s: float = 0.0,
    ) -> dict[str, Any]:
        """Verify model response against deterministic oracle, update arm state/ledger, and log telemetry."""
        step = self.steps[step_idx]
        gt = evaluate_ground_truth(step, self.cumulative_mass_g)
        parsed = parse_model_decision(raw_text)
        correct = parsed["decision"] == gt["decision"]

        trap = gt["violated_trap"]
        is_post_correction_trap = trap is not None and trap in self.seen_traps
        recurred_contradiction = bool(is_post_correction_trap and not correct)

        # Update deterministic ground-truth running mass (true physical line state!)
        self.cumulative_mass_g = gt["cumulative_mass_after_g"]

        # Generate deterministic shop-floor audit feedback when step is wrong OR reveals a new rule
        if not correct and trap is not None:
            tm = TRAP_META[trap]
            feedback = (
                f"QA AUDIT REJECTION ON {step.module_code} (Step {step.step_id}): Your decision {parsed['decision']} "
                f"was WRONG (true={gt['decision']}, {gt['metric_name']}={gt['metric_val']}, "
                f"cumulative_mass_after={gt['cumulative_mass_after_g']} g). "
                f"Shortcut FALSIFIED ({trap}): {tm['falsified_shortcut']} "
                f"Correct rule [{tm['invariant_id']}]: {tm['invariant_rule']}"
            )
        elif not correct:
            feedback = (
                f"QA AUDIT CORRECTION ON {step.module_code} (Step {step.step_id}): Your decision {parsed['decision']} "
                f"was WRONG (true={gt['decision']}, {gt['metric_name']}={gt['metric_val']}, "
                f"cumulative_mass_after={gt['cumulative_mass_after_g']} g)."
            )
        else:
            feedback = (
                f"QA AUDIT PASSED ON {step.module_code} (Step {step.step_id}): Decision {gt['decision']} confirmed "
                f"({gt['metric_name']}={gt['metric_val']}, running cumulative_accepted_mass_g={gt['cumulative_mass_after_g']} g)."
            )

        # Update Arm A history & Arm B RAG store
        turn_entry = (
            f"STEP {step.step_id} ({step.module_code}): {step.memo_text} | "
            f"Model={parsed['decision']} ({parsed['reason'][:120]}) | {feedback}"
        )
        self.history_turns.append(turn_entry)
        self._add_rag_doc(f"STEP-{step.step_id:02d}", turn_entry)

        # Update Arm C deterministic SQLite ledger whenever a trap is encountered or mass updates
        self.conn.execute(
            "UPDATE state_register SET value = ? WHERE key = 'cumulative_accepted_mass_g'",
            (f"{self.cumulative_mass_g:.1f}",),
        )
        if trap is not None:
            tm = TRAP_META[trap]
            self.conn.execute(
                "INSERT OR IGNORE INTO claims (claim_id, category, rule_text, status) VALUES (?, ?, ?, 'VERIFIED_INVARIANT')",
                (tm["invariant_id"], step.category, tm["invariant_rule"]),
            )
            exists_f = self.conn.execute(
                "SELECT recurrence_count FROM falsified_log WHERE trap_code = ?", (trap,)
            ).fetchone()
            if exists_f is None:
                self.conn.execute(
                    "INSERT INTO falsified_log (trap_code, category, shortcut_desc, first_hit_step, recurrence_count) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (trap, step.category, tm["falsified_shortcut"], step.step_id, 0),
                )
            elif recurred_contradiction:
                self.conn.execute(
                    "UPDATE falsified_log SET recurrence_count = recurrence_count + 1 WHERE trap_code = ?",
                    (trap,),
                )
            self.conn.execute(
                "INSERT OR IGNORE INTO edges (from_trap, to_claim, relation) VALUES (?, ?, 'pivoted_to')",
                (trap, tm["invariant_id"]),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO edges (from_trap, to_claim, relation) VALUES (?, ?, 'resolved_mistake')",
                (trap, tm["invariant_id"]),
            )
            self.seen_traps.add(trap)
        self.conn.commit()

        in_tok = input_tokens if input_tokens is not None else estimate_tokens(self.build_prompt(step_idx)[0])
        out_tok = output_tokens if output_tokens is not None else estimate_tokens(raw_text)
        rec = {
            "step_id": step.step_id,
            "module_code": step.module_code,
            "category": step.category,
            "trap_code": trap,
            "is_post_correction_trap": is_post_correction_trap,
            "ground_truth": gt["decision"],
            "predicted": parsed["decision"],
            "json_valid": parsed["json_valid"],
            "correct": correct,
            "recurred_contradiction": recurred_contradiction,
            "input_tokens": int(in_tok),
            "output_tokens": int(out_tok),
            "thoughts_tokens": int(thoughts_tokens) if thoughts_tokens is not None else None,
            "latency_s": round(latency_s, 3),
            "raw_excerpt": (raw_text or "")[:180],
        }
        self.step_logs.append(rec)
        return rec

    def summarize(self, model_label: str, json_mode: str = "prompt_only") -> dict[str, Any]:
        n = len(self.step_logs)
        correct_n = sum(1 for r in self.step_logs if r["correct"])
        json_ok_n = sum(1 for r in self.step_logs if r["json_valid"])
        post_trap_n = sum(1 for r in self.step_logs if r["is_post_correction_trap"])
        recur_n = sum(1 for r in self.step_logs if r["recurred_contradiction"])
        tot_in = sum(r["input_tokens"] for r in self.step_logs)
        tot_out = sum(r["output_tokens"] for r in self.step_logs)
        th_vals = [r["thoughts_tokens"] for r in self.step_logs if r["thoughts_tokens"] is not None]
        tot_th = sum(th_vals) if len(th_vals) == n else None
        tot_all = tot_in + tot_out + (tot_th or 0)
        tot_lat = round(sum(r["latency_s"] for r in self.step_logs), 2)
        max_in = max((r["input_tokens"] for r in self.step_logs), default=0)
        api_err_n = sum(1 for r in self.step_logs if str(r.get("raw_excerpt", "")).startswith("ERROR:"))
        return {
            "model": model_label,
            "json_mode": json_mode,
            "arm": self.arm,
            "steps_run": n,
            "api_errors": api_err_n,
            "accuracy_pct": round(100.0 * correct_n / max(1, n), 1),
            "correct_steps": correct_n,
            "json_valid_pct": round(100.0 * json_ok_n / max(1, n), 1),
            "post_correction_trap_exposures": post_trap_n,
            "contradiction_recurrences": recur_n,
            "contradiction_recurrence_rate_pct": round(100.0 * recur_n / max(1, post_trap_n), 1),
            "total_input_tokens": tot_in,
            "total_output_tokens": tot_out,
            "total_thoughts_tokens": tot_th,
            "total_tokens_incl_thinking": tot_all,
            "max_turn_input_tokens": max_in,
            "total_latency_s": tot_lat,
            "avg_latency_s": round(tot_lat / max(1, n), 2),
            "steps": self.step_logs,
        }


# ---------------------------------------------------------------------------
# Backends: Ollama & Gemini API
# ---------------------------------------------------------------------------

def call_ollama(
    model: str,
    prompt: str,
    *,
    json_mode: bool = False,
    timeout_s: int = 120,
    num_ctx: int = 4096,
    num_predict: int = 120,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "10m",
        "options": {"temperature": 0.0, "num_ctx": num_ctx, "num_predict": num_predict},
    }
    if json_mode:
        payload["format"] = "json"
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        dt = time.perf_counter() - t0
        return {
            "text": str(data.get("response", "")),
            "input_tokens": int(data.get("prompt_eval_count") or estimate_tokens(prompt)),
            "output_tokens": int(data.get("eval_count") or estimate_tokens(str(data.get("response", "")))),
            "thoughts_tokens": 0,
            "latency_s": dt,
            "error": None,
        }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:200]
        return {
            "text": f"ERROR: HTTP {exc.code}: {body}",
            "input_tokens": estimate_tokens(prompt),
            "output_tokens": 0,
            "thoughts_tokens": 0,
            "latency_s": time.perf_counter() - t0,
            "error": f"HTTP {exc.code}: {body}",
        }
    except Exception as exc:
        return {
            "text": f"ERROR: {exc}",
            "input_tokens": estimate_tokens(prompt),
            "output_tokens": 0,
            "thoughts_tokens": 0,
            "latency_s": time.perf_counter() - t0,
            "error": str(exc),
        }


def run_ollama_sweep(models: list[str], json_modes: list[bool], arms: list[str], timeout_s: int = 120) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for model in models:
        for jm in json_modes:
            jm_label = "ollama_json" if jm else "unconstrained"
            for arm in arms:
                sess = GauntletSession(arm=arm)
                arm_ctx = 4096 if arm == "ungated_full_history" else 2560
                try:
                    for idx in range(len(sess.steps)):
                        prompt, _ = sess.build_prompt(idx)
                        res = call_ollama(model, prompt, json_mode=jm, timeout_s=timeout_s, num_ctx=arm_ctx)
                        sess.record_response(
                            idx,
                            res["text"],
                            input_tokens=res["input_tokens"],
                            output_tokens=res["output_tokens"],
                            thoughts_tokens=res["thoughts_tokens"],
                            latency_s=res["latency_s"],
                        )
                    summ = sess.summarize(model_label=model, json_mode=jm_label)
                    summaries.append(summ)
                    print(
                        f"[OLLAMA] {model} ({jm_label}) | {arm:25s} | "
                        f"acc={summ['accuracy_pct']:5.1f}% ({summ['correct_steps']}/20) | "
                        f"recur={summ['contradiction_recurrences']}/{summ['post_correction_trap_exposures']} "
                        f"({summ['contradiction_recurrence_rate_pct']:5.1f}%) | "
                        f"json={summ['json_valid_pct']:5.1f}% | errs={summ['api_errors']} | "
                        f"tok={summ['total_tokens_incl_thinking']:,} | lat={summ['total_latency_s']:.1f}s",
                        flush=True,
                    )
                finally:
                    sess.close()
    return summaries


def render_gauntlet_markdown(all_runs: list[dict[str, Any]], out_path: Path = DEFAULT_OUT_MD) -> str:
    lines = [
        "# 20-Step Multi-Turn Contradiction & Capability-Floor Gauntlet Report",
        "",
        "**Task:** Private Kestrel-7 Modular Assembly Line (20 sequential stateful steps, 4 non-textbook trap rules: `TRAP_1_BOW`, `TRAP_2_VALVE`, `TRAP_3_DERATE`, `TRAP_4_MASS` ceiling `420.0 g`).  ",
        "**Arms:** (a) `ungated_full_history` (unbounded), (b) `matched_token_hybrid_rag` (`<= 2,200` tokens, BM25+TF-IDF RRF, no `[FALSIFIED]` tier), (c) `sqlite_gated` (`<= 2,200` tokens, 3-table SQLite `[FALSIFIED]` ledger + deterministic mass register).",
        "",
        "## Summary Table (Live Runs Only — Zero Extrapolated Tiers)",
        "",
        "| Model | Constraint Mode | Arm | Step Accuracy | Contradiction Recurrence | JSON Valid | Input Tok | Output Tok | Thoughts Tok | Total Tok | Max Turn In | Wall Clock |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in all_runs:
        th = str(r["total_thoughts_tokens"]) if r["total_thoughts_tokens"] is not None else "n/a"
        lines.append(
            f"| `{r['model']}` | `{r['json_mode']}` | `{r['arm']}` | "
            f"**{r['accuracy_pct']:.1f}%** ({r['correct_steps']}/{r['steps_run']}) | "
            f"**{r['contradiction_recurrence_rate_pct']:.1f}%** ({r['contradiction_recurrences']}/{r['post_correction_trap_exposures']}) | "
            f"{r['json_valid_pct']:.1f}% | {r['total_input_tokens']:,} | {r['total_output_tokens']:,} | "
            f"{th} | {r['total_tokens_incl_thinking']:,} | {r['max_turn_input_tokens']:,} | {r['total_latency_s']:.1f} s |"
        )
    text = "\n".join(lines) + "\n"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return text


def run_self_test() -> None:
    """Deterministic unit verification of the 20-step oracle, token budgets, and 3-arm harness."""
    steps = build_gauntlet_steps()
    assert len(steps) == 20, f"Expected 20 steps, got {len(steps)}"
    # Verify oracle ground truth reaches exact 420.0g by step 20 and contains >=7 post-correction trap recurrences
    mass = 0.0
    accepts, rejects = 0, 0
    traps_seen: set[str] = set()
    post_traps = 0
    for s in steps:
        gt = evaluate_ground_truth(s, mass)
        mass = gt["cumulative_mass_after_g"]
        if gt["decision"] == "ACCEPT":
            accepts += 1
        else:
            rejects += 1
        if gt["violated_trap"]:
            if gt["violated_trap"] in traps_seen:
                post_traps += 1
            traps_seen.add(gt["violated_trap"])
    assert abs(mass - 420.0) < 1e-6, f"Final accepted mass should equal 420.0 g, got {mass}"
    assert len(traps_seen) == 4, f"Expected all 4 distinct traps triggered, got {traps_seen}"
    assert post_traps == 8, f"Expected 8 post-correction trap recurrences, got {post_traps}"

    # Verify Arm B and Arm C stay strictly <= 2200 tokens on all 20 steps while Arm A grows unbounded
    for arm in ARMS:
        sess = GauntletSession(arm=arm)
        try:
            for i in range(20):
                p, tok = sess.build_prompt(i)
                if arm != "ungated_full_history":
                    assert tok <= TOKEN_BUDGET, f"{arm} step {i+1} exceeded budget: {tok}"
                # Feed naive shortcut ("ACCEPT" always) to verify recurrence tracking + SQLite falsified_log
                sess.record_response(i, json.dumps({"decision": "ACCEPT", "computed_value": 1.0, "rule_id": "NAIVE", "reason": "shortcut"}))
            summ = sess.summarize("naive_dummy")
            assert summ["post_correction_trap_exposures"] == 8
            assert summ["contradiction_recurrences"] == 8
            if arm == "sqlite_gated":
                f_cnt = sess.conn.execute("SELECT COUNT(*) FROM falsified_log").fetchone()[0]
                e_cnt = sess.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                assert f_cnt == 4 and e_cnt == 8, f"Expected 4 falsified traps & 8 edges, got {f_cnt}/{e_cnt}"
        finally:
            sess.close()
    print(f"[SELF-TEST OK] 20 steps | accepts={accepts} rejects={rejects} | final_mass={mass}g | traps={sorted(traps_seen)} | post_correction_recurrences={post_traps}")


def main() -> None:
    parser = argparse.ArgumentParser(description="20-Step Kestrel-7 Multi-Turn Contradiction Gauntlet")
    parser.add_argument("--self-test", action="store_true", help="Run deterministic harness verification")
    parser.add_argument("--backend", choices=("ollama", "merge-report"), default="ollama")
    parser.add_argument("--models", default="llama2:latest,llama3:latest", help="Comma-separated Ollama models")
    parser.add_argument("--json-modes", default="off,on", help="Comma-separated off,on")
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--timeout", type=int, default=90)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return

    if args.backend == "ollama":
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        jmodes = [m.strip().lower() == "on" for m in args.json_modes.split(",") if m.strip()]
        arms = [a.strip() for a in args.arms.split(",") if a.strip()]
        runs = run_ollama_sweep(models, jmodes, arms, timeout_s=args.timeout)
        existing = []
        if args.out_json.exists():
            try:
                existing = json.loads(args.out_json.read_text(encoding="utf-8")).get("runs", [])
            except Exception:
                existing = []
        # Replace matching (model, json_mode, arm) tuples cleanly
        key_fn = lambda r: (r["model"], r["json_mode"], r["arm"])
        merged_map = {key_fn(r): r for r in existing}
        for r in runs:
            merged_map[key_fn(r)] = r
        all_runs = list(merged_map.values())
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps({"updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "runs": all_runs}, indent=2), encoding="utf-8")
        render_gauntlet_markdown(all_runs, args.out_md)
        print(f"Saved {len(all_runs)} gauntlet run(s) to {args.out_json} and {args.out_md}")
    elif args.backend == "merge-report":
        all_runs = json.loads(args.out_json.read_text(encoding="utf-8")).get("runs", [])
        render_gauntlet_markdown(all_runs, args.out_md)
        print(f"Rendered {len(all_runs)} run(s) to {args.out_md}")


if __name__ == "__main__":
    main()
