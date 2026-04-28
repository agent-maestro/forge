# Licensing Strategy

> Internal. The compiler is MIT-licensed; specific patented
> methods may require commercial licensing for re-implementation.

## Same model as GCC + x86

GCC is GPL-licensed and free to use. The x86 instruction set is
covered by Intel patents. Anyone can run GCC on x86 without a
license. Anyone re-implementing x86 needs to license it.

We use the same shape:
- `monogate-forge` itself is MIT — anyone can use, modify,
  distribute, and ship products built with it.
- The methods listed in `index.md` are patented by Monogate
  Research. Re-implementing those methods (vs using the
  Forge implementation) may require a license.

## Tiered offering (planned, not active)

1. **Free** — MIT compiler, all backends, all stdlib, no support.
2. **Pro** — paid support contract, priority bug fixes, certification
   guidance.
3. **Enterprise** — site license + custom industry verticals + ASIC tape-out
   support + indemnification.
4. **Silicon** — license to ship Forge-output ASICs commercially
   (covers patent #14 and related allocator methods).

## When to negotiate

- A customer wants to re-implement a patented method themselves
- A competitor hits a patent claim and wants to settle
- A regulated-industry customer wants indemnification on
  certified output

## Contact

For licensing inquiries: see CONTRIBUTING.md.
