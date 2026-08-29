from tools.final_rc_v2_report import build_report


def test_final_rc_v2_aggregator_does_not_promote_incomplete_migration():
    report = build_report()
    assert report["gates"]["CRITICAL_FALSE_ACCEPTANCE_OPEN"] == 0
    assert report["gates"]["WINDOWS_VALIDATION_COMPLETE"]
    assert report["gates"]["LINUX_VALIDATION_COMPLETE"]
    assert report["gates"]["LICENSE_DECISION_COMPLETE"]
    assert not report["gates"]["NATIVE_MIGRATION_COMPLETE"]
    assert report["status"] == "RC_NOT_READY"
    assert report["release_tag_candidate"] is None
