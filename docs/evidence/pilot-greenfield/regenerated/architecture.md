# Architecture

Structure follows arc42, tailored. Architectural decisions are delegated to
`docs/decisions/`, which arc42 section 9 permits.

## Context and scope

A process a person runs against a directory. It reads Markdown files and writes
a report to standard output. It talks to no network, no database, and no other
process, which is what the "no server, no database" constraint means in
practice.

## Building blocks

**Intended, not observed.** No product code exists yet; bootstrap stopped at
startable work, which `AC-GREENFIELD-007` requires. Each row is a proposal
until the first Story lands.

| Block | Responsibility |
|---|---|
| Walker | yields every Markdown file under the root, once |
| Link extractor | pulls link targets out of one note's text |
| Resolver | decides whether a target exists |
| Reporter | writes what did not resolve |

The split exists so the resolver can be decided late: AR-17 has not settled
what a link is, and only the resolver depends on that answer.

## Solution strategy

Owner: unassigned. These are suggestions until a name is supplied.

1. The walker never opens a file for writing. The read-only guarantee (AR-19)
   is structural or it is a promise.
2. The resolver is the only block that knows link syntax, so AR-17 changes one
   block rather than four.
3. Reporting is separate from walking, so ten thousand files can be measured
   (AR-18) without the report in the way.

## Risks and technical debt

| Risk | Cost |
|---|---|
| AR-17 undecided | the core behaviour is undefined; any Story written now is guesswork |
| AR-02 undecided | no verification command exists, so the first delivery fails at a shell step |
| AR-19 undecided | the read-only guarantee has no test, so a regression is invisible |
| AR-18 unfalsifiable | the performance budget reports a pass by default |
| No `.github/`, no CI | nothing runs on a push |

## Seams

Not an arc42 section; kept because arc42 has no equivalent.

| Seam | Enables |
|---|---|
| Resolver as a separate block | AR-17 can be answered without touching the walker |
| Walker yielding paths | a corpus can be faked for AR-18 without a filesystem |
| Reporter taking a list | output format is decided late and tested without I/O |
