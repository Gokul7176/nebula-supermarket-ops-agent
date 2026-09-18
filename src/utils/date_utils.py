from datetime import date, datetime, timedelta
from typing import Tuple, Optional

def resolve_single_date(input_date: Optional[str] = None, reference_date: Optional[date] = None) -> str:
    """
    Resolves a single date string or relative term ('today', 'yesterday') to YYYY-MM-DD.
    Defaults to reference_date (today) if omitted or relative.
    """
    ref = reference_date or date.today()
    if not input_date or not str(input_date).strip():
        return ref.strftime("%Y-%m-%d")
    
    val = str(input_date).strip().lower()
    if val in ["today", "today's", "current"]:
        return ref.strftime("%Y-%m-%d")
    elif val in ["yesterday", "yesterday's"]:
        return (ref - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Try parsing YYYY-MM-DD
    try:
        dt = datetime.strptime(val, "%Y-%m-%d").date()
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return ref.strftime("%Y-%m-%d")

def resolve_date_range(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    reference_date: Optional[date] = None
) -> Tuple[str, str]:
    """
    Deterministically computes (start_date_str, end_date_str) in YYYY-MM-DD format.
    Supports relative phrases ('today', 'this week', 'this_week', 'this month', 'yesterday', 'last week').
    Defaults to 'this week' (Monday of current week to Sunday of current week) if start_date is omitted or 'this week'.
    """
    ref = reference_date or date.today()

    s_raw = str(start_date).strip().lower() if start_date else ""
    e_raw = str(end_date).strip().lower() if end_date else ""

    # Check for relative keywords in start_date
    if not s_raw or "week" in s_raw or s_raw in ["this_week", "current_week"]:
        # "this week": Monday to Sunday of current week
        monday = ref - timedelta(days=ref.weekday())
        sunday = monday + timedelta(days=6)
        return monday.strftime("%Y-%m-%d"), sunday.strftime("%Y-%m-%d")
    
    if s_raw in ["today", "today's"]:
        return ref.strftime("%Y-%m-%d"), ref.strftime("%Y-%m-%d")
    
    if s_raw in ["yesterday", "yesterday's"]:
        yest = ref - timedelta(days=1)
        return yest.strftime("%Y-%m-%d"), yest.strftime("%Y-%m-%d")
    
    if "month" in s_raw or s_raw in ["this_month", "current_month"]:
        first_day = ref.replace(day=1)
        return first_day.strftime("%Y-%m-%d"), ref.strftime("%Y-%m-%d")
    
    if "last week" in s_raw or s_raw == "last_week":
        last_monday = (ref - timedelta(days=ref.weekday())) - timedelta(days=7)
        last_sunday = last_monday + timedelta(days=6)
        return last_monday.strftime("%Y-%m-%d"), last_sunday.strftime("%Y-%m-%d")

    # If start_date is explicit YYYY-MM-DD
    try:
        s_dt = datetime.strptime(s_raw, "%Y-%m-%d").date()
        s_str = s_dt.strftime("%Y-%m-%d")
    except ValueError:
        s_dt = ref - timedelta(days=ref.weekday())
        s_str = s_dt.strftime("%Y-%m-%d")

    # Determine end_date
    if not e_raw or e_raw in ["today", "today's"]:
        e_str = ref.strftime("%Y-%m-%d")
    else:
        try:
            e_dt = datetime.strptime(e_raw, "%Y-%m-%d").date()
            e_str = e_dt.strftime("%Y-%m-%d")
        except ValueError:
            e_str = ref.strftime("%Y-%m-%d")

    return s_str, e_str
