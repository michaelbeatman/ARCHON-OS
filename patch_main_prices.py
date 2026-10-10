import os

p = '/app/main.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace(
    '        from core_skills_engine import _get_state_db\n        with _get_state_db() as conn:',
    '        with _get_state_db() as conn:'
)

with open(p, 'w', encoding='utf-8') as f:
    f.write(c)
