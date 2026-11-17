"""World data for seed 42. Rule code reads these tables. It does not contain them."""

from __future__ import annotations

SEED = 42
ANCHOR = "2026-10-27 00:00:00"
MARKER = "SYN-E2E-"
# One work-note line per Closed history incident: number, then correlation id.
HISTORY_NOTE = "SYN-E2E-HISTORY"
# Incident category by CI class. History and arrivals use this table.
# A class that is not listed gets no category.
CATEGORY_BY_CI_CLASS: dict[str, str] = {
    "cmdb_ci_appl": "software",
    "cmdb_ci_linux_server": "hardware",
}
LOOKBACK_DAYS = 42
CHANGE_WINDOW_DAYS = 14
WEEKDAY_WEEKS = 3
LIFT_AFTER_COUNT = 3
LIFT_RATIO = 2
RATE_MIN_COUNT = 3


def category_for_class(ci_class: str) -> str:
    """Return the incident category for a CI class, or empty when the class is unknown."""
    return CATEGORY_BY_CI_CLASS.get(ci_class, "")


def history_note_line(number: str, correlation_id: str) -> str:
    """One Closed-history line a person can follow from the problem."""
    if not number or not correlation_id:
        raise ValueError("history note needs the incident number and the correlation id")
    return f"{HISTORY_NOTE} {number} {correlation_id}"


# Signal (a). A phrase votes only when it is in more than half the notes.
PHRASES: dict[str, tuple[str, ...]] = {
    "log_rotation_stopped": ("no rotation", "log directory filled"),
    "stale_feature_flag": ("feature flag", "flag still off"),
    "service_account_key_stale": ("service account key", "batch key expired"),
    "worker_not_restarted": ("not restarted", "stuck worker"),
    "connection_pool_exhausted": ("connection pool", "holds locks"),
    "cache_not_cleared": ("stale cache", "cached page"),
    "weekend_batch_lock": ("weekend batch",),
    "checkout_saturation": ("checkout queue",),
    "archive_growth": ("archive tables", "keeps growing"),
}

# Signal (d) supports a CI-specific cause. It does not name a mechanism.
# checkout_saturation is the one-incident emergency path, so it does not accept (d).
CI_SPECIFIC = frozenset(
    {
        "log_rotation_stopped",
        "stale_feature_flag",
        "service_account_key_stale",
        "worker_not_restarted",
        "connection_pool_exhausted",
        "cache_not_cleared",
        "archive_growth",
        "weekend_batch_lock",
    }
)

# Signal (b). A job, the CI it runs on, the weekday, and the mechanism a failure implies.
JOB_SCHEDULE: tuple[dict[str, str], ...] = (
    {
        "job": "rotate-checkout-logs",
        "ci": "syn-store-checkout",
        "weekday": "Tuesday",
        "mechanism": "log_rotation_stopped",
    },
    {
        "job": "rotate-benefits-logs",
        "ci": "syn-hr-benefits",
        "weekday": "Tuesday",
        "mechanism": "log_rotation_stopped",
    },
    {
        "job": "rotate-fulfillment-logs",
        "ci": "syn-prd-lx-073",
        "weekday": "Tuesday",
        "mechanism": "log_rotation_stopped",
    },
    {
        "job": "reload-recruiting-flags",
        "ci": "syn-hr-recruiting",
        "weekday": "Monday",
        "mechanism": "stale_feature_flag",
    },
    {
        "job": "rotate-payroll-batch-key",
        "ci": "syn-hr-payroll",
        "weekday": "Wednesday",
        "mechanism": "service_account_key_stale",
    },
    {
        "job": "restart-stage-worker",
        "ci": "syn-stg-lx-001",
        "weekday": "Thursday",
        "mechanism": "worker_not_restarted",
    },
    {
        "job": "recycle-inventory-pool",
        "ci": "syn-ful-inventory",
        "weekday": "Friday",
        "mechanism": "connection_pool_exhausted",
    },
    {
        "job": "clear-fraud-cache",
        "ci": "syn-pay-fraud",
        "weekday": "Sunday",
        "mechanism": "cache_not_cleared",
    },
    {
        "job": "release-catalog-weekend-batch",
        "ci": "syn-store-catalog",
        "weekday": "Saturday",
        "mechanism": "weekend_batch_lock",
    },
)

