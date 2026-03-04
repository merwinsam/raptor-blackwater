"""Utility helpers"""


def format_currency(value: float) -> str:
    """Format a number as Indian Rupee currency string."""
    try:
        value = float(value)
        if value >= 0:
            return f"₹{value:,.0f}"
        else:
            return f"-₹{abs(value):,.0f}"
    except (TypeError, ValueError):
        return "₹0"


def format_pct(value: float) -> str:
    """Format a decimal fraction as a percentage string."""
    try:
        value = float(value)
        return f"{value * 100:.2f}%"
    except (TypeError, ValueError):
        return "0.00%"


def format_pts(value: float) -> str:
    """Format points value."""
    try:
        return f"{float(value):,.1f} pts"
    except (TypeError, ValueError):
        return "0.0 pts"


def color_pnl(value: float) -> str:
    """Return green/red hex color based on P&L sign."""
    return "#00ff88" if value >= 0 else "#ff4444"
