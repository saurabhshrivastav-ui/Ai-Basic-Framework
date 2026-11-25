# AI Automation Framework - Phase 1

A working, runnable slice of the 15-agent framework described in the
original spec: plain-English requirement in, a real Playwright test
suite out, running against a live demo shopping site (SauceDemo).

Nothing here calls a real AI model yet (see "About the 'AI' part"
below) - every "agent" uses plain, readable Python rules today, with a
single, clearly marked spot to plug in a real AI model later.

---

## 1. The big picture (read this first)

Think of the whole framework as a restaurant kitchen with several
stations, and a head chef who carries the plate from one station to
the next:

```
 plain-English         Agent 1        Agent 2         Agent 3        Agent 4         Agent 5
 requirement    ---> Requirement --> Business Rule --> Scenario --> Test Case --> Test Data
 (you write this)      Agent           Agent            Agent         Agent          Agent
                    (understands   (finds hidden     (imagines    (writes exact   (creates the
                     what you       rules: "must,      every way    step-by-step    real usernames/
                     asked for)     required...")      it could      recipes)        passwords/etc
                                                        go wrong)                     needed)
```

`agents/orchestrator.py` is the "head chef" - it just calls the five
agents above in order and saves what comes out into `data/`.

Once you have test cases and test data, a SEPARATE set of pieces turns
them into something that actually clicks around a real website:

```
 pages/*.py        -> Page Objects: one file per screen (login,
                       cart, checkout...), each with reusable methods
                       like login(username, password). No assertions
                       live here - see pages/base_page.py.

 locators/*.json   -> Agent 7's output: for every button/box on every
                       screen, up to 5 different ways to find it,
                       ranked from most to least reliable.

 self_healing/     -> Agent 11: when a page object asks for an
   resolver.py         element, this tries each of those 5 ways in
                        order, and LOGS it whenever it had to fall
                        back past the #1 choice - so a human can
                        notice and fix the underlying locator later.

 tests/smoke/      -> Agent 8 + Agent 9's output: the actual pytest
   test_purchase_      test file. This is the ONLY file in the whole
   flow.py             framework that contains `assert` - checking
                        whether something is correct is the test's
                        job, nobody else's.

 conftest.py       -> Agent 8's "Fixtures": wires a real browser tab
                       into every test, builds the right page objects
                       automatically, and screenshots the page the
                       moment any test fails.

 agents/           -> Agent 15: after a test run, rolls up the
   reporting_agent.py  Allure results into a short, manager-readable
                        summary (pass/fail counts + "automation
                        health %").

 agents/           -> Agent 10: a static "code reviewer" - reads
   review_agent.py      pages/*.py and tests/**/*.py and checks POM
                         compliance, naming, reusability, stability and
                         maintainability, without needing to run a
                         single test.

 agents/           -> Agent 13: reads a failed test's Allure result +
   root_cause_          self_healing/healing_log.json and guesses WHY
   agent.py              it failed, with a confidence score and a
                         suggested fix.

 agents/           -> Agent 14: reads healing_log.json for locators
   auto_repair_          that keep needing a fallback, and either
   agent.py              auto-repairs locators/*.json (confidence >90%)
                         or queues the fix for a human to confirm.
```

---

## 2. What is ACTUALLY built and working right now

| #  | Agent                   | Status                                                                              | Where                                                  |
| -- | ----------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------ |
| 1  | Requirement Agent       | Working (rule-based)                                                                | `agents/requirement_agent.py`                        |
| 2  | Business Rule Agent     | Working (rule-based)                                                                | `agents/business_rule_agent.py`                      |
| 3  | Scenario Agent          | Working (rule-based)                                                                | `agents/scenario_agent.py`                           |
| 4  | Test Case Agent         | Working (rule-based)                                                                | `agents/test_case_agent.py`                          |
| 5  | Test Data Agent         | Working                                                                             | `agents/test_data_agent.py`                          |
| 6  | Page Object Agent       | Working (hand-authored output)                                                      | `pages/*.py`                                         |
| 7  | Locator Agent           | Working (hand-authored output)                                                      | `locators/*.json`                                    |
| 8  | Playwright Script Agent | Working (hand-authored output)                                                      | `tests/smoke/test_purchase_flow.py`, `conftest.py` |
| 9  | Assertion Agent         | Working (hand-authored output)                                                      | same test file                                         |
| 10 | Review Agent            | Working (rule-based,`ast`-powered static checks)                                  | `agents/review_agent.py`                             |
| 11 | Self-Healing Agent      | Working (real fallback logic, proven - see below)                                   | `self_healing/resolver.py`                           |
| 13 | Root Cause Agent        | Working (rule-based pattern matching + healing-log correlation)                     | `agents/root_cause_agent.py`                         |
| 14 | Auto Repair Agent       | Working (rule-based; auto-applies above 90% confidence, else queues for review)     | `agents/auto_repair_agent.py`                        |
| 15 | Reporting Agent         | Working                                                                             | `agents/reporting_agent.py`                          |
| 12 | Execution Agent         | Partly covered by pytest itself; trace/video collection not wired up                | -                                                      |
| -  | RAG Agent               | **Not built yet** (Phase 3) - see `rag/README.md` for why and what it needs | -                                                      |

"Rule-based" means: readable Python `if`/`for` logic instead of a real
AI model. Every one of those files calls `ai_client.complete(...)`
first and falls back to its own rules - so turning on a real AI model
later (see section 5) improves all of them at once, with zero changes
to any other file.

