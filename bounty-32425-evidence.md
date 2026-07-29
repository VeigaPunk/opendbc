# Bounty evidence: commaai/openpilot#32425 — "test_models: add a test that fuzzes the tx messages"

**Deliverable:** `test_panda_safety_tx_fuzzy` in `opendbc/car/tests/test_models.py`
(branch `bounty-32425-tx-fuzz` on the fork `VeigaPunk/opendbc`).

## Context: post-#38441 layout

- commaai/openpilot#38441 moved `selfdrive/car/tests/test_models.py` from openpilot into
  **commaai/opendbc** (`opendbc/car/tests/test_models.py`), and #38428 removed hypothesis
  from openpilot. #38471 replaced pytest with a custom runner (`unittest_parallel`).
- Fuzzing now uses `opendbc.testing.fuzzy_test` / `opendbc.testing.Fuzzy`, a small
  deterministic generator (`boolean`, `choice`, `integer`, `binary`, `list`) with
  systematic boundary coverage and reproducible seeds (`FUZZ_SEED` / `FUZZ_EXAMPLE`,
  printed on failure via `exc.add_note`). The new test is written against this API —
  no hypothesis, no pytest.
- Upstream already merged the deterministic part of sshane's draft as
  `test_panda_safety_tx_cases` (fixed CarControl cases through `CI.apply` +
  `safety_tx_hook`). This change adds the missing **fuzzed** half the bounty asks for.

## Bounty criteria

1. **"Fails when the panda safety tx hook rejects a message openpilot tries to send"**
   (the commaai/panda#1948 mismatch class): every frame, fuzzed measured-state CAN is fed
   into *both* `safety_rx_hook` and `CI.update`, and a fuzzed `CarControl` is run through
   `CI.apply`; **every** resulting `sendcan` message is passed through
   `safety.safety_tx_hook` and a rejection fails the test with full panda/openpilot state
   context. Payloads are drawn from a small pool seeded with the last real payload seen on
   the route, so measured values oscillate between plausible in-range readings and extremes —
   exactly the pattern that exposes panda's sample-window (min/max) divergence from
   openpilot's instantaneous readings (panda#1948).
2. **No false positives from physically impossible fuzzed state:** the assertion is gated by
   `_tx_fuzz_measured_state_coherent`, which only asserts while openpilot's `CarState` and
   panda agree on the measured state the TX limits depend on (vehicle speed window, Toyota
   LTA driver/EPS torque window extremes and angle range, angle-control measured angle and
   command continuity, Ford curvature error window, and panda's own lateral accel/jerk
   bounds). Blocked frames still run through the tx hook so panda's rate-limit tracking
   state keeps moving, and panda's desired angle/curvature baselines are re-anchored to
   openpilot's applied command each frame (`set_desired_angle_last` /
   `set_desired_curvature_last`, already exposed by `libsafety_py`). Panda gating state that
   fuzzed rx can latch (controls allowed, cruise engaged, gas pressed, relay malfunction,
   Honda AEB brake forwarding) is reset to the drawn state every frame.
3. **Runs in the existing per-car test matrix for every platform with a test route:** the
   test lives in `TestCarModelBase`, reuses the route replay, fingerprint, `CarInterface`
   and `libsafety` setup of the surrounding tests, and skips exactly the platforms the
   existing TX test skips (`dashcamOnly`, `notCar`, Toyota SecOC, VW MLB alpha-long
   routes). Any exception raised by the parser/packer/CarController under fuzzed input
   fails the test (no-crash invariant).

## How this differs from the dead PR #37548

- #37548 (branch `fuzz-tx-messages`) only pushed **random bytes into `safety_tx_hook`**
  in isolation. That can never satisfy criterion 1: it never generates tx from openpilot's
  CarController, so it can't detect openpilot-vs-panda TX logic divergence — it just tests
  that panda rejects garbage, which is panda's own unit-test job.
- This implementation fuzzes the **inputs** (CarControl actuators/HUD/cancel-resume plus
  measured-state rx CAN) and cross-checks the **outputs**: every message openpilot actually
  tries to send must be accepted by panda safety.
- It also honors the controlsd→CarController contract (actuators zeroed while the
  corresponding control is inactive, accel within `ACCEL_MIN/ACCEL_MAX`, cancel only when
  cruise is engaged and openpilot is not, gas-override deactivating long control), so the
  fuzzed CarControl stays within the envelope CarController is designed for.

## Alignment with sshane's draft #34720 ("part 1")

- Same core idea: replay the route, run recorded/fuzzed `carControl` through `CI.apply`,
  and check each `sendcan` against `safety_tx_hook`.
- Improvements over the draft: uses fuzzed (not only recorded) CarControl and rx; resets
  panda latched gating state per frame instead of forcing `set_controls_allowed(True)`;
  asserts per-frame instead of the draft's "blocked > 5" heuristic; skips via the
  platform flags upstream ended up using rather than a hard-coded platform blocklist.
- The measured-state coherence gating and baseline re-anchoring follow the design that
  competitor PR #38425 converged on (the strongest reference), ported to the current
  `opendbc.testing.Fuzzy` API and trimmed (no CANParser counter/checksum fixing —
  both sides reject invalid payloads identically, which keeps them in agreement).

## How to run

```bash
git clone https://github.com/VeigaPunk/opendbc -b bounty-32425-tx-fuzz
cd opendbc
uv sync   # or your usual env setup

# whole car-test matrix (downloads cached route segments; use NUM_JOBS/JOB_ID to shard)
python opendbc/car/tests/test_models.py

# a single generated test class / just the fuzzy tx test
python -m unittest opendbc.car.tests.test_models.TestCarModel_<index>_<PLATFORM>.test_panda_safety_tx_fuzzy

# more/fewer fuzz examples, and replaying a failure
MAX_EXAMPLES=1000 python opendbc/car/tests/test_models.py
FUZZ_SEED=<seed> FUZZ_EXAMPLE=<index> python -m unittest ...test_panda_safety_tx_fuzzy
```

## Local validation performed

- File parses (`ast.parse`) and matches upstream conventions (2-space indent,
  `fuzzy_test` decorator usage identical to the existing
  `test_panda_safety_carstate_fuzzy`, same skip conditions as `test_panda_safety_tx_cases`).
- All `libsafety_py` symbols used exist in `opendbc/safety/tests/libsafety/libsafety_py.py`
  (`set_desired_angle_last`, `set_desired_curvature_last`, `set_honda_fwd_brake`,
  `get_longitudinal_allowed`, the torque/angle/curvature/speed getters).
- `ACCEL_MIN`/`ACCEL_MAX` imported from `opendbc.car.interfaces`; `LongCtrlState` from
  `structs.CarControl.Actuators.LongControlState` (same alias used by brand carcontrollers).
- Not run end-to-end here: running the full matrix requires downloading comma test route
  segments and compiling libsafety (cc + cffi); recommended first CI target is a Toyota
  LTA platform and a Ford (curvature) platform, which carry the most coherence logic.

## Known limitations / residual risk

- Without CANParser-based counter/checksum fix-up, most fuzzed rx payloads are rejected by
  both sides; the pool seeding with real payloads plus repeated pool draws still produces
  accepted oscillations for messages without checksums, but coverage of checksummed
  measured-state signals is thinner than #38425's. This is a deliberate simplicity/
  robustness trade-off and does not affect soundness of failures.
- Brands with torque-based steering only get the gas/brake/speed coherence gates; the
  deeper per-brand tuning #38425 explored (Tesla rx exclusions, VW payload masks) can be
  added incrementally if a platform shows false positives in CI.
