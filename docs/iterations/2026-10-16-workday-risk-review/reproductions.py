"""Original review scenarios now assert the fixed behavior via CI regressions."""
from tests.test_literature_batch_recovery import (  # noqa: F401
    test_crash_rolls_back_paper_and_receipt_then_recovers,
    test_stale_worker_never_saves_or_replaces_receipt,
)
from tests.test_starred_questions import (  # noqa: F401
    client,
    test_shared_edit_conflicts_and_reloads_latest_revision,
)
