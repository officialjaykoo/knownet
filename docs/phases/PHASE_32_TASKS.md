# Phase 32 Tasks: Workflow-First Operator UI

Status: in_progress
Created: 2026-05-08
Updated: 2026-05-08

Phase 31 moved KnowNet onto the clean DB v2 runtime. Phase 32 changes the web UI
from a feature checklist into an AI collaboration workbench.

The goal is not to make the app look decorative. The goal is to make the next
operator action obvious.

## Current Problem

The current UI grew around implementation surfaces:

```txt
Operator Console
Knowledge Map
Agent Dashboard
AI Reviews
AI Packets
Provider/maintenance panels
```

That mirrors the codebase, not the operator's workflow. It makes sense for
checking whether features exist, but it does not make it obvious what to do next.

KnowNet's product loop is now clearer:

```txt
Generate packet -> ask external AI -> import review -> triage findings ->
create/implement tasks -> submit evidence -> optionally export SARIF
```

The UI should follow that loop.

## Desktop Scope

Phase 32 targets the desktop operator app only.

```txt
Primary viewport: 1280px and wider
Minimum practical viewport: 1024px wide
Mobile layout: out of scope
```

Do not spend this phase designing mobile navigation, mobile sheet patterns, or
phone-width packet editing. The app is an operator workbench, and the target use
case is desktop.

## Fixed Rules

Do not:

- Add a marketing landing page.
- Add decorative cards, oversized hero sections, gradient blobs, or ornamental
  layout.
- Hide core actions behind vague dashboard labels.
- Add new backend product features during this phase.
- Reintroduce old v1 names such as `finding_tasks` or `ai_state_pages`.
- Make the UI depend on full release checks.
- Add a heavy design library dependency just to copy a visual style.

Do:

- Organize the app by operator workflow, not by backend module.
- Keep DB v2 vocabulary: `tasks`, `structured_state_pages`, `packets`,
  `reviews`, `findings`, `provider_runs`.
- Keep compact packet and SARIF concepts visible but not mixed together.
- Use Radix/shadcn-inspired design rules through local CSS primitives.
- Use icons consistently for commands and tabs where they improve scanning.
- Keep controls dense, stable, and predictable.
- Make disabled or blocked actions explain why.

## Target Information Architecture

Replace the current top-level mental model with:

```txt
Next
Packets
Reviews
Tasks
Sources
Ops
```

URL structure must match workspace keys:

```txt
/          -> redirect or default to /next
/next      -> Next workspace
/packets   -> Packets workspace
/reviews   -> Reviews workspace
/tasks     -> Tasks workspace
/sources   -> Sources workspace
/ops       -> Ops workspace
```

Browser back/forward, refresh, and bookmarks should preserve the active
workspace. Do not keep the selected workspace only in local component state.

### Next

Purpose:

```txt
Show the single best next action and one fallback.
```

Content:

- next-action card from `/api/collaboration/next-action`
- concise health / empty-state summary
- active packet or review reminder when present
- one primary action, one secondary action

Avoid:

- Full dashboards
- Long provider tables
- Knowledge map previews

### Packets

Purpose:

```txt
Create copy-ready external AI packets.
```

Content:

- target selector: Claude / Gemini / DeepSeek / Qwen / Kimi / MiniMax / GLM /
  all
- profile selector: overview / stability / performance / security /
  implementation / provider_review
- output mode selector: top_findings / decision_only / context_questions /
  implementation_candidates
- delta-from packet control
- quality warning acknowledgement
- generated packet body with copy action
- packet fitness and required-context summary

Avoid:

- Showing retired experiment packet workflows
- Showing internal schema detail by default

### Reviews

Purpose:

```txt
Turn external AI responses into structured reviews and findings.
```

Content:

- paste response
- dry-run parser
- import review
- parser errors and AI feedback prompt
- recent review inbox
- finding import summary

Avoid:

- Mixing implementation evidence submission into this screen

### Tasks

Purpose:

```txt
Convert accepted findings into implementation work and close the loop.
```

Content:

- open / in-progress / blocked / done tasks
- accepted findings without tasks
- implementation evidence form
- commit / changed files / verification note
- next-action route back to Next screen

Avoid:

- Old "finding task" naming
- Dense review markdown

### Sources

Purpose:

```txt
Inspect pages, node cards, snapshots, and knowledge context.
```