**Honest limitation on Agents 13/14:** the full spec describes Agent 11
comparing DOM structure, nearby elements, text and *visual* similarity
(steps 2-6) before deciding a locator healed, and Agent 13 reading
Console/Network/DOM data, not just the error message. This Phase 1
build only has the signals it can honestly capture without a live AI
model or a running browser at analysis time: the error message/trace
Allure already saves, and the self-healing fallback log. Both agents
are built so a real AI model (section 5) slots into the same
`ai_client.complete()` call every other agent already uses - see the
docstring at the top of each file for exactly what's simplified today.

---

## 3. How to run it

```bash
# 1. Install Python packages
pip install -r requirements.txt

# 2. Download the actual browser binary Playwright drives
python -m playwright install chromium

# 3. Turn your business requirement into test cases + test data
python agents/orchestrator.py
#    -> writes data/test_cases.json, data/test_data.json,
#       data/pipeline_output.json

# 4. Run the real browser tests
python -m pytest tests/smoke -v
#    add --headed to WATCH the browser click around instead of
#    running invisibly, e.g.:  python -m pytest tests/smoke -v --headed

# 5. Turn the test results into a manager-readable summary
python agents/reporting_agent.py
#    -> prints, and writes, reports/business_summary.txt

# 6. (Any time) Statically review the generated code for style/POM issues
python agents/review_agent.py
#    -> prints, and writes, reports/review_report.txt (+ .json)

# 7. If step 4 had failures, find out why
python agents/root_cause_agent.py
#    -> prints, and writes, reports/root_cause_report.txt (+ .json)

# 8. Auto-repair any locator that keeps needing a fallback
python agents/auto_repair_agent.py
#    -> prints, and writes, reports/auto_repair_report.txt;
#       edits locators/*.json directly when confidence > 90%
```

To see a proper, clickable Allure report (not just raw JSON) instead of
the plain text summary, install the separate Allure command-line tool
once (`npm install -g allure-commandline`, or see
https://allurereport.org/docs/install/), then run:

```bash
allure serve reports/allure-results
```

### A note on the exact selectors used

This project was built and validated inside a sandboxed environment
that could not reach the public internet - only local addresses and a
few package registries. So the CSS/data-test selectors in
`locators/*.json` are based on strong, well-documented knowledge of
SauceDemo's long-stable page structure, but they were **not**
confirmed against the live site directly. Instead, every page object,
fixture, and self-healing fallback was validated against a local mock
of the same page structure (login form -> product list -> cart ->
checkout -> confirmation) - proving the *mechanics* genuinely work.

**The first time you run `pytest tests/smoke -v --headed` against the
real `https://www.saucedemo.com/`, watch it once.** If SauceDemo has
changed anything since this was written, two things make that easy to
fix:

1. `self_healing/healing_log.json` will show exactly which elements
   had to fall back past their #1 locator - that tells you precisely
   what to update in `locators/*.json`.
2. Nothing else in the framework needs to change - locators are the
   only file that ever needs editing. Or just run
   `python agents/auto_repair_agent.py` and let it do that for you.

**Update (Agents 10/13/14 added):** re-verified in a second sandboxed
session - still no public internet access here, so `pytest` still
can't reach the real SauceDemo from inside this environment (it fails
at the network call with `ERR_TUNNEL_CONNECTION_FAILED`, after every
fixture, page object and browser launch worked correctly). The three
new agents were each proven against REAL data already sitting in this
project, not just syntax-checked: Agent 10 found 14 genuine (low
severity - missing docstrings) issues in the existing `pages/*.py`;
Agent 13 correctly diagnosed the sandbox's own network failure as
"Network Error" at 90% confidence; Agent 14 correctly found nothing to
repair against the real (healthy) healing log, and was separately
proven end-to-end by temporarily injecting a fake high-confidence
fallback event, confirming it edits `locators/*.json` and
`self_healing/repair_log.json` exactly as designed, before that test
data was removed again. **On your own machine, with real internet
access, step 4 above will actually reach saucedemo.com.**

---

## 4. Configuration (never hardcode URLs or credentials)

Copy `.env.example` to `.env` and edit as needed:

```bash
cp .env.example .env
```

Every URL, browser choice, and timeout comes from `utils/config.py`,
which reads `.env`. No test file or page object ever has a URL typed
directly into it - that's what the spec's "Automation Standards"
section calls "never hardcode credentials/URLs."

---

## 5. Turning on a real AI model later (Phase 2)

Today, `AI_PROVIDER=none` in `.env`, and every agent uses its
rule-based fallback. To wire in a real model (Azure OpenAI, Gemini,
anything with a chat-completion API):

1. Open `utils/ai_client.py`.
2. Fill in the body of `AIClient.complete()` - there's a ready-to-adapt
   Azure OpenAI example in that file's class docstring.
3. Set `AI_PROVIDER` (and whatever API key/endpoint variables you add)
   in `.env`.

Nothing else changes. Every agent already calls `ai_client.complete()`
first and only falls back to its own rules when that returns `None`.

---

## 6. Roadmap (Phase 2 and beyond)

Agents 10, 13 and 14 are now built (rule-based, Phase 1 style - see
section 2). In rough order of what unlocks the most value next:

1. **Wire in a real AI model** (section 5) - the single biggest
   upgrade, since it improves every rule-based agent at once (1-5, 10,
   13, 14), and unlocks generating NEW page objects/tests for
   requirements this framework has never seen, instead of just the one
   demo flow built here.
2. **Give Agent 13 real trace/console/network evidence** - wire up
   Playwright's tracing (`context.tracing.start(...)`) and console/
   network event listeners so Root Cause Agent has more than just the
   error message and the healing log to reason about.
