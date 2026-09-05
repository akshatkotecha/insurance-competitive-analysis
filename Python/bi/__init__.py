"""Business-intelligence dashboard for the ABHI competitive-intelligence data.

Package layout
--------------
    data.py        connection, one-shot view loading, orderings, formatters
    insights.py    findings computed from the data, returned as Insight objects
    theme.py       palette and figure styling
    components.py  reusable card / table builders
    pages/         one module per route, registered via dash.register_page

Entry point is Python/bi_dashboard.py.
"""
