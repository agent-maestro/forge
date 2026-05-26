# Boundary Event Taxonomy

Status: active benchmark contract.

Forge labels each Optimization Boundary Lab sample with one event class:

| Event class | Trigger in benchmark harness | Research meaning |
| --- | --- | --- |
| `interior_sample` | no other class applies | ordinary finite interior sample |
| `corner_concentration` | max coordinate near cube face/corner | high-dimensional volume pressure |
| `domain_wall` | non-finite/domain failure without overflow pressure | input-domain violation |
| `overflow_wall` | domain failure with high evaluation pressure | non-finite numeric wall |
| `saturation_shelf` | finite sample hits clamp/saturation | output plateau |
| `phantom_attractor` | suspicious finite interior pressure band | precision-sensitive trap candidate |
| `guard_rescue` | raw mode would fail, guarded mode survives | guard preserved finite behavior |
| `log_domain_rescue` | raw mode would fail, log-domain candidate survives | positive-coordinate rescue |

The benchmark packet stores the class on each `trace_preview` frame and an
`event_counts` summary per run. This is the contract consumed by Course 006 and
mapped into MachLib obligations.