3. **Let Agent 14 discover brand-new selector values** - today it can
   only re-rank locator strategies it already has stored for an
   element; teaching it to inspect a live DOM (or a screenshot, via a
   real AI model) would let it propose a locator it has never seen
   before, not just promote an existing fallback.
4. **RAG layer** - see `rag/README.md`.
5. **More flows** - right now this framework only knows one business
   flow (login -> add to cart -> checkout) against one app
   (SauceDemo). Adding a new flow means: write a new plain-English
   requirement, run `agents/orchestrator.py` on it, then add the
   matching page object(s)/locator file(s)/test file, following the
   exact same pattern as the SauceDemo ones.
6. **Agent 12 (Execution Agent)** - wire up trace/video collection on
   top of what pytest + the failure-screenshot hook in `conftest.py`
   already do.

---

## 7. Quick command cheat-sheet (for revision)

```bash
# Full pipeline, one shot (plan -> run -> report -> review -> diagnose -> repair)
python agents/orchestrator.py \
  && python -m pytest tests/smoke -v \
  && python agents/reporting_agent.py \
  && python agents/review_agent.py \
  && python agents/root_cause_agent.py \
  && python agents/auto_repair_agent.py

# Only smoke tests (fast, high-value)
python -m pytest -m smoke -v

# Only regression tests
python -m pytest -m regression -v

# Watch the browser instead of running invisibly
python -m pytest tests/smoke -v --headed

# Where things land
data/test_cases.json           # Agent 4 output
data/test_data.json            # Agent 5 output
locators/*.json                # Agent 7 output (Agent 14 edits this in place)
self_healing/healing_log.json  # Agent 11's fallback history
self_healing/repair_log.json   # Agent 14's audit trail of every auto-repair
reports/business_summary.txt   # Agent 15 output
reports/review_report.txt      # Agent 10 output
reports/root_cause_report.txt  # Agent 13 output
reports/auto_repair_report.txt # Agent 14 output
screenshots/                   # auto-saved on any test failure
reports/framework.log          # every agent's log lines, in one file
```

## 8. Folder structure

```
# AI Automation Framework - Phase 1

A working, runnable slice of the 15-agent framework described in the
original spec: plain-English requirement in, a real Playwright test
suite out - complete with real live-website locator discovery, real
Page Object Model code generation, a real (lexical) RAG layer, and
self-healing locators.

Nothing calls a real AI model yet (see "About the 'AI' part" below) -
every "agent" uses plain, readable Python rules today, with a single,
clearly marked spot to plug a real AI model into later.

---

## 1. The big picture (read this first)

This project actually has **two flows**, because they answer two
different questions. Think of a bakery: Flow A is the one demo cake the
bakery already knows how to make from memory (prove the oven works).
Flow B is the NEW conveyor belt - a customer describes ANY cake in
plain English, and the bakery figures out the recipe, bakes it, and
hands it over, all by itself.

### Flow A - the original one-app demo (still here, still passing)

```
 plain-English         Agent 1        Agent 2         Agent 3        Agent 4         Agent 5
 requirement    ---> Requirement --> Business Rule --> Scenario --> Test Case --> Test Data
 (you write this)      Agent           Agent            Agent         Agent          Agent