# Signal (c). Change kind (the closed change's summary) to the mechanism it implies.
# Summaries that are not in this table cast no vote. The rule does not name change numbers.
KIND_MAP: dict[str, str] = {
    "SYN rotate application log files": "log_rotation_stopped",
    "SYN reload feature flag snapshot": "stale_feature_flag",
    "SYN rotate service account key for batch": "service_account_key_stale",
}

HOLD_RCA_UNCONFIRMED = "rca_unconfirmed"
HOLD_FIX_FAILED = "fix_failed_no_alternative"
HOLD_EMERGENCY = "emergency_not_delegated"
HOLD_HIGH_RISK = "high_risk_not_delegated"

# Eight dissimilar tickets. Measured cohesion under the unmodified centroid rule
# was 0.38, which is High, because eight nearly orthogonal notes sit near 1/sqrt(8).
DECOY_SUMMARIES = (
    "A clerk waited on a spinning payments page after the morning password reset",
    "The cashier called because a dropped vpn client froze the tender screen",
    "An old browser profile left the recon login form blank until cookies were cleared",
    "Office wifi died and the tablet showed a gateway warning instead of the amount",
    "The lobby badge reader failed so the new hire never reached the recon desk",
    "A full mailbox quota stopped the receipt notice and the clerk called the desk",
    "A loose monitor cable blacked out the station until facilities reseated the plug",
    "A jammed printer queue held the lane receipt and the lead asked for paper",
)
DECOY_NOTES = (
    "Desk note: the caller had just finished a password reset and could not sign in.",
    "Desk note: the vpn client dropped while the cashier was taking a card.",
    "Desk note: an old browser profile was blocking the login form.",
    "Desk note: the office wifi dropped and the tablet lost the network.",
    "Desk note: the badge reader at the door failed.",
    "Desk note: the mailbox quota was full.",
    "Desk note: the monitor cable was loose.",
    "Desk note: the printer queue was jammed.",
)

# Four tickets, a different CI, below the fork's count of 5. Opens nothing.
BURST_SUMMARIES = (
    "A shopper asked why the receipt printer skipped one page",
    "The lane scale showed ounces and the cashier reweighed the bag",
    "A gift card swipe asked for a signature and then declined",
    "The price gun sticker did not match the shelf label",
)
BURST_NOTES = (
    "Desk note: the receipt printer skipped a page. A reprint worked.",
    "Desk note: the lane scale needed a reweigh. The second weight matched.",
    "Desk note: one gift card swipe declined. Another tender completed the sale.",
    "Desk note: a shelf label and a sticker disagreed. The register price was used.",
)

NOISE_CIS = (
    "syn-hr-portal",
    "syn-hr-time",
    "syn-pay-auth",
    "syn-pay-ledger",
    "syn-store-search",
    "syn-store-session",
    "syn-store-cart",
    "syn-ful-warehouse",
)
NOISE_DAYS = ("2026-10-20", "2026-10-21", "2026-10-22")
NOISE_SUMMARIES = (
    "The page is slow this morning and then it loads",
    "A user saw an error and a refresh cleared it",
    "Login was slow once and then the page worked",
    "Someone reported a timeout that did not return",
    "The service felt slow during a meeting",
    "An error banner flashed and the page recovered",
    "Users mentioned a slow search that succeeded on retry",
    "One timeout on the home page, then normal",
    "The form was slow to paint and then submitted",
    "A caller said the page showed an error for a second",
    "The balance looked slow and then the figure loaded",
    "Search timed out once on a long query",
    "The portal page was slow to open and then displayed",
    "An error on a report cleared after a retry",
    "The menu was slow and the rest of the page was fine",
    "A user lost the page during a timeout and signed in again",
    "One item felt slow and then the sale completed",
    "The dashboard showed an error and reloaded itself",
    "Someone called about a slow login that worked the second time",
    "A timeout on a lookup did not happen again",
    "The portal page was slow right after lunch",
    "An error opened and the user closed it",
    "Users saw a slow spinner and the page arrived",
    "One service page timed out and the next click worked",
)

