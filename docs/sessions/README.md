# Handoff docs: briefs for follow-up sessions

A handoff doc is a self-contained brief for one piece of work that a fresh session (or a person) picks up without the
conversation that produced it. Start a session with: "Read `docs/sessions/<file>.md` and do it."

## The workflow

1. **Write** one when work is found that belongs in its own session (a separate investigation, change or repository),
   instead of leaving it in chat. Copy the template below; name the file after the task (`kebab-case.md`); add it to
   *Open* below.
2. **Pick up**: the session reads the brief, sets `Status: in progress (<date>, <who or session name>)`, and works from
   it. It asks the owner where the brief is unclear rather than guessing.
3. **Close**: the result goes where it belongs (code, the issue doc, the backlog, RESULTS). The brief gets an
   `## Outcome` section (what was found or done, the commit, what is left), moves from *Open* to *Done* below, and is
   then deleted in a later tidy-up; git history keeps it.

A brief never holds the evidence itself: it links to the doc that does (an issue, the backlog, a results file), so the
evidence has one home.

## Template

```markdown
# Follow-up session: <task>

Status: open (written <date>). Evidence: <link to the issue / backlog / results doc>.

## Goal
<one paragraph: what to establish or build, and what not to do (for example: do not report upstream)>

## What is known
<the facts the session starts from, briefly, with links>

## Steps
1. ...

## Done means
<the observable end state: which doc says what, which test passes>

## Environment and constraints
<machine, paths, builds, models; the owner's standing rules: ask before downloads or installs, nothing leaves the
machine, no commits without the owner's go-ahead, one GPU job at a time>
```

## Open

| Brief | Task | Written |
|---|---|---|
| [qwen38-27b-cuda-isolation.md](qwen38-27b-cuda-isolation.md) | Isolate the Qwen3.8-27B UD-IQ3_XXS CUDA fault (which kernel, type and shape) | 2026-11-16 |
| [basalt-engine-start-and-followups.md](basalt-engine-start-and-followups.md) | Engine `start` command, Basalt 0.5.7 comparison, open measurements and follow-ups | 2026-11-24 |

Elsewhere: Sub0Squad's [docs/sessions/](https://github.com/CraigHutchinson/Sub0Squad/tree/main/docs/sessions) has the
brief for integrating this engine and the model registry into the squad.

## Done

(none yet)
