"""Reporting docstring claims must have named enforcement."""

from __future__ import annotations

from breezy.settlement import reporting

ENFORCED_DOCSTRING_CLAIMS = (
    (
        "Pure reporting: this module performs no I/O, clock, environment, or network access.",
        "test_d1_settlement_package_is_pure",
    ),
    (
        "Programme reports are constructed through build_programme_report.",
        "test_r1_no_unsanctioned_programme_headline_construction",
    ),
    (
        "A PRIMARY_GO report requires MDW's boundary figure to be REPORTED.",
        "test_primary_go_requires_mdw_boundary_figure_reported",
    ),
)


def test_reporting_docstring_claims_are_pinned_to_mechanisms() -> None:
    docstring = reporting.__doc__ or ""

    for claim, mechanism in ENFORCED_DOCSTRING_CLAIMS:
        assert claim in docstring
        assert mechanism
