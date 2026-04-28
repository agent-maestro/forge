# Certification Partners

To make our Lean / SMT / CBMC verification artifacts useful for
regulated industries, we need partners who know each domain's
certification process intimately.

## Targets per standard

| Standard | Who certifies | Status |
|----------|---------------|--------|
| DO-178C (aerospace) | TBD partner — likely a DER (Designated Engineering Representative) | Not yet engaged |
| ISO 26262 (automotive) | TÜV / SGS / DEKRA | Not yet engaged |
| IEC 62304 + FDA 510(k) (medical) | Notified body + FDA consultant | Not yet engaged |
| MIL-STD-882 (defense) | Government PM office | Not yet engaged |
| IEC 61508 (industrial functional safety) | TÜV | Not yet engaged |
| NRC (nuclear) | Internal NRC review | Not yet engaged |

## What a partner does

1. Reviews our Lean theorem templates against the standard's
   evidence requirements
2. Validates that our `@verify` block output meets the standard's
   "proof of correctness" bar
3. Co-authors industry-specific guidance docs in
   `industries/<vertical>/certification/`
4. Becomes the named consultant the customer hires for the
   actual certification submission

## Engagement timing

After Phase 2 ships (Lean backend at M2.7) and we have a real
artifact to put in front of partners. Before that, conversations
are necessarily abstract.
