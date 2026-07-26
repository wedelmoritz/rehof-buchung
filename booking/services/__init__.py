"""Service-Layer: Brücke zwischen Django-Modellen und der reinen Logik.

Früher eine einzelne `services.py`; jetzt ein Paket aus fachlichen Submodulen
(siehe ADR 0050). Dieses `__init__` re-exportiert alle Namen, damit der bisherige
Zugriff `from booking import services as svc` und `svc.*` unverändert funktioniert.
"""
from __future__ import annotations

from .dates import *  # noqa: F401,F403
from .notify import *  # noqa: F401,F403
from .slots import *  # noqa: F401,F403
from .beds24_ops import *  # noqa: F401,F403
from .retention import *  # noqa: F401,F403
from .calendars import *  # noqa: F401,F403
from .lottery_ops import *  # noqa: F401,F403
from .wishes import *  # noqa: F401,F403
from .booking_ops import *  # noqa: F401,F403
from .pool import *  # noqa: F401,F403
from .dashboard import *  # noqa: F401,F403
from .external_ops import *  # noqa: F401,F403
from .terminal_ops import *  # noqa: F401,F403
from .helptexts import *  # noqa: F401,F403
from .blocks import *  # noqa: F401,F403
from .nl import *  # noqa: F401,F403
from .nl_learn import *  # noqa: F401,F403
from .nl_learn_ops import *  # noqa: F401,F403
from .nl_lexicon import *  # noqa: F401,F403
from .nl_shadow import *  # noqa: F401,F403

from . import dates, notify, slots, beds24_ops, retention, calendars, lottery_ops, wishes, booking_ops, pool, dashboard, external_ops, terminal_ops, helptexts, blocks, nl, nl_learn, nl_learn_ops, nl_lexicon, nl_shadow  # noqa: F401

# Parität zur alten `services.py`: dort waren die importierten Modelle und die
# reinen Logik-Module als Modul-Attribute erreichbar (z.B. `svc.ExternalConfig`,
# genutzt in views.py). Hier wieder bereitstellen, damit `svc.<Name>` unverändert
# funktioniert.
from .. import availability as A, lottery as L, rules as R, validation as V  # noqa: F401
from ..external import external_allowed, cancellation_refund  # noqa: F401
from ..models import (  # noqa: F401
    Allocation, BookingPeriod, BookingPolicy, ExternalBooking, ExternalConfig,
    Guest, LotteryRun, Member, NightTransfer, Notification, OutboxEmail, Quarter,
    SchoolHoliday, SeasonRule, SwapRequest, WaitlistEntry, Wish,
)

