# manufacturing

> Industry vertical scaffold. SCAFFOLD -- per-application `.eml`
> files and certification guides arrive as the vertical comes online.

**Certification target:** ISO 9001
**Typical chain orders:** 0-2 (mostly linear)

## Subdirectories

See `roadmap/industries/manufacturing.md` for the planned application list and
priority order.

## Adding an application

1. Pick the right subdirectory (or create one if the application
   doesn't fit existing categories)
2. Write a `<name>.eml` file with chain-order + domain + precision
   declarations
3. If certification-relevant, write a matching theorem in the
   subdirectory's `certification/` folder
4. Add a test in `tests/industry/test_manufacturing.py`

## Cross-references

- Patents touching this vertical: see `patents/index.md`
- Reference implementations (MATLAB / C / etc.) live in the user's
  domain-research folder, not here
