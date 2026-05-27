# Documentation

| Folder | Purpose |
|---|---|
| [`arch/`](./arch/) | Architecture Decision Records (ADRs) — *why* each significant decision was made, what we considered, and what we accepted in return |
| [`guides/`](./guides/) | Informal walkthroughs for tasks that touch multiple parts of the system — local dev, recovery from partial failures, conventions |

## What goes where

| If you're looking for… | Look here |
|---|---|
| File / directory layouts (the *what* of the code) | The README next to the code (`infra/README.md`, `infra/bootstrap/README.md`) |
| How a specific resource was set up and why it exists | `infra/bootstrap/README.md` |
| Why we chose approach X over approach Y | [`docs/arch/adr-NNNN-...`](./arch/) |
| Commands to run a specific task | `infra/Makefile` (run `make help`) or [`docs/guides/`](./guides/) |
| Recovery steps when something has gone wrong | [`docs/guides/`](./guides/) |

ADRs are *immutable* once merged — a superseding decision gets a new ADR that
references the older one. Guides are *living* documents and are updated in
place.
