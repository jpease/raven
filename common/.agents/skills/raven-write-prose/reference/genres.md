# Genre

The fourteen tells are one set, but which of them can fire depends entirely on
what you are writing: procedures fire 1 to 3 tells each, a conceptual spec can
fire 10, essays fire more still, and code comments produce almost no prose
findings at all.

Read the row for what you are writing before running the tells.

| genre | what it is for | dominant failure | tells that cannot fire |
|---|---|---|---|
| code comment | why this, over the alternative a reader would otherwise restore | the comment no longer describes the code | heading, bulletification, restating close |
| docstring | the contract: arguments, raises, guarantees, invariants, one example | drifting into why, or promising behavior the function lacks | heading, bulletification |
| README | what it is, who it is for, why it exists, the first command | becoming reference material | — |
| tutorial | a first run that works, start to finish | explaining — the lesson stops to teach the model | symmetric hedge, no specifics, bulletification |
| how-to | one task, for a reader who already knows the subject | teaching something the task does not need | symmetric hedge, no specifics, bulletification, restating close |
| reference | names, types, defaults, errors, versions | arguing, or drifting into how-to | symmetric hedge, `not X, but Y`, no specifics, closing flourish |
| design doc, spec | the decision, and what it rules out | restating the requirement as though deciding it | `not X, but Y`, symmetric hedge, restating close |
| essay, blog post | an argument someone could disagree with | scaffolding: signposting, rhetorical closes | no specifics |
| commit subject, issue title | what changed, in one line a reader can scan | a tag that rates the work — "measured, not inferred" | heading, bulletification, restating close, closing flourish |

## Code comments

The most valuable test on a comment is not a prose test. Comments contradicted
by the code beside them are the dominant failure — a docstring describing
behavior a later fix removed, a rule stated directly above the constant that
violates it, a module docstring claiming parity that the same file denies
twice.

So run this first, before any tell: **does this comment still describe what the
code does?** A stale comment is worse than no comment, because it is evidence.
One asserted a `git` option "carries no short letter" when it does, and that
false assertion was the reason a guard checked only half its input.

Two mechanical checks answer that question cheaply:

- **An identifier in backticks that the file does not define.** One docstring
  promised a height capped to ``_BAR_MAX_HEIGHT``; the constant is
  ``_BAR_MAX_H``, and no such name had ever existed.
- **A count or a superlative.** "Seventeen files here are past 2000 lines,
  topping out at `<name>.py`" went stale inside the branch that wrote it —
  seventeen at the base, eighteen at the tip — and the superlative half was
  wrong the day it was typed, naming a file 2857 lines short of the largest.
  Make the number reproducible by naming the command that produces it, or drop
  the number.

Then the genre rule: the code states what. The comment states why, and the test
is whether a reader who deleted the code's non-obvious choice would put it back.

Two failure shapes worth naming:

**Restating the line below.** `# increment the counter` above `counter += 1`.
Catch it with the throat-clearing test.

**Comment as changelog.** "This used to be X, which broke when Y." Concrete on
the day it is written and decaying from then on, because it describes a bug no
current reader can observe. This recurs, and can decay further into the first
kind of error: a comment that no longer matches the code beside it.

**The example nobody runs.** A worked example is checked by a doctest runner or
by nothing, and the difference shows. One repo carried 39 examples under the two
trees its `python -m doctest` gate covered and 39 under a tree nothing collected
— `testpaths = tests`, no `--doctest-modules`. Every example-shaped defect found
was in the uncollected half, among them `_effective_bar_width(10, 52)  # -> 4`
for a function returning 3, with arithmetic beside it summing to 56 against a
52-pixel budget. Form is a hint and the runner is the fact: 24 of the
uncollected examples were already in `>>>` form, which buys nothing where
nothing collects it. Find out what executes an example before trusting it, and
verify by hand the ones nothing does.

What good looks like, from the same corpus: a comment naming the exact misfire
a change would cause, with the value or version that proves it. "Listing GNU's
optional-argument forms would hand back `-rf /` and match nothing" is not
derivable from the constant it sits above, which is the whole point.

## Docstrings

A docstring is a contract, so the reader is deciding whether to call the thing.
Give arguments, what it raises, what it guarantees. Push the reasoning down into
a comment where the reasoning lives.

The failure to watch is promising more than the code does. One docstring in the
reviewed corpus offered a fallback path the function returned before ever
reaching.

Two items from Rust's API guidelines carry into any language. **C-EXAMPLE**:
every public item gets an example that exercises it. **C-FAILURE**: what it
raises, what it panics on, and what makes it unsafe get their own section
rather than a clause in the summary. Rust can hold C-EXAMPLE to every public
item because rustdoc compiles and runs doc examples as tests by default — the
same difference "The example nobody runs" above turns on, made structural.

## READMEs

Orientation, not reference: what this is, who it is for, and the first command
that works. Every detail you add pushes the first command further down.

Link the reference material rather than inlining it. A README that answers every
question has stopped answering the first one.

Two things go missing at scale. Prana and colleagues hand-labelled 4,226
sections across 393 READMEs: what and how are well covered, purpose and status
are thin. Say why the project exists and what state it is in — alpha,
maintained, archived — near the top, where someone deciding whether to use it
is looking.

## Tutorials, how-to guides, and reference

Three genres, one failure between them: writing in the wrong mode. A tutorial
that stops to explain the data model, a how-to that recaps what the tutorial
covered, a reference page that argues for a design — each is competent prose
doing a job the reader did not open the page for. Diátaxis names the split, and
Django's docs were built on it before it had a name.

- **Tutorial**: the reader has not done this before. Everything is stated, in
  order, and it works from a clean checkout. Cut every choice you can; a branch
  point is a place to fail.
- **How-to**: the reader knows the subject and has a task. Start at the task.
- **Reference**: the reader is checking a fact. Names, types, defaults, errors,
  versions, and no argument.

Bulletification cannot fire in any of the three. Morkes and Nielsen measured a
page rewritten for scanning at 47% higher usability, written concisely at 58%,
and written objectively rather than promotionally at 27% — 124% with all three.
The tell is a finding about essays and design docs, where a bulleted list
stands in for an argument. In a procedure the list is the argument.

That 27% is also what the stakes-inflation tell rests on: promotional wording
measured worse than plain wording on the same content.

## Design docs and specs

The reason to write one is the decision — what was chosen and what that rules
out. Restating the requirement in the decision's place is the common failure,
and it reads as settled work when nothing was settled.

Three tells cannot fire here and a zero from them means nothing: specs carry no
argument to build antithesis or hedging out of, and they close on a table or an
open-questions list, which always holds new facts.

## Commit subjects and issue titles

A title is one line and holds no paragraphs, so four of the fourteen tells have
nothing to fire on. What is left is the tag: `X, not Y` hung off the end.

The tag earns its place when the negated half names what the change replaced —
`not cwd`, `not the checked-out branch` — because a reader who knew the old
behavior needs telling it is gone. It does not when the negated half rates how
the work was done: "measured, not inferred", "verified, not assumed", "earned,
not claimed". Nobody was going to assume otherwise, so the tag adds no fact and
reads as self-congratulation. This one was reported from outside, on an issue
an agent filed after loading these rules, which is why it now has a row.
The measurement behind it is in `SKILL.md` under the `not X, but Y` tell.

A title that needs the method is a title missing a number: "measured across
nine documents" beats both versions.