```
`agents/orchestrator.py` runs these five in order against ONE hardcoded
requirement and saves the result to `data/`. `pages/*.py`,
`locators/*.json` and `tests/smoke/test_purchase_flow.py` are
hand-written (by an earlier "Agent 6/7/8" pass) for one app -
SauceDemo. This is the original proof that the mechanics (page objects,
self-healing, fixtures, reporting) genuinely work.

### Flow B - the general story -> script pipeline (what you actually asked for)

```
 you write a story                    agent generates                agent DISCOVERS
 in plain English      ----------->   test cases, in     ---------->  real locators from
 (user_stories/*.txt)                 their OWN folder                the live website,
                                       (test_cases/<story>/)           then WRITES the
                                                                        Page Object classes
                                                                        (pages/*.py) - not
                                                                        hand-typed
                                                                              |
                                                                              v
                                                            agent WRITES a runnable test
                                                            script, matching each test-case
                                                            step to a real page-object method
                                                            (tests/generated/<story>/)
                                                                              |
                                                                              v
                                                                  YOU just run: pytest
```

This is the flow you described:
> user writes their story => agent generates test cases in a separate
> folder => agent writes scripts and generates POM files/folder => user
> runs the script

**You don't have to run the four steps below by hand - `agents/orchestrator.py`
(the "brain") chains all of them into one command, reading WHERE to
discover pages from straight out of your `.env` file's `BASE_URL` - see
section 2a.** The four steps are still explained individually below,
because that's what the brain is calling under the hood, and you may
want to run just one of them on its own sometimes (e.g. re-discover one
page without touching everything else).

Four files do this, in this exact order:

| Step | Agent | File | Reads | Writes |
|---|---|---|---|---|
| 1 | Locator Discovery (Agent 7) | `agents/locator_discovery_agent.py` | a **real URL** (opens an actual browser) | `locators/<story>/<page>_page.json` |
| 2 | Page Object Agent (Agent 6) | `agents/pom_generator_agent.py` | `locators/<story>/<page>_page.json` | `pages/<story>/<page>_page.py` (+ `.manifest.json`) |
| 3 | Story -> Test Cases | `agents/test_case_pipeline.py` | `user_stories/<story>.txt` | `test_cases/<story>/*.json` |
| 4 | Script Writer (Agent 8) | `agents/script_writer_agent.py` | `test_cases/<story>/test_cases.json` + every `pages/<story>/*.py` | `tests/generated/<story>/test_<story>.py` (+ its own `conftest.py`) |

Steps 1-2 only need to run **once per page, per story** (or again if the
real site changes). Steps 3-4 run **once per story**. Every generated
script reuses whatever pages already exist for THAT story under
`pages/<story>/` - it never re-discovers or re-generates a page it
already has, and it never looks at another story's pages.

**Every story gets its own folder, top to bottom - this is the
whole point.** Two stories can point at two completely different
websites (or the same one, twice), and can both have a page called
`login`, WITHOUT one overwriting the other's files:

```
locators/<story_A>/login_page.json     pages/<story_A>/login_page.py
locators/<story_B>/login_page.json     pages/<story_B>/login_page.py
test_cases/<story_A>/                  tests/generated/<story_A>/  (+ its own conftest.py)
test_cases/<story_B>/                  tests/generated/<story_B>/  (+ its own conftest.py)
```

**WHY a `conftest.py` per story, instead of one shared one?** pytest has
a rule built in: a `conftest.py` only hands out its fixtures to tests in
its OWN folder and below, and if two `conftest.py` files define a
fixture with the SAME name, the one closest to the test file wins. So
`tests/generated/<story_A>/conftest.py` only ever looks at
`pages/<story_A>/`, and `tests/generated/<story_B>/conftest.py` only
ever looks at `pages/<story_B>/` - two fixtures can both be named
`login_page` and never collide, because pytest never mixes them
together. `utils/fixture_factory.py` holds the actual scanning logic
(shared by this per-story `conftest.py` AND the project root's
`conftest.py`, which does the same thing for Flow A's hand-written
`pages/*.py`), so this rule only had to be written once.

**WHY split it into four small agents instead of one big one?** Same
reason a kitchen has a separate prep cook, grill cook and expediter
instead of one person doing everything: each agent has ONE job, is easy
to test on its own, and - most importantly - Agent 8 (script writer)
can be swapped for a smarter one later (see section 5) without touching
how locators are discovered or pages are built.

---

## 2. Flow B, step by step (the part you asked about)

### 2a. The easy way: let the brain do all of it

```bash
# .env:  BASE_URL=https://your-real-site.com/

# Simplest case - your story's flow never leaves BASE_URL's own page,
# or every page it needs already exists in pages/:
python agents/orchestrator.py --story login_checkout

# Story also needs a page that only exists after logging in:
python agents/orchestrator.py --story login_checkout \
    --pages inventory:/inventory.html \
    --username standard_user --password secret_sauce

# Also run the generated test immediately when it's done:
python agents/orchestrator.py --story login_checkout --run

# The real site's HTML changed since you last discovered it - redo it:
python agents/orchestrator.py --story login_checkout --force-discover
```

**WHY read the URL from `.env` instead of typing `--url` every time?**
Same reason `utils/config.py` exists at all (section 8) - the spec says
never hardcode URLs, and typing the same URL on the command line every
single run is really just hardcoding it one command at a time. Set
`BASE_URL` once in `.env`, and the brain (`agents/orchestrator.py`,
`--story` mode) - and everything it calls - always knows where "the
real site" is.

**WHAT THE BRAIN ACTUALLY DOES, in order** (this is exactly steps 1-4
below, chained together for you):

1. **Entry page** - if `pages/<ENTRY_PAGE_NAME>_page.py` (default name:
   `login`) doesn't exist yet, discovers it from `BASE_URL` (Agent 7)
   and generates it (Agent 6). **Already exists? Skipped automatically**
   - the brain never redoes work it's already done, unless you pass
   `--force-discover`.
2. **Extra pages** (`--pages name:/path ...`) - any further page your
   story's flow needs beyond the entry page (e.g. one reached only
   after logging in). Same skip-if-exists rule applies to each one.
3. **Story -> test cases** - runs `agents/test_case_pipeline.py` for you.
4. **Test cases -> real script** - runs `agents/script_writer_agent.py`
   for you.
5. **(Only with `--run`)** actually executes the generated test with
   pytest. **Off by default on purpose** - a generated test can contain
   honest `# TODO` lines (see step 4's explanation below), and those
   deserve a quick glance before you trust them, the same way you'd
   skim a junior engineer's first draft before merging it.

This is why `.env` matters here specifically: point `BASE_URL` at a
completely different website, run the same command, and the brain
discovers and builds page objects for THAT site instead - zero code
changes.

### Step 1: discover real locators from a live website (Agent 7)

```bash
# A page anyone can reach directly - --story says WHICH story's
# folder to write into (locators/login_checkout/login_page.json):
python agents/locator_discovery_agent.py \
    --url https://www.saucedemo.com/ --page-name login --story login_checkout

# A page that only exists after logging in:
python agents/locator_discovery_agent.py \
    --url https://www.saucedemo.com/inventory.html --page-name inventory \
    --story login_checkout \
    --login-first --username standard_user --password secret_sauce
```

**WHY discover locators from a real browser instead of hand-typing
them?** Same reason a building inspector walks through the real house
with a clipboard instead of trusting an old blueprint - the blueprint
might be stale, but the real house never lies. This agent opens an
actual Playwright browser, visits the real URL, and reads the actual
HTML - so what it writes to `locators/<story>/<page>_page.json` is
always true *right now*, not "true as of whenever someone last typed it
in."

**WHY does `--story` matter here?** Two stories can each have a page
they'd both naturally call "login" - possibly on two totally different
websites. Without `--story`, the SECOND discovery would silently
overwrite the FIRST one's `locators/login_page.json`. With it, they
land in `locators/<story_A>/login_page.json` and
`locators/<story_B>/login_page.json` - two separate files that can
never collide. (Agent 7 also runs a quick word-overlap check across
ALL stories' already-discovered pages and prints a warning - never a
block - if a new page looks suspiciously similar to one that already
exists, in case you're about to duplicate work by accident.)

For each interactive element (button, input, link...) it captures FIVE
different ways to find it later (data-testid, ARIA role, visible text,
CSS, XPath) - see section 3 (self-healing) for why five, not one.

**`--login-first` note:** if the page you're discovering needs a login
first, this agent logs in through whatever locators the entry page
already has (guessing which are "username"/"password"/"submit" by
name) - it does NOT require the entry page to already have a
hand-written `.login()` method, so this works even for a page this
agent JUST discovered a moment ago, not only for the original
hand-written SauceDemo pages.

### Step 2: turn discovered locators into a real Page Object class (Agent 6)

```bash
python agents/pom_generator_agent.py --page login --entry-page login --story login_checkout
python agents/pom_generator_agent.py --page inventory --story login_checkout
# or generate every page THAT STORY has locators for but no .py file yet:
python agents/pom_generator_agent.py --story login_checkout
```

Just like Agent 7, `--story` is required here too, and for the same
reason: it writes to `pages/<story>/<page>_page.py`, not a shared
`pages/` folder, reading from that same story's
`locators/<story>/<page>_page.json`.

**WHY generate the class instead of writing it by hand?** Same reason a
furniture-assembly robot builds the cabinet once the measurements are
written down - it's mechanical, repetitive work a person shouldn't have
to redo for every button on every page. This agent reads
`locators/<page>_page.json` and, for every element, generates ONE
method based on what KIND of element it is:

| Element kind | Generated method | Example |
|---|---|---|
| button/link (click) | `def click_<name>(self) -> None` | `click_login_button()` |
| input/textbox (fill) | `def fill_<name>(self, value: str) -> None` | `fill_username_input("bob")` |
| checkbox/radio (toggle) | `def toggle_<name>(self) -> None` | `toggle_remember_me()` |
| text to read (assert later) | `def get_<name>_text(self) -> str` | `get_error_text()` |

Every generated method is a one-line call into `pages/base_page.py`
(`self.click(...)`, `self.fill(...)`, `self.text_of(...)`), so every
auto-generated page is self-healing for free (section 3) - no extra
code needed. **Safety rule:** this agent never overwrites a page object
that already exists, unless you pass `--force` - so it can never
silently clobber a hand-written page (like the original SauceDemo
ones).

### Step 3: turn your story into test cases (Agents 1, 2, 3, 4, 5 - reused)

```bash
python agents/test_case_pipeline.py user_stories/login_checkout.txt
```

Write a plain-English story as a `.txt` file in `user_stories/` (see
`user_stories/login_checkout.txt` for a real example already in this
project). This runs it through the SAME five agents `orchestrator.py`
uses (Requirement -> Business Rule -> Scenario -> Test Case -> Test
Data) - except every story gets its **own folder** under `test_cases/`,
named after the story:

```
test_cases/login_checkout/
├── requirement_analysis.json
├── business_rules.json
├── scenarios.json
├── test_cases.json        <- the actual step-by-step checklist
├── test_data.json         <- usernames/passwords/etc to use
├── rag_matches.json       <- "have we tested something like this before?"
└── pipeline_output.json   <- all of the above, combined
```

**WHY a separate folder per story?** So ten different stories never
overwrite each other, and Agent 8 (next step) knows exactly where to
find everything it needs just from the story's name.

### Step 4: write a runnable test script (Agent 8)

```bash
python agents/script_writer_agent.py login_checkout
# -> writes tests/generated/login_checkout/test_login_checkout.py
```

This is the trickiest agent, so it deserves the longest explanation.
**WHY is this hard?** A test case step is plain English ("Click the
Login button"). A page object method is Python
(`login_page.click_login_button()`). Something has to translate between
them - a computer doesn't automatically know those two things mean the
same thing.

**HOW it translates, honestly:** this is keyword matching, not real
language understanding (a real AI model - section 5 - would do this
step far better). For every test-case step, it compares the step's
words against every known page-object method's "trigger phrases"
(built either from `pages/*.manifest.json`, or - for hand-written pages
with no manifest - straight from the method's own name) and picks the
closest match, using the same word-overlap math the RAG layer uses (see
section 4). Two safety rules make this honest rather than silently
wrong:

1. **A step and a candidate method must share at least one REAL word** -
   not just filler words like "the"/"a", and not just a generic verb
   like "click" that appears in EVERY click-kind method's phrases.
   (A real bug this caught during testing: "Click the Login button" was
   once matching a totally unrelated "remove item from cart" method,
   purely because both phrases contained "click" and "the".)
2. **The same method is never matched twice in one test** - so a step
   like "Enter a valid password" can't accidentally trigger `login()` a
   *second* time after an earlier step already logged in (which would
   crash, since the page has moved on by then).

Below the match-confidence threshold, it leaves an honest
`# TODO: no confident match` instead of guessing - the same way you'd
leave a sticky note for a colleague rather than quietly do something
that might be wrong. **Every generated test is meant to be glanced over
before being trusted**, exactly like you'd review a junior engineer's
first draft - the confidence percentage is printed right next to every
matched line so you know exactly how sure the agent was.

### Step 5: you just run it

```bash
pytest tests/generated/login_checkout/ -v
```

Nothing special - it uses the exact same dynamic page-object fixtures
(see `conftest.py`) every other test in this project uses.

---

## 3. Self-healing locators (Agent 11) - unchanged, still real

**WHY 5 locator strategies per element, not 1?** A real website changes
constantly - a developer renames a CSS class, or removes a
`data-testid`. If a page object only knew ONE way to find the "Login"
button, that ONE change would break every test that touches it. Instead,
every element is captured with up to 5 fallback strategies, ranked
most-to-least reliable (`data-testid` > ARIA role > visible text > CSS
> XPath), and `self_healing/resolver.py` tries them **in order**,
picking the first one that actually finds something on screen -
logging it to `self_healing/healing_log.json` whenever it had to fall
back past strategy #1, so a human can notice and fix the real locator
later (or let `agents/auto_repair_agent.py` do it automatically above
90% confidence).

This applies equally to hand-written AND auto-generated page objects,
since both call the exact same `self.click()`/`self.fill()`/`self.text_of()`
helpers in `pages/base_page.py`.

---

## 4. RAG - "have we automated something like this before?" (built, Phase 1 style)

**WHY does a test framework need RAG at all?** Without it, every new
story risks silently re-testing something already covered, or a new
page getting re-discovered as if it were brand new when 90% of it
already exists. RAG is the librarian who's read everything the team has
ever written and can say "this sounds like the returns-policy test from
March" the instant you describe a new one.

**WHAT KIND of "AI" is this, honestly?** No API key, no internet, no
vector database needed - a real, working Phase 1 RAG using **lexical
(keyword) search**, scored with a simple, well-known formula called
Jaccard similarity:

```
similarity = (words both texts share) / (all words either text has)
```

"log in with valid credentials" vs "log in with a locked account" share
`{log, in, with}` out of 7 unique words total -> ~43% similar. Good
enough to flag "these are clearly related" - nowhere near as smart as a
real AI model that understands MEANING (which would also catch "sign
in" as similar to "log in", despite sharing zero words), but it costs
nothing to run.

All in `rag/knowledge_base.py` (see `rag/README.md` for full detail):

| Called by | When | What it checks |
|---|---|---|
| `test_case_pipeline.py` | before generating test cases for a new story | "does an existing test case already cover this?" |
| `locator_discovery_agent.py` / `pom_generator_agent.py` | before discovering/generating a page | "does a page with very similar elements already exist?" |

It never BLOCKS anything - it only warns, and writes matches to
`rag_matches.json` so a human decides whether it's genuinely new work.

---

## 5. What is ACTUALLY built and working right now

| # | Agent | Status | Where |
|---|-------|--------|-------|
| 1 | Requirement Agent | Working (rule-based) | `agents/requirement_agent.py` |
| 2 | Business Rule Agent | Working (rule-based) | `agents/business_rule_agent.py` |
| 3 | Scenario Agent | Working (rule-based) | `agents/scenario_agent.py` |
| 4 | Test Case Agent | Working (rule-based) | `agents/test_case_agent.py` |
| 5 | Test Data Agent | Working | `agents/test_data_agent.py` |
| 6 | Page Object Agent | **Working - REAL code generation from real locators** | `agents/pom_generator_agent.py` |
| 7 | Locator Agent | **Working - REAL live-browser DOM discovery** | `agents/locator_discovery_agent.py` |
| 8 | Playwright Script Agent | **Working - REAL step-to-method matching + script generation** | `agents/script_writer_agent.py` |
| 9 | Assertion Agent | Working (folded into Agent 8's output - every generated test ends with a real `assert`) | same file |
| 10 | Review Agent | Working (rule-based, `ast`-powered static checks) | `agents/review_agent.py` |
| 11 | Self-Healing Agent | Working (real fallback logic, proven) | `self_healing/resolver.py` |
| 13 | Root Cause Agent | Working (rule-based pattern matching + healing-log correlation) | `agents/root_cause_agent.py` |
| 14 | Auto Repair Agent | Working (auto-applies above 90% confidence, else queues for review) | `agents/auto_repair_agent.py` |
| 15 | Reporting Agent | Working | `agents/reporting_agent.py` |
| - | RAG Agent | **Working - real lexical (keyword) search, no API key needed** | `rag/knowledge_base.py` |
| 12 | Execution Agent | Partly covered by pytest itself; trace/video collection not wired up | - |

"Rule-based" means: readable Python `if`/`for` logic instead of a real
AI model. Every one of those files calls `ai_client.complete(...)`
first and falls back to its own rules - so turning on a real AI model
later (section 6) improves all of them at once, with zero changes to
any other file.

---

## 6. Proof this all genuinely works (not just "it compiles")

Both flows were verified for real, not just syntax-checked, using a
small local copy of the SauceDemo page structure (this sandbox can't
reach the public internet - only local addresses and package
registries - so this is the honest way to prove the *mechanics*):

- **Flow A** (`tests/smoke/test_purchase_flow.py`, hand-written pages):
  all 3 tests genuinely **pass** against a live local server - real
  browser, real self-healing resolver, real fixtures.
- **Flow B, steps 1-2** (Agent 7 + Agent 6): pointed at the SAME live
  local server with brand-new page names it had never seen, with **zero
  hand-typed locators** - it discovered the real `data-test` attributes
  by reading the DOM, generated working `pages/*.py` classes from them,
  and (using the generic `--login-first` fallback) logged in through a
  freshly-generated page object that had no hand-written `login()`
  method at all.
- **Flow B, steps 3-5** (story -> test cases -> script -> run): all 6
  auto-generated tests for the `login_checkout` story genuinely **pass**
  against the same live local server.
- **The brain** (`agents/orchestrator.py --story`): with `BASE_URL`
  pointed at the same live local server via `.env`/an environment
  variable, one single command genuinely discovered a brand-new entry
  page, discovered a second page that required logging in first (using
  a page object it had JUST generated, with no hand-written `login()`
  method), then generated test cases and a runnable script - all from
  one command, with the target site never typed anywhere except
  `BASE_URL`. It was also re-run against a site whose entry page ALREADY
  had a page object, confirming it correctly skips re-discovering work
  it's already done.
- **Per-story isolation (no collisions, proven with two real stories):**
  ran the brain twice, back to back, against the same live local server
  - once for `user_stories/login_checkout.txt` (discovering `login`,
  `inventory`, `cart`), once for a second, independent
  `user_stories/quick_reorder.txt` (discovering only `login` and
  `inventory`) - both using the SAME default entry-page name, `login`.
  Confirmed genuinely separate, non-colliding output:
    - `pages/login_checkout/login_page.py` and
      `pages/quick_reorder/login_page.py` exist side by side as two
      separate files (with two separate `locator_file` values baked in
      - `"login_checkout/login_page"` vs `"quick_reorder/login_page"`).
    - Running story 1 a second time (for story 2) never touched story
      1's files - `locators/login_checkout/login_page.json`'s checksum
      was identical before and after.
    - `pytest tests/generated/` (BOTH stories' folders, in ONE pytest
      session) collected all 12 tests with **zero fixture-name errors**
      - pytest resolved each test's `login_page`/`inventory_page`
      fixtures from the correct story's own `conftest.py` (the one
      closest to that test file), never the other story's.
    - Agent 7's cross-story similarity check correctly noticed and
      **warned** (never blocked) that `quick_reorder`'s `login`/
      `inventory` pages looked similar to `login_checkout`'s - proving
      the RAG index now tracks pages *per story*, not as one shared
      pool.
    - All **12 of 12 generated tests pass for real**, with ZERO manual
      edits needed. (An earlier pass of this proof had 3 honest
      failures here - two real, general bugs, found from a real user's
      first run against a real public site: (1) every auto-generated
      `fill_<x>(value)` method takes a parameter literally named
      `value` - meaningless on its own - so the old value-filler
      never found "standard_user" in `test_data.json` and left
      `CHANGE_ME`; (2) a single combined step like "Log in with valid
      credentials" had no method to match, because auto-discovered
      pages only ever get individual `fill_username_input`/
      `fill_password_input`/`click_login_button` methods, never a
      combined `login()`. Both are now fixed IN GENERAL, not just for
      this one site: `_semantic_key_for_element()` in
      `agents/script_writer_agent.py` guesses a field's real meaning
      from its DISCOVERED element name - "user-name" -> "username" -
      instead of trusting the generic Python parameter name; and
      `_try_composite_login()` auto-finds whichever page in a story
      looks like a login form - has a username field, a password
      field, and a submit-shaped button - and synthesizes the three
      real calls a "log in" sentence actually means, for any story, on
      any site.)

**On your own machine, with real internet access**, pointing `BASE_URL`
at `https://www.saucedemo.com/` (or any real site) works exactly the
same way - the only thing the sandbox couldn't do here was reach a
public URL.

---

## 7. How to run Flow A (the original one-app demo)

```bash
# 1. Install Python packages
pip install -r requirements.txt

# 2. Download the actual browser binary Playwright drives
python -m playwright install chromium

# 3. Turn the built-in requirement into test cases + test data
python agents/orchestrator.py

# 4. Run the real browser tests
python -m pytest tests/smoke -v
#    add --headed to WATCH the browser click around instead of
#    running invisibly

# 5. Turn the test results into a manager-readable summary
python agents/reporting_agent.py

# 6. (Any time) Statically review the generated code for style/POM issues
python agents/review_agent.py

# 7. If step 4 had failures, find out why
python agents/root_cause_agent.py

# 8. Auto-repair any locator that keeps needing a fallback
python agents/auto_repair_agent.py
```

To see a proper, clickable Allure report instead of plain text, install
the Allure command-line tool once (`npm install -g allure-commandline`,
or see https://allurereport.org/docs/install/), then run:

```bash
allure serve reports/allure-results
```

---

## 8. Configuration (never hardcode URLs or credentials)

Copy `.env.example` to `.env` and edit as needed:

```bash
cp .env.example .env
```

Every URL, browser choice, and timeout comes from `utils/config.py`,
which reads `.env`. No test file or page object ever has a URL typed
directly into it.

---

## 9. Turning on a real AI model later (Phase 2)

Today, `AI_PROVIDER=none` in `.env`, and every agent uses its
rule-based fallback (including RAG's keyword matching and Agent 8's
step-to-method matching). To wire in a real model:

1. Open `utils/ai_client.py`.
2. Fill in the body of `AIClient.complete()` - there's a ready-to-adapt
   example in that file's class docstring.
3. Set `AI_PROVIDER` (and whatever API key/endpoint variables you add)
   in `.env`.

Nothing else changes. Every agent already calls `ai_client.complete()`
first and only falls back to its own rules when that returns `None`.
For Agent 8 and RAG specifically, a real embedding model would replace
Jaccard word-overlap with real semantic understanding - the function
signatures are already the "socket" (`_best_method()` in
`agents/script_writer_agent.py`, `_score()` in `rag/knowledge_base.py`)
for that upgrade to slot into, with every caller unchanged.

---

## 10. Roadmap

1. **Wire in a real AI model** (section 9) - the single biggest
   upgrade, since it improves every rule-based agent at once, and would
   let Agent 8 correctly match awkwardly-phrased steps this version
   honestly can't.
2. **Give Agent 13 real trace/console/network evidence** - wire up
   Playwright's tracing and console/network event listeners.
3. **Let Agent 14 discover brand-new selector values**, not just
   re-rank locator strategies it already has stored.
4. **More stories** - Flow B already generalizes to any site and any
   story; just add more `.txt` files to `user_stories/`.
5. **Agent 12 (Execution Agent)** - wire up trace/video collection on
   top of what pytest + the failure-screenshot hook already do.

---

## 11. Quick command cheat-sheet (for revision)

```bash
# ---- Flow B, the easy way: the brain (set BASE_URL in .env first) ----
python agents/orchestrator.py --story <story>
python agents/orchestrator.py --story <story> --pages inventory:/inventory.html --username U --password P
python agents/orchestrator.py --story <story> --run              # also runs pytest at the end
python agents/orchestrator.py --story <story> --force-discover   # real site changed - rediscover

# ---- Flow B, the manual way: story -> real script, one step at a time ----
# --story on Agents 6/7 says WHICH story's folder to read/write - see
# the main isolation section above for why it's required, not optional.
python agents/locator_discovery_agent.py --url <URL> --page-name <name> --story <story>
python agents/pom_generator_agent.py --page <name> --entry-page <name> --story <story>   # only for the entry/login page
python agents/test_case_pipeline.py user_stories/<story>.txt
python agents/script_writer_agent.py <story>
pytest tests/generated/<story>/ -v

# ---- Flow A: the original one-app demo, one shot ----
python agents/orchestrator.py \
  && python -m pytest tests/smoke -v \
  && python agents/reporting_agent.py \
  && python agents/review_agent.py \
  && python agents/root_cause_agent.py \
  && python agents/auto_repair_agent.py

# Only smoke / regression tests
python -m pytest -m smoke -v
python -m pytest -m regression -v

# Watch the browser instead of running invisibly
python -m pytest tests/smoke -v --headed

# Where things land
user_stories/<story>.txt              # you write this
test_cases/<story>/*.json             # Flow B, Agents 1-5 output (per story)
locators/*.json                       # Flow A's hand-written pages read these (global)
locators/<story>/*.json               # Flow B - Agent 7 output, ONE FOLDER PER STORY
pages/*.py, *.manifest.json           # Flow A - hand-written pages (global)
pages/<story>/*.py, *.manifest.json   # Flow B - Agent 6 output, ONE FOLDER PER STORY
tests/generated/<story>/              # Flow B - Agent 8 output (test file + its own conftest.py)
rag/index/*.json                # RAG's knowledge base
self_healing/healing_log.json   # Agent 11's fallback history
self_healing/repair_log.json    # Agent 14's audit trail of every auto-repair
reports/business_summary.txt    # Agent 15 output
reports/review_report.txt       # Agent 10 output
reports/root_cause_report.txt   # Agent 13 output
reports/auto_repair_report.txt  # Agent 14 output
screenshots/                    # auto-saved on any test failure
reports/framework.log           # every agent's log lines, in one file
```

---

## 12. Folder structure

```
AI_AUTOMATION_FRAMEWORK/
├── user_stories/       Flow B - you write a plain-English story here
├── test_cases/         Flow B - Agent 4/5 output, ONE FOLDER PER STORY
│   └── <story>/        requirement_analysis.json, business_rules.json,
│                        scenarios.json, test_cases.json, test_data.json,
│                        rag_matches.json, pipeline_output.json
├── agents/              Agents 1-8, 10, 13, 14, 15 (the "brain",
│                         including agents/orchestrator.py)
├── pages/               Flow A - hand-written Page Object Model classes
│   └── <story>/          Flow B - Agent 6 output, ONE FOLDER PER STORY
│                          (+ *.manifest.json - trigger phrases for Agent 8)
├── locators/             Flow A's hand-written pages read these (global)
│   └── <story>/          Flow B - Agent 7 output, ONE FOLDER PER STORY
│                          (ranked locator strategies, JSON)
├── rag/                  RAG Agent - lexical knowledge base (see rag/README.md)
│   └── index/            *.json - what's been indexed so far, keyed
│                          "<story>:<page>" so stories never collide
├── self_healing/         Agent 11 - the fallback resolver + its log
│                          + Agent 14's repair_log.json
├── tests/
│   ├── smoke/            Flow A - hand-written, fast, high-value tests
│   ├── sanity/            broader "did I break the basics" tests
│   ├── regression/        full coverage (run before a release)
│   └── generated/         Flow B - Agent 8 output, ONE FOLDER PER STORY
│       └── <story>/        test_<story>.py + its OWN conftest.py
│                            (fixtures scoped to pages/<story>/ only)
├── data/                 Flow A - test_cases.json / test_data.json
├── reports/               Allure raw results + business_summary.txt
├── screenshots/           auto-saved failure screenshots
├── traces/, videos/       reserved for Phase 2's Execution Agent
├── utils/                 config.py, logger.py, ai_client.py (the AI "socket"),
│                           fixture_factory.py (shared dynamic-fixture logic)
├── conftest.py            root pytest fixtures - Flow A's GLOBAL pages/*.py
│                           only (test data, screenshot-on-failure hook).
│                           Delegates its page-fixture scanning to
│                           utils/fixture_factory.py - the SAME helper every
│                           per-story conftest.py (above) also uses.
├── pytest.ini
├── requirements.txt
├── .env                  BASE_URL, ENTRY_PAGE_NAME, DEMO_USERNAME/PASSWORD...
└── .env.example
```
```
#   A i - B a s i c - F r a m e w o r k  
 