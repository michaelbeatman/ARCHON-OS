## Summary

Briefly describe what this PR changes and which milestone/issue it addresses.

## Checklist

- [ ] No hardcoded secrets, API keys, tokens, or personal file paths (`git grep` checked)
- [ ] Works on both `amd64` and `arm64` (Apple Silicon) where Docker/Compose is touched
- [ ] Bilingual (`en` / `de`) parity preserved if UI locales, SOUL profiles, or templates were modified
- [ ] Automated test suite passes (`python -m pytest tests/ -q`)
- [ ] JavaScript syntax checked (`node --check static/js/<modified>.js`)