Content:

- page list / source detail
- node cards
- compact knowledge map or graph summary
- structured state preview using `structured_state_pages`

Avoid:

- Treating graph visualization as the primary product experience

### Ops

Purpose:

```txt
Diagnose system state only when something is wrong.
```

Content:

- health summary
- provider runs
- SARIF export readiness
- DB v2 status
- MCP status
- maintenance actions

Avoid:

- Making Ops the default first screen
- Running slow checks automatically

## P32-001 Navigation And Shell

Problem:

The current top navigation reads like a row of buttons and changes shape as
screens change.

Implementation shape:

```txt
- Add a stable app shell.
- Use a stable top tab bar for the six workspaces.
- Use route/workspace keys: next, packets, reviews, tasks, sources, ops.
- Keep each nav item width and height stable across active/inactive states.
- Make active state visually clear without changing layout size.
- Route / to /next or render the Next workspace by default.
```

Design rules:

- Navigation should look like navigation, not action buttons.
- Primary actions should use button styling.
- Selection controls should use segmented/tab styling.
- Status chips should not look like buttons.
- Active tab state must not change font weight, padding, or item width.
- Reserve active-state space with border color, background, or stable indicator
  instead of layout-changing typography.

Done when:

- Switching screens does not resize the navigation.
- URLs map one-to-one to workspace keys.
- "Operator Console" is no longer the primary top-level destination.
- The first visible screen is workflow-oriented.

## P32-002 Shared UI Primitives

Problem:

Buttons, tabs, headings, panels, and status badges still feel inconsistent.

Implementation shape:

```txt
Create or consolidate local CSS primitives:
  .ui-shell
  .ui-nav
  .ui-tabs
  .ui-button
  .ui-button-primary
  .ui-button-secondary
  .ui-panel
  .ui-section
  .ui-status
  .ui-field
  .ui-toolbar
```

Color direction:

```txt
Base: neutral slate/gray surfaces
Primary: blue
Secondary selection: sky
Success: emerald
Warning: amber
Danger: red
Info: cyan or indigo, sparingly
```

Required CSS tokens:

```css
:root {
  --surface-0: #0f172a;
  --surface-1: #1e293b;
  --surface-2: #334155;
  --surface-3: #475569;
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
  --color-primary: #3b82f6;
  --color-success: #10b981;
  --color-warning: #f59e0b;
  --color-danger: #ef4444;
  --color-info: #06b6d4;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
}
```

Button/tab/status distinction:

```txt
Buttons = perform actions.
Tabs = switch workspace or local view.
Status badges = display state and are not clickable unless explicitly a filter.
```

Avoid:

- One-note blue-only UI
- Cards inside cards
- Font scaling by viewport width
- Negative letter spacing

Done when:

- Major buttons share one visual system.
- Screen titles use one heading style.
- Tabs, buttons, and status badges are visually distinct.
- Primary, secondary, destructive, and disabled button states are consistent.

## P32-003 Next Workspace

Problem:

The operator needs a first screen that says what to do now.

Implementation shape:

```txt
Build a Next workspace around /api/collaboration/next-action.
Show:
  action_type
  priority
  title
  detail
  next_endpoint
  method
  task_template when present
```

Expected API shape:

```json
{
  "action_type": "generate_project_snapshot|create_task_from_accepted_finding|implement_task|triage_review_findings|run_ai_review_now",
  "priority": "urgent|high|normal|low",
  "title": "string",
  "detail": "string",
  "next_endpoint": "/api/...",
  "method": "GET|POST",
  "task_template": {},
  "empty_state": false
}
```

Behavior:

- If action is packet generation, deep-link to Packets with defaults.
- If action is review triage, deep-link to Reviews.
- If action is task implementation, deep-link to Tasks.
- If action is provider review, deep-link to Ops provider runs.
- If empty state is active, show a clear "fresh install or no sources" prompt.
- Primary action must be visible in the first viewport without scrolling.
- Use a skeleton or compact loading state if the API is slow.

Done when:

- A user can open the app and know the next step in under five seconds.
- Disabled actions explain the reason.

## P32-004 Packets Workspace

Problem:

Packets are central to external AI collaboration, but the current flow still
feels like a form plus raw output.

Implementation shape:

```txt
Promote Packets to a first-class workspace.
Use v2 names:
  tasks
  structured_state_pages
  packet_fitness
  required_context
  context_questions
```

