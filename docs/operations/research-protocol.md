# Text Alpha User Research Protocol

This protocol turns the MVP's first-use and two-week reuse criteria into a repeatable study. It is a preparation document; no participants have been recruited and no study has been run.

## Purpose and limits

Evaluate whether a person who uses AI for research, learning, or development can import selected material, verify a source, complete a weekly review, and export useful Markdown. Identify workflow friction and privacy concerns before expanding access.

The study does not establish security, privacy, or production readiness. Real personal material may be used only after every applicable item in the [MVP release checklist](release-checklist.md) has passed and the hosted system has been reviewed. Until then, use synthetic fixtures only.

## Participants and consent

- Recruit five participants for the first text Alpha. Expand to no more than ten only after reviewing the first cohort's results and fixing any blocking issue.
- Invite people who regularly use AI for research, learning, or development and organize some work in Markdown or Obsidian.
- Before a session, explain the purpose, the exact data used, what is recorded, who can access study notes, and how to withdraw. Obtain affirmative consent before collecting measurements.
- Screen recording is off by default. Ask for separate consent if a recording would materially help diagnose a workflow issue; pause it before any sensitive material is opened.
- Do not collect note, conversation, or photo contents in research records. Use participant codes and record task events, elapsed time, errors, corrections, and de-identified feedback only.

## Materials and setup

1. Prepare the same two-week synthetic packet for every participant: a Markdown note and a ChatGPT export with selected and unselected conversations, known decisions, a duplicate, and an item with no date.
2. Confirm that the test account contains no other participant's data and reset it before each session.
3. Give the participant the task sheet below without coaching. The facilitator may clarify the task wording but must record any help that changes the outcome.
4. For the paired time comparison, ask the participant to estimate or perform their usual manual weekly-review workflow using the same packet before using Life OS. Record the method and elapsed time.

## Task sheet

Ask each participant to:

1. Choose the Markdown file and only the intended conversations, inspect the upload disclosure, and import them.
2. Find a named decision using date/source filters or keyword search, open its evidence, and explain whether the source supports it.
3. Generate a weekly review, correct anything that is incomplete or wrong, and save the review.
4. Create one follow-up reminder from the review, then mark it complete or dismiss it.
5. Export the review as Markdown and open it in a Markdown editor or Obsidian. Confirm that its identifiers and source references remain readable.

After the text tasks, ask about the upload scope, model consent, source controls, and data deletion. Photo workflows are evaluated separately after text Alpha and use the photo release checks; do not combine them into the text completion score.

## Measures and definitions

Record one row per participant and task, with participant code, cohort, task start/end, success, facilitator help, errors, manual corrections, and a short de-identified observation.

- **First-use success:** completed all five tasks without the facilitator operating the product. Report numerator and denominator; a participant who stops or withdraws remains in the denominator and is shown separately.
- **First-value time:** elapsed time from the first task instruction to a readable review export. Report the median among successful participants and list failed sessions separately. Target: at least 4 of the first 5 participants succeed; median no more than five minutes.
- **Evidence location:** whether the participant opens the expected source for the named decision. Record the expected item before the session; report correct locations divided by attempted locations.
- **Two-week reuse:** after two weeks, count participants who saved a review in each of the two weeks. Target: at least 60% of at least five participants who completed enrollment and reached the two-week point; report all exclusions and missing follow-up.
- **Paired time change:** for each participant with both a manual baseline and two product sessions, calculate `(manual_minutes - product_minutes) / manual_minutes`. Report the median paired change and the paired sample count. Target: at least 30% median reduction. Do not compare unmatched participants.
- **Quality signals:** count unsupported facts, source corrections, duplicate imports, failed tasks, facilitator interventions, and privacy concerns. Any cross-account access or deletion failure stops the study and triggers the release incident process.

## Follow-up and decision

At the end of each session, ask which step felt slow or unclear, what they distrusted, and what they would change before using the system again. Avoid soliciting private source content. At the two-week follow-up, ask what was reused, what was edited manually, and why a review was skipped.

Summarize counts with their denominators, medians with sample counts, task failures, and de-identified observations. Compare results with the thresholds in the [development plan](../roadmap/development-plan.md). Fix data-access, deletion, import, and evidence problems before tuning convenience. Keep the cohort at five until a maintainer reviews the evidence and records the next decision. Do not claim a threshold passed when follow-up is missing or the paired sample is too small to report.

## Study record template

| Participant code | Enrolled | First-use result | First-value minutes | Evidence located | Manual baseline minutes | Week 1 review saved | Week 2 review saved | Product minutes | Help/errors | Privacy feedback |
| --- | --- | --- | ---: | --- | ---: | --- | --- | ---: | --- | --- |
| P01 |  |  |  |  |  |  |  |  |  |  |

Store consent separately from measurement notes. Before recruitment, the maintainer must choose and document the study-note storage location, access list, and deletion date. Do not place identifiable study notes in the public repository.
