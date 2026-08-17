"""pytest suite for fb_valve.FBValve - the Python port of FB_Valve.scl.

Run in VS Code via the Test Explorer (Python extension), or from a terminal:
    pip install pytest
    pytest src/Tests/python -v
"""

from datetime import timedelta

from fb_valve import FBValve, HMI


def run(fb: FBValve, hmi: HMI, cycles: int, dt: timedelta = timedelta(milliseconds=100)) -> None:
    """Advance the block a number of scans, each separated by `dt` of simulated time."""
    for _ in range(cycles):
        fb.scan(hmi, dt)


# --------------------------------------------------------------------------------------
# 1. Initialization / default mode
# --------------------------------------------------------------------------------------

def test_default_mode_is_automatic_with_no_motion_or_fault():
    fb, hmi = FBValve(), HMI()
    run(fb, hmi, 1)
    assert hmi.status.mode_auto is True
    assert fb.coil_open is False and fb.coil_close is False
    assert fb.fault is False


def test_first_scan_adopts_current_feedback_so_an_already_open_valve_does_not_move():
    fb, hmi = FBValve(), HMI()
    fb.open_feedback = True
    fb.interlock_open = True
    fb.interlock_close = True
    run(fb, hmi, 1)
    assert fb.coil_open is False
    assert fb.coil_close is False


# --------------------------------------------------------------------------------------
# 3. Automatic control
# --------------------------------------------------------------------------------------

def test_automatic_open_energizes_coil_until_feedback_confirms():
    fb, hmi = FBValve(), HMI()
    fb.interlock_open = True
    fb.interlock_close = True
    fb.auto_open_cmd = True
    run(fb, hmi, 1)
    assert fb.coil_open is True

    fb.open_feedback = True
    run(fb, hmi, 1)
    assert fb.coil_open is False
    assert fb.open is True
    assert hmi.status.open is True


def test_automatic_close_energizes_coil_until_feedback_confirms():
    fb, hmi = FBValve(), HMI()
    fb.interlock_open = True
    fb.interlock_close = True
    fb.open_feedback = True  # start from Open
    run(fb, hmi, 1)

    fb.auto_close_cmd = True
    run(fb, hmi, 1)
    assert fb.coil_close is True

    fb.open_feedback = False
    fb.close_feedback = True
    run(fb, hmi, 1)
    assert fb.coil_close is False
    assert fb.closed is True


def test_automatic_open_rejected_without_interlock_open():
    fb, hmi = FBValve(), HMI()
    fb.interlock_open = False
    fb.interlock_close = True
    fb.close_feedback = True  # currently closed
    fb.auto_open_cmd = True
    run(fb, hmi, 1)
    assert fb.coil_open is False
    assert fb.closed is True


def test_automatic_close_rejected_without_interlock_close():
    fb, hmi = FBValve(), HMI()
    fb.interlock_open = True
    fb.interlock_close = False
    fb.open_feedback = True  # currently open
    run(fb, hmi, 1)

    fb.auto_close_cmd = True
    run(fb, hmi, 1)
    assert fb.coil_close is False
    assert fb.open is True


# --------------------------------------------------------------------------------------
# 2. Manual control
# --------------------------------------------------------------------------------------

def test_manual_mode_ignores_automatic_inputs():
    fb, hmi = FBValve(), HMI()
    fb.interlock_open = True
    fb.interlock_close = True
    hmi.control.mode_manual = True
    fb.auto_open_cmd = True  # must be ignored in Manual
    run(fb, hmi, 1)
    assert fb.coil_open is False
    assert hmi.status.mode_manual is True
    assert hmi.status.mode_auto is False


def test_manual_open_respects_interlock_open():
    fb, hmi = FBValve(), HMI()
    fb.interlock_open = False
    hmi.control.mode_manual = True
    hmi.control.open_cmd = True
    run(fb, hmi, 1)
    assert fb.coil_open is False


