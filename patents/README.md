# Patents

> **Internal only.** Patent counts are NEVER displayed on public
> surfaces (monogate.org, monogate.dev, 1op.io, capcard.ai, blog,
> READMEs, footers). This directory documents the IP portfolio
> for internal reference, attorney review, and the
> patent-strengthening exercise.

## Layout

| Subdir | Contents |
|--------|----------|
| `filed/` | Provisional or full applications already filed |
| `pending/` | Drafts in attorney review or awaiting filing |
| `strategy/` | Filing timeline, prior art, licensing strategy |

## Master index

See `index.md` for the per-patent table (number, title, status,
date, related code).

## Cross-references in code

When code implements a patented method, include the patent
number in a comment header:

```python
def superbest_route(...):
    """SuperBEST routing -- Patents #01, #02, #08.

    [implementation]
    """
```

This makes the IP coverage visible to anyone reading the code
and helps the patent-strengthening review identify which methods
need claim updates as the implementation evolves.
