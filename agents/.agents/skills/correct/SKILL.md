---
name: correct
description: Eliminate recurring agent mistakes in a repository through ownership, types, checks and focused documentation. Use for /correct or an explicit request to prevent repeated mistakes.
license: MIT
---

# Correct

Find the recurring mistake classes the user asked to prevent. Read recent
corrections, reverts, reviews, workarounds and instructions; cite the real examples.
A class needs evidence of recurrence, not a hypothetical error.

Fix each class at the highest useful level:
1. Give state/rules one owner, remove obsolete paths and prevent copying dead examples.
2. Use types or an actionable lint/check to reject invalid changes. If the
   pattern already exists, prevent new instances without forcing unrelated cleanup.
3. Test observable behavior. Prove the check fails on a real past mistake and
   passes after the correction; remove tests that only mirror internals.
4. Document only the remaining judgment calls, in their owning project docs or
   scoped instructions. Remove rules made redundant by enforcement.

Keep fixes within the authorized scope and verify affected callers. Exceptions
need a narrow reason and owner, with an expiry when temporary. Prepare reviewable
changes; commit only when authorized.

Report each class, its evidence, the enforcement selected and the verification.
Do not turn every operator correction into a new permanent global rule.
