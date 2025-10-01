#!/usr/bin/env python3
"""Jargon Theory analyzer.

This module implements a lightweight command line utility that helps apply the
so-called "Jargon theory" workflow to a collection of qualitative research
cases.  The theory is often used to examine how specialised vocabulary
(jargon), conceptual dimensions, and discursive patterns show up in empirical
materials.  The tool expects two inputs:

* A *language* configuration file describing the controlled vocabulary,
  conceptual categories, and optional interpretative rules.
* A *cases* file with the textual data (e.g. interview excerpts, field notes,
  etc.) that should be analysed.

The script produces a structured description of how the jargon is distributed
across each case and synthesises dimension scores that can be used in
subsequent qualitative analysis.

The language configuration and the cases file can be JSON or YAML (if PyYAML is
available).  Examples of both files are available in the ``examples/``
directory.

Typical usage::

    python jargon_theory.py analyze \
        --language examples/language.json \
        --cases examples/cases.json \
        --format markdown

This will print a Markdown report with a per-case breakdown.  See the README
for more details.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

try:
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    yaml = None  # type: ignore


@dataclasses.dataclass(slots=True, frozen=True)
class JargonTerm:
    """Represents a jargon entry defined in the language file."""

    term: str
    category: str | None = None
    weight: float = 1.0
    description: str | None = None
    variants: tuple[str, ...] = dataclasses.field(default_factory=tuple)

    def patterns(self) -> tuple[re.Pattern[str], ...]:
        """Return compiled regex patterns for the term and its variants."""

        raw_variants = (self.term, *self.variants)
        compiled: list[re.Pattern[str]] = []
        for variant in raw_variants:
            if not variant:
                continue
            pattern = re.compile(rf"\b{re.escape(variant)}\b", re.IGNORECASE)
            compiled.append(pattern)
        return tuple(compiled)


@dataclasses.dataclass(slots=True)
class Dimension:
    """Represents a conceptual dimension used to score jargon usage."""

    name: str
    description: str | None = None
    weights: Mapping[str, float] = dataclasses.field(default_factory=dict)

    def weight_for_category(self, category: str | None) -> float:
        if category and category in self.weights:
            return self.weights[category]
        return self.weights.get("__default__", 0.0)


@dataclasses.dataclass(slots=True)
class LanguageConfig:
    """In-memory representation of the language configuration."""

    terms: tuple[JargonTerm, ...]
    dimensions: tuple[Dimension, ...]
    density_thresholds: Mapping[str, float]

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "LanguageConfig":
        terms = []
        for raw_term in mapping.get("terms", []):
            term = JargonTerm(
                term=str(raw_term["term"]).strip(),
                category=raw_term.get("category"),
                weight=float(raw_term.get("weight", 1.0)),
                description=raw_term.get("description"),
                variants=tuple(raw_term.get("variants", []) or ()),
            )
            terms.append(term)

        dimensions = []
        for raw_dimension in mapping.get("dimensions", []):
            dimension = Dimension(
                name=str(raw_dimension["name"]).strip(),
                description=raw_dimension.get("description"),
                weights=dict(raw_dimension.get("weights", {})),
            )
            dimensions.append(dimension)

        density_thresholds = dict(mapping.get("density_thresholds", {}))
        density_thresholds.setdefault("high", 0.12)
        density_thresholds.setdefault("moderate", 0.06)

        return cls(
            terms=tuple(terms),
            dimensions=tuple(dimensions),
            density_thresholds=density_thresholds,
        )


@dataclasses.dataclass(slots=True)
class Case:
    """A single text case to analyse."""

    identifier: str
    text: str
    metadata: Mapping[str, Any] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any]) -> "Case":
        identifier = str(mapping.get("id") or mapping.get("identifier") or "")
        if not identifier:
            raise ValueError("Each case must define an 'id' field")
        text = str(mapping.get("text") or "").strip()
        if not text:
            raise ValueError(f"Case '{identifier}' is missing textual data")
        metadata = {k: v for k, v in mapping.items() if k not in {"id", "identifier", "text"}}
        return cls(identifier=identifier, text=text, metadata=metadata)


@dataclasses.dataclass
class TermMatch:
    term: JargonTerm
    count: int


@dataclasses.dataclass
class CaseAnalysis:
    case: Case
    matches: Sequence[TermMatch]
    total_words: int
    total_occurrences: int
    dimension_scores: Mapping[str, float]
    density: float
    density_level: str

    def as_dict(self) -> Mapping[str, Any]:
        return {
            "case": {"id": self.case.identifier, **self.case.metadata},
            "total_words": self.total_words,
            "total_jargon_occurrences": self.total_occurrences,
            "unique_jargon_terms": len([m for m in self.matches if m.count > 0]),
            "jargon_density": self.density,
            "density_level": self.density_level,
            "dimension_scores": dict(self.dimension_scores),
            "term_breakdown": [
                {
                    "term": match.term.term,
                    "category": match.term.category,
                    "count": match.count,
                    "weight": match.term.weight,
                    "description": match.term.description,
                    "variants": match.term.variants,
                }
                for match in self.matches
                if match.count > 0
            ],
        }


def load_structure(path: Path) -> Mapping[str, Any] | Sequence[Any]:
    """Load a JSON or YAML structure from *path*."""

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError(
                "PyYAML is required to load YAML files. Install it with 'pip install PyYAML'."
            )
        return yaml.safe_load(text)
    raise ValueError(f"Unsupported file extension '{suffix}' for {path}")


def load_language_config(path: Path) -> LanguageConfig:
    data = load_structure(path)
    if not isinstance(data, Mapping):
        raise TypeError("Language file must contain a JSON/YAML object")
    return LanguageConfig.from_mapping(data)


def load_cases(path: Path) -> tuple[Case, ...]:
    data = load_structure(path)
    if isinstance(data, Mapping):
        items = data.get("cases")
        if items is None:
            raise ValueError("Cases file must contain a 'cases' list when encoded as an object")
    else:
        items = data
    if not isinstance(items, Iterable):
        raise TypeError("Cases file must provide an iterable of case objects")
    cases: list[Case] = []
    for raw_case in items:  # type: ignore[assignment]
        if not isinstance(raw_case, Mapping):
            raise TypeError("Each case entry must be a JSON/YAML object")
        cases.append(Case.from_mapping(raw_case))
    return tuple(cases)


def tokenize(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text.lower())


def find_term_matches(text: str, term: JargonTerm) -> int:
    count = 0
    for pattern in term.patterns():
        matches = pattern.findall(text)
        count += len(matches)
    return count


def compute_density_level(density: float, thresholds: Mapping[str, float]) -> str:
    high = thresholds.get("high", 0.12)
    moderate = thresholds.get("moderate", 0.06)
    if density >= high:
        return "high"
    if density >= moderate:
        return "moderate"
    return "low"


def analyse_case(case: Case, config: LanguageConfig) -> CaseAnalysis:
    text = case.text
    total_words = len(tokenize(text))

    term_matches: list[TermMatch] = []
    term_counts: Counter[JargonTerm] = Counter()
    for term in config.terms:
        count = find_term_matches(text, term)
        if count:
            term_counts[term] = count
        term_matches.append(TermMatch(term=term, count=count))

    total_occurrences = sum(term_counts.values())
    density = (total_occurrences / total_words) if total_words else 0.0
    density_level = compute_density_level(density, config.density_thresholds)

    dimension_scores: dict[str, float] = {}
    for dimension in config.dimensions:
        score = 0.0
        for term, count in term_counts.items():
            weight = dimension.weight_for_category(term.category)
            if weight:
                score += weight * count * term.weight
        dimension_scores[dimension.name] = score

    return CaseAnalysis(
        case=case,
        matches=term_matches,
        total_words=total_words,
        total_occurrences=total_occurrences,
        dimension_scores=dimension_scores,
        density=density,
        density_level=density_level,
    )


def analyse_cases(cases: Sequence[Case], config: LanguageConfig) -> list[CaseAnalysis]:
    return [analyse_case(case, config) for case in cases]


def format_markdown(analyses: Sequence[CaseAnalysis], top: int | None = None) -> str:
    lines = ["# Jargon theory analysis", ""]
    for analysis in analyses:
        case = analysis.case
        lines.append(f"## Case {case.identifier}")
        if case.metadata:
            for key, value in case.metadata.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")
        lines.append("### Summary")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("| --- | --- |")
        lines.append(f"| Total words | {analysis.total_words} |")
        lines.append(f"| Total jargon occurrences | {analysis.total_occurrences} |")
        lines.append(f"| Unique jargon terms | {len([m for m in analysis.matches if m.count > 0])} |")
        lines.append(f"| Jargon density | {analysis.density:.3f} |")
        lines.append(f"| Density level | {analysis.density_level} |")
        if analysis.dimension_scores:
            lines.append("| Dimension scores | " + ", ".join(
                f"{name}: {score:.2f}" for name, score in analysis.dimension_scores.items()
            ) + " |")
        lines.append("")

        lines.append("### Term breakdown")
        lines.append("")
        lines.append("| Term | Category | Count | Weight | Variants | Description |")
        lines.append("| --- | --- | ---: | ---: | --- | --- |")
        # Sort matches by count descending, then name.
        sorted_matches = sorted(
            [m for m in analysis.matches if m.count > 0],
            key=lambda m: (-m.count, m.term.term.lower()),
        )
        if top is not None:
            sorted_matches = sorted_matches[:top]
        if not sorted_matches:
            lines.append("| *(none)* | - | 0 | 0 | - | - |")
        else:
            for match in sorted_matches:
                variants = ", ".join(match.term.variants) if match.term.variants else "-"
                description = match.term.description or "-"
                lines.append(
                    f"| {match.term.term} | {match.term.category or '-'} | {match.count} | "
                    f"{match.term.weight:.2f} | {variants} | {description} |"
                )
        lines.append("")
    return "\n".join(lines)


def format_json(analyses: Sequence[CaseAnalysis]) -> str:
    payload = [analysis.as_dict() for analysis in analyses]
    return json.dumps(payload, indent=2, ensure_ascii=False)


def run_analyse(args: argparse.Namespace) -> None:
    language_path = Path(args.language)
    cases_path = Path(args.cases)
    config = load_language_config(language_path)
    cases = load_cases(cases_path)
    analyses = analyse_cases(cases, config)
    if args.format == "markdown":
        output = format_markdown(analyses, top=args.top)
    else:
        output = format_json(analyses)

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply Jargon theory to textual cases")
    subparsers = parser.add_subparsers(dest="command")

    analyse_parser = subparsers.add_parser(
        "analyze",
        help="Analyse cases using a language configuration",
    )
    analyse_parser.add_argument("--language", required=True, help="Path to the language JSON/YAML file")
    analyse_parser.add_argument("--cases", required=True, help="Path to the cases JSON/YAML file")
    analyse_parser.add_argument(
        "--format",
        choices=["json", "markdown"],
        default="json",
        help="Output format. Default: json",
    )
    analyse_parser.add_argument(
        "--output",
        help="Optional path to save the analysis. If omitted, data is printed to stdout.",
    )
    analyse_parser.add_argument(
        "--top",
        type=int,
        default=None,
        help="Limit the number of jargon terms shown in the Markdown report.",
    )
    analyse_parser.set_defaults(func=run_analyse)

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
