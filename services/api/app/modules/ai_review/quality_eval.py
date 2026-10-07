"""New photo evaluation, separate from consumed T09 holdout and its $5 ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from PIL import Image

from .eval_runner import (
    ROOT,
    BudgetedProvider,
    BudgetExceeded,
    BudgetLedger,
    claim_holdout,
    exclusive_run,
    freeze_configuration,
    frozen_config,
    write_json,
)
from .prompts import SYSTEM_PROMPT
from .provider import OpenAIReviewProvider
from .rules import assess_rules
from .schemas import ImageEvidence, ReviewInput, StagePlan
from .service import evaluate_stage, evaluate_submission, finalize_result

PACK = ROOT / "evals" / "quality"
STATE = ROOT / ".tooling" / "t07-quality"
POSITIVE = {"accepted", "accepted_with_notes"}


class QualityBudgetLedger(BudgetLedger):
    def __init__(self, path: Path, phase: str):
        if phase not in {"dev", "comparison", "holdout"}:
            raise ValueError("Unknown evaluation phase")
        self.path, self.phase, self.limit = path, phase, Decimal("8")
        saved = json.loads(path.read_text()) if path.exists() else None
        if saved is not None and saved.get("limit_usd") != "8":
            raise ValueError("Quality evaluation requires its own authorized $8 ledger")
        self.records = saved["calls"] if saved else []
        if len({r["call_id"] for r in self.records}) != len(self.records):
            raise ValueError("Duplicate budget records")
        if any(
            not Decimal(r["charged_usd"]).is_finite() or Decimal(r["charged_usd"]) < 0
            for r in self.records
        ):
            raise ValueError("Invalid persisted charges")

    def reserve(self, call_id, amount, metadata=None):
        ceiling = Decimal("8") if self.phase == "holdout" else Decimal("5")
        if self.spent + Decimal(amount) > ceiling:
            raise BudgetExceeded("Keep $3 for holdout; total additional budget is $8")
        super().reserve(call_id, amount, {**(metadata or {}), "phase": self.phase})


class QualityBudgetedProvider(BudgetedProvider):
    def reserve_image_tokens(self, images, model=None):
        # Base64 is transport, not tokenized text. Official vision sizing:
        # <=1024px high-detail Astra uses <=1229 patch tokens. Keep a 32768
        # token bound for other model families, 1300 for Astra, without
        # weakening any source/format/size validation or JPEG quality.
        for image in images.values():
            with Image.open(BytesIO(image.data)) as decoded:
                if max(decoded.size) > 1024:
                    raise ValueError(
                        "Quality eval reservation requires <=1024px images"
                    )
                decoded.verify()
        return len(images) * (1300 if model == "gpt-6-astra" else 32768)


def register_development(directory: Path, prompt_hash: str):
    if (directory / "frozen.json").exists() or (
        directory / "holdout.started.json"
    ).exists():
        raise ValueError("Development/comparison is closed after freeze")
    path = directory / "prompt_versions.json"
    versions = json.loads(path.read_text()) if path.exists() else []
    if prompt_hash not in versions:
        if len(versions) >= 2:
            raise ValueError("At most two development prompt versions are authorized")
        write_json(path, [*versions, prompt_hash])


def pending_comparison(cases, ledger):
    attempted = {
        r["metadata"].get("case_id")
        for r in ledger.records
        if r["metadata"].get("model") == "gpt-6-astra"
        and r["metadata"].get("stage") == "escalation"
    }
    return [case for case in cases if case["case_id"] not in attempted]


def load_cases(pack=PACK):
    cases = [
        json.loads(line)
        for line in (pack / "cases.jsonl").read_text().splitlines()
        if line.strip()
    ]
    if len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case ids")
    for case in cases:
        if any(
            name.split("-", 1)[0] not in case["source_groups"]
            for name in case["photos"].values()
        ):
            raise ValueError("Photo source must belong to its declared split group")
    dev = {s for c in cases if c["split"] == "dev" for s in c["source_groups"]}
    holdout = [c for c in cases if c["split"] == "holdout"]
    if dev & {s for c in holdout for s in c["source_groups"]}:
        raise ValueError("Source projects cannot cross evaluation splits")
    if Counter(c["category"] for c in holdout) != Counter(good=4, bad=4, ambiguous=4):
        raise ValueError("Holdout must contain 4 good, 4 bad and 4 ambiguous cases")
    return cases


def load_photo_case(case: dict, media=STATE / "media"):
    images, photos = {}, []
    for phase, name in case["photos"].items():
        path = (media / name).resolve()
        if not path.is_relative_to(media.resolve()):
            raise ValueError("Media path must remain in ignored quality directory")
        data = path.read_bytes()
        if len(data) > 5 * 1024 * 1024:
            raise ValueError("Normalized image is too large")
        with Image.open(BytesIO(data)) as decoded:
            if decoded.format != "JPEG" or max(decoded.size) > 1024:
                raise ValueError("Expected normalized local JPEG")
            decoded.verify()
        ref = "photo:" + str(uuid5(NAMESPACE_URL, case["case_id"] + ":" + phase))
        images[ref] = ImageEvidence(media_type="image/jpeg", data=data)
        photos.append(
            {
                "id": ref,
                "phase": phase,
                "quality": "unknown",
                "content_fingerprint": hashlib.sha256(data).hexdigest(),
            }
        )
    value = ReviewInput(
        work_order_id=uuid5(NAMESPACE_URL, case["case_id"]),
        submission_revision=1,
        assignment_version=1,
        problem=case["problem"],
        work_description=case["work_description"],
        photo_refs=photos,
        material_checks=case.get("material_checks", []),
        timing_checks=[],
        checklist=[
            {
                "id": "report",
                "code": "report_fields",
                "required": True,
                "complete": bool(case["work_description"].strip()),
            },
            {"id": "after", "code": "mandatory_after_photo", "required": True},
        ],
    )
    return value, images


def configuration(cases):
    config = frozen_config(PACK)
    hashes = {}
    for name in sorted({name for c in cases for name in c["photos"].values()}):
        hashes[name] = hashlib.sha256((STATE / "media" / name).read_bytes()).hexdigest()
    config["normalized_media_hashes"] = hashes
    config["source_manifest_hash"] = hashlib.sha256(
        (PACK / "sources.json").read_bytes()
    ).hexdigest()
    config["quality_image_token_bound"] = {"gpt-6-astra": 1300, "other_allowed": 32768}
    config["price_verified_at"] = "2026-10-07"
    config["authorization"] = {
        "additional_usd": "8",
        "development_ceiling_usd": "5",
        "reserved_holdout_usd": "3",
    }
    return config


def acceptance(rows):
    counts = Counter(row["category"] for row in rows)
    good = sum(r["category"] == "good" and r["verdict"] in POSITIVE for r in rows)
    bad_accepted = sum(
        r["category"] == "bad" and r["verdict"] in POSITIVE for r in rows
    )
    ambiguous_human = sum(
        r["category"] == "ambiguous" and r["verdict"] == "human_review" for r in rows
    )
    return {
        "passed": counts == Counter(good=4, bad=4, ambiguous=4)
        and good >= 3
        and bad_accepted == 0
        and ambiguous_human == 4,
        "good_positive": good,
        "bad_accepted": bad_accepted,
        "ambiguous_human": ambiguous_human,
        "counts": dict(counts),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument(
        "--split", choices=["dev", "comparison", "holdout"], default="dev"
    )
    args = parser.parse_args(argv)
    from app.core.config import settings

    key = (
        settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    )
    if args.live and not key:
        print("BLOCKED: OPENAI_API_KEY отсутствует; вызовов нет.", file=sys.stderr)
        return 2
    if args.split in {"holdout", "comparison"} and not args.live and not args.freeze:
        print("Comparison/holdout require --live.", file=sys.stderr)
        return 2
    try:
        cases = load_cases()
        # Validate all assets and the split before any holdout marker or paid call.
        for case in cases:
            load_photo_case(case)
        config = configuration(cases)
        with exclusive_run(STATE):
            if args.freeze:
                freeze_configuration(STATE, config)
                print("New photo corpus/config frozen; no model calls.")
                return 0
            if args.split == "holdout":
                claim_holdout(STATE, config)
            elif args.live:
                register_development(
                    STATE, hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
                )
            selected = [
                c
                for c in cases
                if c["split"] == ("dev" if args.split == "comparison" else args.split)
            ]
            if args.split == "comparison":
                selected = [c for c in selected if c["comparison"]]
                if len(selected) != 2:
                    raise ValueError(
                        "Comparison must use exactly two development cases"
                    )
            ledger = QualityBudgetLedger(STATE / "budget.json", args.split)
            if args.split == "comparison":
                selected = pending_comparison(selected, ledger)
            wrapper = (
                QualityBudgetedProvider(
                    OpenAIReviewProvider(
                        key,
                        timeout=settings.ai_request_timeout_seconds,
                        max_output_tokens=settings.ai_max_output_tokens,
                        complex_max_output_tokens=settings.ai_complex_max_output_tokens,
                        capture_diagnostics=True,
                    ),
                    ledger,
                    settings.ai_max_output_tokens,
                    settings.ai_complex_max_output_tokens,
                )
                if args.live
                else None
            )
            rows, aborted = [], False
            run_id = str(uuid5(NAMESPACE_URL, str(__import__("time").time_ns())))
            output = STATE / f"{args.split}-{run_id}.json"
            for case in selected:
                value, images = load_photo_case(case)
                trace = []
                if wrapper:
                    wrapper.case_id = case["case_id"]
                try:
                    if args.split == "comparison":
                        rules = assess_rules(value)
                        plan = StagePlan(
                            stage="escalation", model="gpt-6-astra", reasoning="medium"
                        )
                        outcome = evaluate_stage(value, wrapper, plan, images)
                        diagnostic = {
                            "stage": "comparison",
                            "provider_outcome": outcome.model_dump(mode="json"),
                        }
                        result = finalize_result(
                            value, rules, outcome, diagnostics=diagnostic
                        )
                        trace.append(diagnostic)
                    else:
                        result = evaluate_submission(
                            value, wrapper, images, diagnostics=trace
                        )
                except BudgetExceeded:
                    aborted = True
                    break
                row = {
                    "case_id": case["case_id"],
                    "category": case["category"],
                    "expected_verdict": case["expected_verdict"],
                    "verdict": result.verdict,
                    "result": result.model_dump(mode="json"),
                    "trace": trace,
                    "invalid_refs": sum(
                        ref not in value.evidence_ids()
                        for f in result.findings
                        for ref in f.evidence_refs
                    ),
                }
                rows.append(row)
                write_json(
                    output,
                    {
                        "mode": "live" if args.live else "rules_only",
                        "split": args.split,
                        "config": config,
                        "rows": rows,
                        "calls": wrapper.calls if wrapper else [],
                        "spent_or_reserved_usd": str(ledger.spent),
                        "aborted_budget": False,
                        "acceptance": acceptance(rows)
                        if args.split == "holdout"
                        else None,
                    },
                )
                print(
                    case["case_id"],
                    result.verdict,
                    [f.code for f in result.findings],
                    flush=True,
                )
            write_json(
                output,
                {
                    "mode": "live" if args.live else "rules_only",
                    "split": args.split,
                    "config": config,
                    "rows": rows,
                    "calls": wrapper.calls if wrapper else [],
                    "spent_or_reserved_usd": str(ledger.spent),
                    "aborted_budget": aborted,
                    "acceptance": acceptance(rows) if args.split == "holdout" else None,
                },
            )
            print("Report:", output, "spent_or_reserved_usd:", ledger.spent, flush=True)
            return 3 if aborted else 0
    except (ValueError, OSError) as error:
        # Never echo network exceptions, response bodies, settings or credentials.
        print("Quality evaluation stopped:", type(error).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
