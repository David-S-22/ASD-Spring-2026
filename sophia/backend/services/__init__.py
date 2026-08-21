"""Business-logic layer shared by the JSON (/api/*) and HTML (/ui/*) routes.

Every function here takes and returns plain dicts, never a Flask request or
response, so both protocols call the same code instead of either
reimplementing the other.
"""