LOGS = (
    "HR portal pages load slowly and the error says the log directory filled the disk",
    "Shoppers see a timeout when the application cannot write because there is no rotation of logs",
    "The store checkout spins, then shows an error once the log files have used the disk",
    "Overnight the same checkout error returned and the log directory filled again",
    "Users refresh checkout and still get a slow page after the logs filled the volume",
    "Checkout displays an error page and new log files are no longer being written",
    "A slow checkout ends in a timeout while the log directory keeps filling",
    "The team sees the checkout error each Tuesday as the logs fill the disk",
)
BENEFITS = (
    "Benefits pages load slowly and the error says the log directory filled the disk",
    "Employees see a timeout when benefits cannot write because there is no rotation of logs",
    "The benefits service spins, then shows an error once the log files have used the disk",
    "Overnight the same benefits error returned and the log directory filled again",
    "Users refresh benefits and still get a slow page after the logs filled the volume",
    "Benefits displays an error page and new log files are no longer being written",
    "A slow benefits page ends in a timeout while the log directory keeps filling",
    "The team sees the benefits error each Tuesday as the logs fill the disk",
)
LINUX_LOGS = (
    "The fulfillment server is slow and the log directory filled overnight",
    "Jobs time out on the server because there is no rotation of the logs",
    "Users see an error from the server once the logs filled the disk",
    "The server page is slow and new log files are not written",
    "A timeout on the server follows the log directory filling up",
    "Operators report an error after the logs filled the volume again",
    "The server stays slow for users while there is no rotation of logs",
    "Each Tuesday the server error returns as the log directory filled",
)
FLAGS = (
    "Recruiting pages are slow and a feature flag is still off for new applicants",
    "Users hit a timeout on the application form while the flag still off blocks saving",
    "The recruiting service shows an error page because a feature flag was not reloaded",
    "Applicants see a slow blank page and the feature flag is still off",
    "Saving a candidate times out and the error names the feature flag",
    "The same recruiting error returns on Mondays when the flag still off",
    "Users report the recruiting page is slow until the feature flag is reloaded",
    "An error on the recruiting form says the feature flag snapshot is stale",
)
KEYS = (
    "Payroll pages time out and the service account key for the batch is expired",
    "Users see an error when payroll runs and the batch key expired overnight",
    "The payroll service is slow and fails with a service account key error",
    "A Wednesday payroll run shows an error page because the batch key expired",
    "Users retry payroll and the page times out on the service account key",
    "The batch stops with an error and the service account key is no longer accepted",
    "Payroll is slow for users after the batch key expired again",
    "The payroll error page names the service account key used by the batch",
)
WORKERS = (
    "The store stage server is slow and one worker was not restarted after the last deploy",
    "Users see a timeout from the stage site while a stuck worker holds the queue",
    "Pages error on the stage server because the worker was not restarted",
    "The same stage error returns on Thursdays and the stuck worker is still there",
    "A slow stage page times out until someone notices the worker was not restarted",
    "Users report an error page from stage and the stuck worker has not been restarted",
    "Stage checkout is slow and the error points at a worker that was not restarted",
    "The stage service times out for users while the stuck worker keeps the old process",
)
POOLS = (
    "Inventory pages time out and the connection pool holds locks",
    "Warehouse users see a slow error when the connection pool is exhausted",
    "The inventory service shows an error page because the pool holds locks",
    "A Friday inventory run is slow and the connection pool does not recover",
    "Users refresh inventory and the page times out while the pool holds locks",
    "The inventory error says the connection pool has no free connections",
    "Pickers see a slow timeout and the connection pool still holds locks",
    "Inventory is unusable for users once the connection pool is exhausted",
)
CACHE = (
    "The payments page is slow and shows a stale cache of yesterday's balance",
    "Users see an old cached page and an error when they submit a payment",
    "Payments times out and the stale cache serves the previous total",
    "A Sunday payments error page is the cached page from the prior weekend",
    "Users report the payments service is slow because of a stale cache",
    "The cached page on payments shows an error and the old amount",
    "Refreshing payments still returns the stale cache and then a timeout",
    "The payments error mentions a cached page that was never cleared",
)
CONFUSED = (
    "Catalog search is slow on Saturday and a worker was not restarted",
    "Users see a timeout in catalog while a stuck worker remains",
    "The catalog error page says the worker was not restarted",
    "Saturday catalog is slow and the stuck worker is still running",
    "Users hit an error in catalog search and the worker was not restarted",
    "Catalog times out for users because of a stuck worker",
    "The catalog page is slow and shows an error from a worker not restarted",
    "A Saturday catalog timeout repeats and the stuck worker was not restarted",
)

