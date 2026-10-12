"""Internal feature availability; retired reports have no runtime or UI toggle."""

REPORTING_ENABLED = False
REPORTING_DISABLED_REASON = '刷图推荐和经验收益已停用。'


def require_reporting():
    if not REPORTING_ENABLED:
        raise ValueError(REPORTING_DISABLED_REASON)


def reporting_disabled():
    return {'available': False, 'disabled': True, 'reason': REPORTING_DISABLED_REASON,
            'error': REPORTING_DISABLED_REASON}
