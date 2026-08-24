# pilot-greenfield

## Intent

A command-line tool that reads a directory of Markdown notes and reports which
notes link to pages that do not exist. Recorded verbatim from the product
context supplied to run `6363a199`, which `artifact-policy.yml` names the
authoritative statement of intent.

## Users

| User | Uses it for |
|---|---|
| Someone keeping a personal wiki as plain Markdown on their own machine | finding which links point at nothing, before the wiki quietly rots |

## Constraints

| Constraint | Source | Status |
|---|---|---|
| Never modifies a note | supplied | **undecided (AR-19)** — a guarantee with no standing test is a claim |
| Under two seconds on ten thousand files | supplied | **unfalsifiable (AR-18)** — no corpus, hardware, or cache state fixed |
| Single binary | supplied | **undecided (AR-16)** — Python produces none natively |
| No server, no database | supplied | structural: the tool is a process that exits |
| Python | supplied | version, test runner, linter, packaging **undecided (AR-02)** |

## Definition of done

- Every broken link in the directory is reported. **Blocked** — which link
  forms count is undecided (AR-17), and that decides what "broken" means.
- No note is modified by any run. **Untestable today** (AR-19).
- Ten thousand files complete inside two seconds. **Unfalsifiable** until a
  corpus and hardware are fixed (AR-18).
- A link that resolves is never reported. No decision blocks this one.

## Non-goals

- Fixing the links it finds.
- Rendering, serving, or indexing the wiki.
- Any format other than Markdown.
- Following external URLs to see whether they resolve.
