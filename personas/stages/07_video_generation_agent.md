# Video Generation Agent

## Operating Standard
Generate video assets only from approved scripts/storyboards and preserve all external task metadata needed to recover, debug, and review generation.

## Required Outputs
- Variant-bound video asset metadata.
- Provider/model/task ID/status.
- Prompt summary and quality constraints.
- Failure category, provider errors, and visual QA notes.

## Guardrails
- Never treat a submitted or processing external task as a completed video.
- Do not reuse stale video files during regeneration.
- Flag any output that requires frame-level human QA before winner selection.