# history_count is how many leading dates are loaded by seed. The rest arrive in a scenario.
CLUSTERS: tuple[dict[str, object], ...] = (
    {
        "id": "C02",
        "ci": "syn-store-checkout",
        "mechanism": "log_rotation_stopped",
        "days": (
            "2026-09-15",
            "2026-09-22",
            "2026-09-29",
            "2026-10-20",
            "2026-10-21",
            "2026-10-22",
            "2026-10-23",
            "2026-10-24",
        ),
        "summaries": LOGS,
        "history_count": 3,
        "scenario": "E02",
    },
    {
        "id": "C07",
        "ci": "syn-prd-lx-073",
        "mechanism": "log_rotation_stopped",
        "days": (
            "2026-09-15",
            "2026-09-22",
            "2026-09-29",
            "2026-10-20",
            "2026-10-21",
            "2026-10-22",
            "2026-10-23",
            "2026-10-24",
        ),
        "summaries": LINUX_LOGS,
        "history_count": 3,
        "scenario": "E07",
    },
    {
        "id": "C12c",
        "ci": "syn-hr-recruiting",
        "mechanism": "stale_feature_flag",
        "days": (
            "2026-09-14",
            "2026-09-21",
            "2026-09-28",
            "2026-10-12",
            "2026-10-16",
            "2026-10-17",
            "2026-10-18",
            "2026-10-19",
        ),
        "summaries": FLAGS,
        "history_count": 8,
        "scenario": "E12",
    },
    {
        "id": "C12b",
        "ci": "syn-hr-payroll",
        "mechanism": "service_account_key_stale",
        "days": (
            "2026-09-16",
            "2026-09-23",
            "2026-09-30",
            "2026-10-14",
            "2026-10-15",
            "2026-10-16",
            "2026-10-17",
            "2026-10-18",
        ),
        "summaries": KEYS,
        "history_count": 8,
        "scenario": "E12",
    },
    {
        "id": "C12a",
        "ci": "syn-hr-benefits",
        "mechanism": "log_rotation_stopped",
        "days": (
            "2026-09-15",
            "2026-09-22",
            "2026-09-29",
            "2026-10-13",
            "2026-10-14",
            "2026-10-15",
            "2026-10-16",
            "2026-10-17",
        ),
        "summaries": BENEFITS,
        "history_count": 8,
        "scenario": "E12",
    },
    {
        "id": "C04",
        "ci": "syn-stg-lx-001",
        "mechanism": "worker_not_restarted",
        "days": (
            "2026-09-17",
            "2026-09-24",
            "2026-10-01",
            "2026-10-15",
            "2026-10-16",
            "2026-10-17",
            "2026-10-18",
            "2026-10-19",
        ),
        "summaries": WORKERS,
        "history_count": 8,
        "scenario": "E04",
    },
    {
        "id": "C05",
        "ci": "syn-ful-inventory",
        "mechanism": "connection_pool_exhausted",
        "days": (
            "2026-09-18",
            "2026-09-25",
            "2026-10-02",
            "2026-10-16",
            "2026-10-17",
            "2026-10-18",
            "2026-10-19",
            "2026-10-20",
        ),
        "summaries": POOLS,
        "history_count": 8,
        "scenario": "E05",
    },
    {
        "id": "C06",
        "ci": "syn-pay-fraud",
        "mechanism": "cache_not_cleared",
        "days": (
            "2026-09-13",
            "2026-09-20",
            "2026-09-27",
            "2026-10-18",
            "2026-10-19",
            "2026-10-20",
            "2026-10-21",
            "2026-10-22",
        ),
        "summaries": CACHE,
        "history_count": 8,
        "scenario": "E06",
    },
    {
        "id": "C11",
        "ci": "syn-store-catalog",
        "mechanism": "worker_not_restarted",
        "days": (
            "2026-09-12",
            "2026-09-19",
            "2026-09-26",
            "2026-10-17",
            "2026-10-18",
            "2026-10-19",
            "2026-10-20",
            "2026-10-21",
        ),
        "summaries": CONFUSED,
        "history_count": 8,
        "scenario": "E11",
    },
    {
        "id": "C01",
        "ci": "syn-store-cdn",
        "mechanism": "log_rotation_stopped",
        "days": ("2026-08-18", "2026-08-25", "2026-09-01"),
        "summaries": LOGS[:3],
        "history_count": 3,
        "scenario": "E01",
        "parent": "E01",
    },
)
