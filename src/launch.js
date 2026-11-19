// THE release moment (Story 18.8). This is the ONE place it is written down.
//
// 10 December 2026, 09:00 in Lisbon, which is 09:00 UTC (Lisbon and London are
// on UTC in December). Everything else reads it:
//   - src/worker.js imports it and marks every page "out" from this moment on,
//     so the same URL flips with no redeploy and no JavaScript;
//   - scripts/build_launch.py reads it and writes every date, every "comes to"
//     and "out now" line, and the countdown's data-release attribute into the
//     pages; its --check mode fails CI when any page carries the date or a
//     launch phrase it did not generate.
// Change the moment here, run `python3 scripts/build_launch.py`, commit both.
export const RELEASE_UTC_MS = 1796893200000;

// "pre" before the moment, "out" from the moment itself onwards.
export function launchState(nowMs) {
  return nowMs >= RELEASE_UTC_MS ? 'out' : 'pre';
}
