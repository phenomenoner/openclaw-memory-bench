# Public Release Checklist (openclaw-memory-bench)

Before switching repo visibility to public:

- [ ] Confirm no secrets in git history (`token`, `api_key`, `gateway_token`, etc.)
- [ ] Confirm `artifacts/` and `data/datasets/` remain gitignored
- [ ] Confirm no private absolute paths in committed docs that should be generalized
- [ ] Run lint/tests from clean tree:
  - `uv run --python 3.13 --with pytest -- pytest -q`
  - `uv run --python 3.13 --with ruff -- ruff check`
- [ ] Ensure `README.md` links to `PRELIMINARY_RESULTS.md`
- [ ] Ensure preliminary wording is explicit (avoid over-claim)
- [ ] Confirm license/acknowledgements are present (MIT + upstream inspiration)
- [ ] Optional: add repo topics (`openclaw`, `benchmark`, `memory`, `retrieval`)
