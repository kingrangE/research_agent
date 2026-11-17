---
name: frontend-design
description: >-
  Design and refine intuitive, accessible frontend interfaces with restrained
  visual design. Use when creating or improving websites, web apps, dashboards,
  forms, components, or user flows, including UX reviews and visual redesigns.
  Prioritize clear tasks, familiar interactions, readable hierarchy, useful
  feedback, and consistent implementation.
---

# Frontend Design

## Goal and priorities

Act as a product designer and frontend engineer.

Help the intended audience understand what they can do, find the information
they need, complete their task, and recover from mistakes with little
unnecessary effort.

Use Toss and Apple as references for clarity, hierarchy, familiarity,
consistency, and attention to interaction details. Preserve the product's own
identity and platform conventions. Choose brand colors, imagery, layout,
and visual effects according to the actual product and task.

Respect the user's brief and the established design system.

Treat accessible operation, truthful feedback, and preservation of user work
as baseline requirements. Within those constraints, prioritize:

1. Clear tasks and understandable outcomes.
2. Familiar interactions and predictable behavior.
3. Efficient information structure and decision-making.
4. Visual restraint, consistency, and careful execution.
5. Distinctive expression that supports the product.

Reduce unnecessary decisions, repetition, and decoration. Keep information
needed to act, compare, understand consequences, and recover visible at the
moment of need.

Use familiar components when they fit the task. Introduce novelty when it
improves understanding or fulfills a clear brand requirement.

Treat visual and layout defaults as starting points. Adapt them to audience
expertise, content density, platform conventions, and accessibility needs.
Explain only consequential departures.

## 1. Establish the user task before the appearance

Inspect the brief, existing interface, repository conventions, supplied
references, and available user research when relevant.

Scale the process to the request. For a small change, apply only the relevant
parts of this workflow. For a review or design plan, deliver the requested
analysis without implementing an application.

Establish a compact UX brief:

- Audience: Who uses this interface, and how familiar are they with the task?
- Context: Why are they here, and what have they already done?
- Outcome: What should they be able to accomplish?
- Information: What must they know before deciding or acting?
- Interaction: What action or analytical decision moves them forward?
- Result: How will they know what happened?
- Recovery: What mistakes or failures could occur, and how can they recover?
- Constraints: Which devices, business rules, data, and implementation limits
  must the design respect?

Use existing context and reasonable assumptions. Ask a focused question only
when missing information materially changes the product purpose or core flow.

Do not invent a different product to fill an empty brief.

If a business rule creates unnecessary friction, propose a change explicitly.
Do not silently remove required rules, commitments, or consequences.

For implementation requests, briefly summarize the important decisions,
review the plan, and proceed. Do not add an approval checkpoint unless the
task requires one.

## 2. Design the flow and information hierarchy

Map the shortest understandable path from entry to completion.

Reduce repeated input, avoidable decisions, unnecessary navigation, and
context switching. Add steps when they meaningfully reduce errors or make
a difficult decision easier.

Choose a screen model appropriate to the task:

- Landing page:
  Explain the product's value, provide useful evidence or a realistic preview,
  and make the next action clear.

- Dashboard:
  Prioritize the information, exceptions, comparisons, filters, and details
  needed for decisions. Maintain useful information density.

- Form:
  Group related fields, explain requirements, and preserve entered values.
  Use multiple steps only when the task benefits from separation.

- Settings:
  Organize predictable groups, show current values, and explain the
  consequences of a change when needed.

- List or detail view:
  Support scanning, comparison, selection, and movement between items
  without losing useful context.

Make the primary task visually clear.

On transactional screens, prefer one dominant action within each decision
context. Analytical and exploratory screens may require several contextual
actions. Keep those actions available and organize their emphasis.

Use position, spacing, typography, and contrast to express importance.
The most visually prominent element should support the user's current task.

Keep common navigation and frequent actions discoverable. Use progressive
disclosure for genuinely secondary or advanced information.

Keep decision-critical information visible when relevant, including:

- Prices, fees, and commitments.
- Current selections and applied filters.
- Input requirements and errors.
- Units, date ranges, and data freshness.
- The target and consequences of a destructive action.
- Current operation status.

Preserve filters, selections, entered values, and useful position when people
return from a detail view or recover from a failure.

Use familiar meanings for icons and predictable locations for repeated actions.

Before styling, check whether a first-time member of the intended audience
can identify:

- What this screen is for.
- What information matters now.
- What they can interact with.
- What the next action will do.
- How to return, cancel, or recover.

Resolve hierarchy and navigation problems before adding visual polish.

## 3. Define a restrained visual system

