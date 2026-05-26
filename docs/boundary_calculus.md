# Boundary Calculus

Boundary calculus is the small algebra Forge uses to talk about high-dimensional
EML optimizer traces without pretending the trace is already a proof.

The atoms are boundary events:

- `interior_sample`
- `corner_concentration`
- `domain_wall`
- `overflow_wall`
- `saturation_shelf`
- `phantom_attractor`
- `guard_rescue`
- `log_domain_rescue`

A transition is an observed ordered pair:

```text
from_event -> to_event
```

## Composition

Transitions compose when the endpoint matches:

```text
(A -> B) ; (B -> C) = A -> C
```

Forge exposes this as `compose_transition("A->B", "B->C")`.

Composition is deliberately partial. `A->B` does not compose with `C->D` unless
`B == C`. That keeps packet summaries honest: a composed path must still be a
path actually witnessed by adjacent trace frames.

## Rescue Normal Form

The rescue-normal terminal events are:

- `interior_sample`
- `guard_rescue`
- `log_domain_rescue`

A path is rescue-normal when its final event is one of those classes. This is
not a claim that the optimizer has found the global optimum. It only says the
boundary dynamics ended in an event class that has a replay/proof direction:

```text
unsafe boundary event -> rescue-normal event -> MachLib obligation
```

## Unsafe Boundary Events

Forge currently treats these event classes as unsafe boundary events:

- `domain_wall`
- `overflow_wall`
- `saturation_shelf`
- `phantom_attractor`

The current named rescue operators are:

| Operator | Boundary transition | Obligation direction |
| --- | --- | --- |
| `log_domain_lift` | `domain_wall -> log_domain_rescue` | positive-coordinate preservation |
| `guard_clamp` | `overflow_wall -> guard_rescue` | output safety |
| `precision_escape` | `phantom_attractor -> interior_sample` | precision sensitivity |
| `saturation_deshelf` | `saturation_shelf -> corner_concentration` | clamp invariant |

`saturation_deshelf` is intentionally not rescue-normal by itself. It moves a
trace off a clamp shelf and back into measurable boundary concentration, where a
second operator can act.

## Research Boundary

This calculus is an evidence language. It is useful because the simulator,
Forge reports, and MachLib obligations can name the same event path. It is not
a semantic rewrite claim, not a hardware observation, and not a completed
formal proof.