Controls:

- target provider / all providers
- profile
- output mode
- focus
- delta from packet
- acknowledge quality warnings
- generate
- copy content

Display:

- copy-ready packet
- copy button directly above or beside the packet output
- packet size and budget advisory
- signals
- context questions
- empty state

Done when:

- The user can generate a packet and immediately copy the correct content.
- The copy button is visible immediately after generation without scrolling.
- Copy feedback changes state, for example `Copy packet` -> `Copied`.
- Retired experiment packet controls are not shown as a primary path.
- Warnings do not silently block the button without explanation.

## P32-005 Reviews Workspace

Problem:

Review import should be a clear two-step process: dry-run, then import.

Implementation shape:

```txt
Create a dedicated Reviews workspace:
  paste external AI response
  dry-run parser
  show findings preview
  show parser errors
  import when clean
  recent reviews table
```

Layout:

```txt
Step 1: Parse
  response textarea
  Dry Run button

Step 2: Import
  findings preview
  parser errors and suggested fixes
  Import button enabled only after a clean dry-run
```

Step 2 should not dominate the initial screen before Step 1 has a result.

Done when:

- Parser errors are actionable.
- Dry-run and import are visually distinct.
- Imported findings are easy to send to Tasks.

## P32-006 Tasks Workspace

Problem:

Implementation work should not be buried under reviews or actor panels.

Implementation shape:

```txt
Create a dedicated Tasks workspace:
  accepted findings without tasks
  task list by status
  task detail
  implementation evidence form
```

Rules:

- Use `tasks`, not `finding_tasks`.
- Keep review text secondary.
- Make evidence submission compact: implemented, commit, changed files,
  verification note.
- Show accepted findings without tasks at the top.
- Blocked tasks must show a blocking reason if one exists.

Done when:

- Accepted findings can become tasks from this screen.
- A task can be closed with implementation evidence.
- The UI labels align with v2 API vocabulary.

## P32-007 Sources Workspace

Problem:

Knowledge Map is useful as a confirmation tool, but not as the main workflow.

Implementation shape:

```txt
Rename/reframe Knowledge Map as Sources.
Show:
  pages
  node cards
  structured state preview
  optional graph summary
```

Done when:

- Users can inspect source context without feeling like graph visualization is
  the product's main action.
- Source detail links are safe and scoped.

## P32-008 Ops Workspace

Problem:

Provider runs, SARIF, DB v2, MCP, and maintenance are important but should not
dominate daily workflow.

Implementation shape:

```txt
Create an Ops workspace:
  health
  provider runs
  SARIF readiness/export
  DB v2 status
  MCP status
  maintenance actions
```

Rules:

- Do not auto-run slow checks.
- Do not run release_check from screen entry.
- Show when a check is stale.
- Refresh/check actions are manual button clicks.
- Keep destructive actions guarded.

Done when:

- Health and provider problems are discoverable.
- The default user path does not start in Ops.

## P32-009 Retire Confusing UI Paths

Problem:

Some labels and workflows no longer match the product:

```txt
Operator Console
Actor Agent Dashboard
External AI Packet buried under console
Experiment packets
finding_tasks labels
ai_state_pages labels
```

Implementation shape:

```txt
- Remove Agent Dashboard duplication from Actor/user panels if it now has a
  real workspace.
- Hide or remove retired experiment packet UI.
- Replace old labels with v2 vocabulary.
- Keep admin/operator role restrictions for sensitive screens.
```

Done when:

- The visible UI no longer uses old table-era names.
- There is one obvious place for packet generation.
- There is one obvious place for tasks.
- This search returns no active web UI hits:

```powershell
rg "finding_tasks|ai_state_pages|Operator Console|Agent Dashboard" apps\web
```

Mentions in archived docs or migration files are allowed.

## P32-010 Verification

Targeted checks:

```powershell
cd apps\web
npm run build

cd ..\api
python -m pytest tests\test_phase31_v2_collaboration.py -q
```

Required desktop visual check:

```txt
Start the web app and verify at 1280px width:
  navigation is stable and does not resize between workspaces
  /next shows the primary action immediately
  /packets shows Generate and Copy controls without hunting
  /reviews clearly separates Dry Run and Import
  /tasks shows accepted findings without tasks at the top
  /ops does not auto-run slow checks
  text does not overlap
  disabled actions show reasons
```