__all__ = [
    # Modelle + Logik-Aliasse (Parität zur alten services.py)
    'A', 'L', 'R', 'V', 'external_allowed', 'cancellation_refund',
    'Allocation', 'BookingPeriod', 'BookingPolicy', 'ExternalBooking',
    'ExternalConfig', 'Guest', 'LotteryRun', 'Member', 'NightTransfer',
    'Notification', 'OutboxEmail', 'Quarter', 'SchoolHoliday', 'SeasonRule',
    'SwapRequest', 'WaitlistEntry', 'Wish',
    'MONTHS_DE', 'WEEKDAYS_DE', 'month_label', 'month_bounds', 'next_month',
    '_Holiday', 'school_holidays_in_range', 'GERMAN_MONTHS', 'EXTERN_COLOR',
    'unread_notifications', 'mark_notifications_read', 'absolute_url',
    'queue_email', 'email_member', 'queue_email_many', 'email_admins',
    'email_cleaning', 'notify_admins_new_user', 'send_web_push', '_quarters_payload',
    '_external_blocking_qs', 'quarter_is_free', 'find_gaps',
    '_materialized_seasons', 'check_booking_rules', 'schedule_blocker',
    'season_min_nights', 'min_nights_for_range', 'external_min_nights',
    'wish_rule_error', '_active_windows', '_in_season_range',
    'range_is_released', 'find_bookable_gaps', 'split_quarters_for_range',
    'unavailable_quarters_for_range',
    '_occupied_days_by_quarter', '_beds24_member_candidates',
    '_beds24_quarter_candidates', 'beds24_stage', 'beds24_create_member',
    'beds24_apply', 'run_data_retention', 'anonymize_member',
    'build_booking_calendar', 'build_wish_calendar', 'quarter_wish_counts',
    'wish_popularity_context', 'class_popularity_for_range', 'freest_slots',
    'entzerrung_barometer',
    'wish_deconfliction', 'wish_alternatives', 'wish_demand_grid',
    'capture_wish_snapshots',
    'day_detail', 'build_member_calendar', 'build_community_calendar',
    'build_occupancy_timeline', 'build_plan_print', 'build_external_calendar', 'week_agenda',
    'karma_distribution', 'community_stats',
    'run_period_lottery', '_restore_factors', 'confirm_lottery',
    'rollback_lottery', '_build_lottery_notices', 'run_fairness_simulation',
    'ensure_seed_commit', 'verify_period_lottery', 'lottery_retrospective',
    'wish_prognosis',
    '_renumber_wishes', 'add_wish', 'adjust_wish', 'move_wish', 'reorder_wishes',
    'delete_wish', 'wishes_editable', 'wish_demand_band',
    'wish_coordination', 'add_wish_for_member', 'WISH_EXPORT_COLUMNS', 'wish_export_rows',
    'book_spontaneous', 'add_waitlist_entry', 'waiters_for_allocation',
    'notify_waitlist_if_free', 'concurrent_allocations', 'free_quarters_for',
    'concurrent_split', 'create_swap_request', 'respond_swap_request',
    'pending_swaps_for', 'transfer_nights', 'thank_for_transfer',
    'cancel_allocation', '_broadcast_spontaneously_free', 'adjust_allocation',
    'notify_member_of_staff_booking', 'book_for_member',
    'POOL_ELIGIBLE_REMAINING', 'POOL_WITHDRAW_CAP_PER_YEAR',
    'pool_balance', 'pool_status', 'pool_donate', 'pool_withdraw',
    '_annotate_cleaning', '_ExtRow', '_external_confirmed',
    '_month_occupancy', 'dashboard_stats', 'quarter_occupancy_ampel', 'recent_booking_activity', 'arrivals_in_range',
    'departures_in_range', 'BOOKING_COLUMNS', 'booking_rows',
    'CLEANING_COLUMNS', 'cleaning_rows', 'bookings_text', 'cleaning_text',
    'notify_admins_upcoming', 'users_without_membership',
    'onboard_as_member', 'onboard_as_terminal', 'deactivate_account',
    'set_member_passive',
    'ensure_personal_membership', 'external_quote',
    'external_available_quarters', 'create_external_booking',
    'external_cancellation_preview', 'cancel_external_booking',
    'external_booking_by_token', 'guest_bookings_by_token',
    'cancel_external_booking_by_token',
    # Hofladen-Terminal (ADR 0053)
    'terminal_token_ok', 'terminal_payload', 'terminal_record',
    # Ausgelagerte Hilfetexte (ADR 0093)
    'HELP_SECTION_KEYS', 'help_sections',
    # Sperrzeit-Konflikte / Umbuchung / Ausgleich (ADR 0097)
    'block_min_notice_days', 'max_compensation_days', 'block_conflicts',
    'block_within_notice', 'suggest_block_window', 'relocation_options',
    'create_quarter_block', 'propose_relocation', 'respond_relocation',
    'cancel_with_apology', 'pending_relocation_requests', 'count_relocations_needed',
    # NL-Parser-Naht (ADR 0103/0108)
    'nl_stammdaten', 'nl_parse_wish', 'nl_parse_booking',
    # Gelerntes NL-Lexikon (ADR 0113, NL-L3)
    'nl_active_lexicon', 'active_lexicon_entries', 'apply_proposal',
    'reject_proposal', 'retire_entry',
    # Shadow-Auswertung / Golden-Wächter (ADR 0113, NL-L4)
    'nl_shadow_eval',
]