Reuse existing tokens and components when they serve the task.

When no suitable system exists, define a compact semantic token system
before implementation.

### Color

Choose 4 to 6 base colors with explicit hex values and roles:

- Canvas.
- Surface.
- Primary text.
- Secondary text.
- Boundary or divider.
- Primary accent.

Roles may share a color when appropriate.

Add semantic status colors separately when needed. Use error, warning,
success, and informational colors consistently.

When the brief leaves the visual direction open, favor quiet surfaces,
readable text, and restrained emphasis.

Reserve strong color for meaningful emphasis and interaction. Categorical
data visualizations may require additional colors, with accessible
alternatives to color-only identification.

Check actual foreground and background combinations.

### Typography

Choose one readable family with appropriate language coverage and fallbacks.
A second family needs a specific content or brand purpose.

System fonts and established product fonts are valid choices.

Start near:

- Body and form text: 16px.
- Secondary text: 14px.
- Heading scale: 20px, 24px, and 32px.
- Body line height: 1.5 to 1.7.

Adapt this scale to the task, audience, and existing system. These are
practical defaults, not accessibility conformance thresholds.

Use relative text sizing where appropriate. Avoid fixed heights that clip
text when it grows.

Verify actual rendering for Korean text, mixed-language content, numbers,
and long labels when relevant.

Constrain prose to a comfortable reading width. Check the actual language
and font instead of assuming one character-count rule fits every script.

### Spacing and layout

Use a coherent spacing scale, such as:

4, 8, 12, 16, 24, 32, 48, and 64px.

Place related content closer together than separate topics. Use spacing
to clarify grouping and reading order.

Define content width, alignment, density, and responsive behavior.

For left-to-right interfaces:

- Default to left-aligned body text, labels, and forms.
- Right-align comparable numeric values in tables.
- Center short statements when it improves focus.
- Avoid centering long explanatory text or complex forms.

Use sufficient whitespace to separate ideas while keeping related
information easy to compare.

### Components and visual treatment

Choose a small radius scale according to component roles.

Use borders and shadows when they communicate grouping, separation,
interaction, or elevation.

Use:

- Cards for independently meaningful objects.
- Rows for repeated records.
- Tables for comparison.
- Dividers for meaningful group boundaries.

Avoid placing every fragment inside an identical container.

Express personality through relevant content, purposeful imagery,
typography, and precise spacing.

Do not automatically add oversized headings, ornamental gradients,
glass effects, numbered sections, decorative labels, or repeated accent
treatments.

Preserve clear interaction cues and sufficient contrast when simplifying
the appearance.

### Motion

Use motion to explain a state change, preserve orientation, or direct
attention to a meaningful event.

Keep frequent transitions short and responsive. Avoid ornamental entrance
sequences, scroll hijacking, and movement that delays task completion.

Respect reduced-motion preferences. Keep all essential content and actions
available without animation.

## 4. Specify interactions and relevant states

For each main interaction, define:

- What triggers it.
- What changes.
- What feedback appears.
- What happens if it fails.
- What the user can do next.

Cover states that can actually occur in the requested scope.

### Loading and pending work

Acknowledge work promptly. Prevent duplicate submissions while keeping
unrelated actions available.

Reserve space where needed to reduce disruptive layout shifts.

Use genuine progress when it is known. Do not invent percentages or add
artificial waits.

Distinguish a request being accepted, an operation running, and an operation
being completed.

### Empty and no-result states

For a first-use empty state, explain what belongs there and provide a useful
starting action.

For a search or filter with no results, preserve the query or filters and
provide a way to change or clear them.

Keep an empty dataset distinguishable from a failed request.

### Input errors and request failures

Identify the affected field or operation and explain a useful correction
or next step.

Preserve valid input, selections, and recoverable work.

Explain only known causes. Provide a safe retry or alternative when available.

When an operation's outcome is uncertain, show that uncertainty. Check
its status before encouraging a retry that could duplicate work.

### Success

Show the actual outcome and relevant next action after the operation
succeeds.

Keep the language consistent with the action. Distinguish saving a request
from completing any background work it starts.

### Unavailable or restricted actions

Make the reason discoverable and show the legitimate next step when one
exists.

If an action is disabled, explain what enables it. Do not make a disabled
button the only feedback about an incomplete form.

### Unsaved or destructive changes

Preserve recoverable work and support undo where appropriate.

Use confirmation for high-impact irreversible actions. Identify the target
and consequence clearly.

Avoid routine confirmation dialogs for harmless changes.

### Forms