Done when:

- Next build passes.
- v2 API tests still pass.
- No visible UI label uses `finding_tasks` or `ai_state_pages`.
- Desktop visual check is completed.

## Implementation Slices

Phase 32 should be implemented in two slices.

### Slice 1: Shell And First Action

```txt
P32-001 Navigation And Shell
P32-002 Shared UI Primitives
P32-003 Next Workspace
P32-009 Retire Confusing UI Paths
```

This slice establishes the app frame. Do not start the remaining workspaces
until shell navigation and local UI primitives are stable.

### Slice 2: Workflow Workspaces

```txt
P32-004 Packets Workspace
P32-005 Reviews Workspace
P32-006 Tasks Workspace
P32-007 Sources Workspace
P32-008 Ops Workspace
P32-010 Verification
```

This slice fills in the workflow screens after the shell is stable.

## Acceptance

```txt
1. Top-level UI is organized as Next / Packets / Reviews / Tasks / Sources / Ops.
2. First screen communicates the next operator action.
3. Packet generation is a first-class workflow.
4. Review import and task implementation are separate workspaces.
5. Ops/maintenance is available but not the default product experience.
6. UI vocabulary uses v2 names: tasks and structured_state_pages.
7. Buttons, tabs, status badges, and headings use consistent local primitives.
8. URLs map to /next, /packets, /reviews, /tasks, /sources, and /ops.
9. Desktop visual check passes at 1280px.
10. npm run build passes.
11. Targeted v2 API tests still pass.
```

## Implementation Notes

### Slice 1 Completed: Shell And First Action

Implemented on 2026-05-08:

```txt
- Top-level workspace navigation now uses Next / Packets / Reviews / Tasks /
  Sources / Ops.
- Workspace routes map to /next, /packets, /reviews, /tasks, /sources, and
  /ops through the shared app shell.
- The first workspace is Next, backed by /api/collaboration/next-action.
- Next actions deep-link to the appropriate workspace instead of exposing
  module-era dashboard labels.
- Local UI primitives were added for panels, buttons, status chips, and
  workflow placeholders.
- Visible web UI labels no longer use Operator Console, Knowledge Map, Agent
  Dashboard, finding_tasks, or ai_state_pages.
- Retired experiment packet controls are no longer visible in the Packets
  workspace.
```

Verification completed:

```powershell
cd apps\web
npm run build

cd ..\api
python -m pytest tests\test_phase31_v2_collaboration.py -q
```

Remaining for Slice 2:

```txt
P32-004 Packets Workspace
P32-005 Reviews Workspace
P32-006 Tasks Workspace
P32-007 Sources Workspace
P32-008 Ops Workspace
P32-010 Desktop visual check
```

### Slice 2 Completed: Workflow Workspaces

Implemented on 2026-05-08:

```txt
- Reviews workspace now separates parser dry-run from final import.
- Dry-run parser results show finding count, parser errors, and preview
  findings before import is enabled.
- Tasks workspace is connected to v2 /tasks, /finding-queue, task creation, and
  implementation evidence submission.
- Accepted findings without tasks are surfaced at the top of Tasks.
- Task detail includes compact evidence fields: commit, changed files,
  verification note, and memo.
- Sources graph loading now happens only when the Sources workspace is active.
- Ops provider/health/maintenance loading now happens only when the Ops
  workspace is active; no interval refresh runs from screen entry.
- Local CSS primitives were extended for task queues, review dry-run previews,
  and parser errors.
```

Verification completed:

```powershell
cd apps\web
npm run build

cd ..\api
python -m pytest tests\test_phase31_v2_collaboration.py -q
```

Desktop visual check completed:

```txt
Started local API/web with scripts/dev.ps1.
Captured /next, /packets, /reviews, /tasks, /sources, and /ops at 1280px width
with Playwright.
Verified navigation remains stable between workspaces, Next shows the primary
action in the first viewport when authenticated, Packets/Reviews/Tasks/Ops keep
their controls visible and separated, and no obvious text overlap is present.
Screenshots: data/tmp/phase32-visual/auth/
```

## Out Of Scope

```txt
- New backend features
- DB schema changes
- New provider integrations
- New MCP protocol work
- Full design-system dependency installation
- Marketing site or landing page
- Mobile layout or phone-width navigation
- Full release_check
```