def test_manual_travel_stops_immediately_when_interlock_lost_and_resumes_when_restored():
    fb, hmi = FBValve(), HMI()
    fb.interlock_open = True
    hmi.control.mode_manual = True
    hmi.control.open_cmd = True
    run(fb, hmi, 1)
    assert fb.coil_open is True

    fb.interlock_open = False
    run(fb, hmi, 1)
    assert fb.coil_open is False, "losing the interlock mid-travel must stop the coil immediately"

    fb.interlock_open = True
    run(fb, hmi, 1)
    assert fb.coil_open is True, "restoring the interlock must resume travel to the latched target"


# --------------------------------------------------------------------------------------
# 4. Maintenance control
# --------------------------------------------------------------------------------------

def test_maintenance_bypasses_interlock():
    fb, hmi = FBValve(), HMI()
    fb.interlock_open = False
    fb.interlock_close = False
    hmi.control.mode_maintenance = True
    hmi.control.close_cmd = True
    run(fb, hmi, 1)
    assert hmi.status.mode_maintenance is True
    assert fb.coil_close is True


# --------------------------------------------------------------------------------------
# 5. Error handling
# --------------------------------------------------------------------------------------

def test_travel_timeout_raises_fault_and_then_inhibits_the_coil():
    fb, hmi = FBValve(), HMI()
    fb.travel_time = timedelta(milliseconds=250)
    fb.interlock_open = True
    fb.interlock_close = True
    fb.auto_open_cmd = True

    run(fb, hmi, 5, dt=timedelta(milliseconds=100))  # 500 ms of open demand, no feedback ever

    assert fb.fault is True
    assert hmi.status.fault_timeout_open is True
    assert fb.coil_open is False, "coil must be inhibited once the fault is latched"


def test_reset_does_not_clear_a_fault_whose_condition_still_exists():
    fb, hmi = FBValve(), HMI()
    fb.travel_time = timedelta(milliseconds=250)
    fb.interlock_open = True
    fb.interlock_close = True
    fb.auto_open_cmd = True
    run(fb, hmi, 5, dt=timedelta(milliseconds=100))
    assert fb.fault is True

    hmi.control.reset_fault = True
    run(fb, hmi, 1)
    hmi.control.reset_fault = False

    # OpenFeedback was never provided, so the same travel-timeout condition is still present;
    # continuing to run must let it re-trip rather than staying falsely cleared.
    run(fb, hmi, 5, dt=timedelta(milliseconds=100))
    assert fb.fault is True


def test_reset_clears_fault_once_the_condition_is_actually_resolved():
    fb, hmi = FBValve(), HMI()
    fb.travel_time = timedelta(milliseconds=250)
    fb.interlock_open = True
    fb.interlock_close = True
    fb.auto_open_cmd = True
    run(fb, hmi, 5, dt=timedelta(milliseconds=100))
    assert fb.fault is True

    fb.open_feedback = True  # resolve: valve did in fact reach Open
    hmi.control.reset_fault = True
    run(fb, hmi, 1)
    hmi.control.reset_fault = False
    run(fb, hmi, 2)

    assert fb.fault is False
    assert fb.open is True


def test_feedback_conflict_raises_fault():
    fb, hmi = FBValve(), HMI()
    fb.open_feedback = True
    fb.close_feedback = True
    run(fb, hmi, 1)
    assert fb.fault is True
    assert hmi.status.fault_feedback_conflict is True


def test_feedback_conflict_clears_after_resolution_and_reset():
    fb, hmi = FBValve(), HMI()
    fb.open_feedback = True
    fb.close_feedback = True
    run(fb, hmi, 1)
    assert fb.fault is True

    fb.open_feedback = False  # resolve: only Closed is genuinely active
    hmi.control.reset_fault = True
    run(fb, hmi, 1)
    hmi.control.reset_fault = False
    run(fb, hmi, 1)

    assert fb.fault is False
    assert fb.closed is True