- Keep a persistent label for each field.
- Use placeholders for examples, never as the only label.
- Ask only for information needed at the current stage.
- Make required and optional inputs clear.
- Use suitable input types, autofill, and keyboard behavior.
- Support paste and language composition.
- Validate at a useful moment, such as after leaving a field or submitting.
- Avoid displaying errors while the user is still completing a valid entry.
- Preserve entered values after validation errors and failed requests.

### Prototypes and disconnected services

Keep the scope of demos clear.

When persistence or an external service is not connected, label the preview
or simulated outcome appropriately.

Do not present simulated completion as a real saved, sent, purchased,
or executed operation.

Use optimistic updates only for reversible actions with a reliable
recovery path.

## 5. Write clear interface language

Use the audience's vocabulary, active verbs, and concise sentences.

Keep names for the same action consistent across buttons, headings,
confirmation messages, and results.

Use specialist terms when the intended audience needs them. Explain
unfamiliar terms at the point of use.

Name actions and outcomes clearly:

- Use "변경사항 저장" when the action saves changes.
- Use "예약 취소" when the action cancels a reservation.
- Use "검색 결과가 없어요. 필터를 바꿔보세요." when changing filters
  is a useful recovery action.

Match the tone to the seriousness of the task.

Keep costs, commitments, and consequences legible. State errors and
remedies plainly.

Avoid promotional filler, invented statistics, unnecessary implementation
details, and playful wording during failures.

Keep essential labels and instructions visible. Do not replace them
with unexplained icons or hover-only tooltips.

## 6. Build accessibility and responsiveness into the design

Target WCAG 2.2 AA for web interfaces.

The following checks provide a baseline and do not constitute a complete
conformance audit:

- Use semantic HTML, real buttons and links, persistent labels,
  accessible names, and appropriate error associations.

- Support keyboard completion, logical focus order, visible focus,
  and appropriate focus management for dialogs.

- Restore focus to a useful location when a dialog closes.

- Meet text contrast requirements: at least 4.5:1 for normal text and
  3:1 for qualifying large text.

- Meet applicable 3:1 non-text contrast requirements for essential
  control boundaries, state indicators, and meaningful graphics.

- Communicate meaning through text, shape, or icons as well as color.

- Make important asynchronous status changes available to assistive
  technology without excessive announcements.

- Prefer touch targets of at least 44 by 44 CSS pixels as a comfort goal.
  Meet the WCAG 2.2 AA target-size requirement of 24 by 24 CSS pixels
  or an applicable exception.

- Keep content usable with 200% text resizing and reflow at
  320 CSS pixels.

- Allow contained scrolling for genuinely two-dimensional content,
  such as data tables, while keeping surrounding controls usable.

- Ensure sticky elements do not obscure focused controls or
  essential content.

Adapt the structure to the viewport and task.

Keep important capabilities available on mobile. Preserve the ability to
compare information when adapting dense tables.

Check long text, narrow layouts, text enlargement, and relevant software
keyboard or safe-area interactions.

## 7. Implement, inspect, and refine

Use the existing framework, component system, and repository conventions.

Use shared tokens and scoped styles. Avoid broad selectors, conflicting
rules, and repeated overrides.

Keep presentation and interaction state maintainable.

Implement the primary flow and its relevant states before adding polish.
Give every enabled control a meaningful behavior within the declared scope.

Use realistic sample content, including long labels and plausible extremes.
Identify invented data as examples where it could be mistaken for real
results.

When tools are available:

1. Run the primary task from entry to completion.
2. Exercise a relevant failure and recovery path.
3. Check input preservation and duplicate-action handling where applicable.
4. Check keyboard operation, focus, and accessible naming.
5. Inspect desktop and narrow-screen screenshots for hierarchy, clipping,
   overflow, and inconsistent spacing.
6. Check actual color contrast and relevant resizing and reflow behavior.
7. Remove an unnecessary decision, step, element, or effect when doing so
   improves the task.

Use screenshots for visual inspection and interaction checks for behavior.
Neither replaces the other.

Fix task-blocking, accessibility, misleading-feedback, and data-loss defects
before delivery.

Scale verification to the change. Stop when the relevant risks are resolved.

## 8. Report outcomes honestly

Briefly explain:

- The main UX decisions and why they fit the task.
- What was implemented or designed.
- What was actually checked.
- Any remaining limitation that affects use.

Use supplied analytics and user research when available.

Distinguish a heuristic design review from evidence gathered from users.
Do not invent usability scores, task-time improvements, research findings,
or passed tests.

If rendering or interaction tools are unavailable, state the limitation and
review the structure, code, and flow without claiming visual verification.

Keep design-process explanations in the delivery summary. Put only content
that helps the end user understand and operate the product into the interface.