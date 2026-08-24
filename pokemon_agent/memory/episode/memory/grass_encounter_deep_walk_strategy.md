# Grass Encounter Deep-Walk Strategy

## Summary
Triggered a wild Rattata encounter by executing a three-phase continuous grass walk: (1) 4-step north in Map 0 (y=2 → y=-2) to enter deep grass; (2) 4-step north across map transition into Map 12 (y=34 → y=30); (3) 4-step west to position x=6 y=30 — landing the final two steps within a verified 3-row dense grass zone (x=6–7, y=28–30), directly triggering the encounter.

## Reusable Patterns
- Prioritize grass zones with ≥3-cell depth (row/column continuity) — they yield significantly higher encounter probability than single-line patches.
- After map transitions, always re-validate grass coordinates using `walk_map`: confirm target cells are `G`, not `.` or `#`.
- ‘Continuous walking in grass’ requires ≥2 consecutive steps *on grass cells* — avoid border-hopping (e.g., .→G→.) as it resets encounter counters.

## Critical Decisions & Why They Worked
- **Step 1 (up×4)**: Neighbors + `walk_map` confirmed unobstructed 4-cell northward grass column — eliminated low-yield single-step probing.
- **Step 2 (up×4)**: Verified persistent grass at x=10 from y=34 down to y=30 in Map 12 — maintained momentum and depth.
- **Step 3 (left×4)**: Chose west over east because x=6–7/y=28–30 forms a 3-row grass block (higher density than east’s 1-row), and last two moves (x=7→6 at y=30) landed cleanly on `G`, satisfying the ‘continuous grass walk’ condition.

## Failure Points to Avoid
- Single-step north in Step 1 (e.g., up×1) leaves player at y=1 — still near map edge, shallow grass, low encounter chance.
- Misaligning Step 2’s y-range (e.g., up×4 from y=30 instead of y=34) risks hitting `#` walls or stepping onto `.` — breaks continuity.
- Stopping at x=7 y=30 (left×3) enters grass but misses the second grass step — insufficient for reliable trigger under standard encounter logic.