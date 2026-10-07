# -*- coding: utf-8 -*-
from data_license import DistributionStatus, SOURCE_DISTRIBUTION, ViewerScope, can_display, status_of, LICENSE_NOTES


def test_nothing_is_external_until_written_license():
    assert DistributionStatus.EXTERNAL_ALLOWED not in SOURCE_DISTRIBUTION.values()
    for src in SOURCE_DISTRIBUTION:
        assert can_display(src, ViewerScope.OWNER) is True
        assert can_display(src, ViewerScope.EXTERNAL) is False
        assert LICENSE_NOTES[src]


def test_unknown_source_is_blocked_for_everyone():
    assert status_of("某新來源") == DistributionStatus.BLOCKED
    assert not can_display("某新來源", ViewerScope.OWNER)


def test_bundle_sources_are_all_registered():
    import data_bundle as db
    for name in db.SOURCE_TYPES:
        assert name in SOURCE_DISTRIBUTION, name
