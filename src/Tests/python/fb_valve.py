"""Python port of FunctionBlocks/FB/FB_Valve.scl for fast, TIA-Portal-free testing.

This is a scan-by-scan re-implementation of the same logic, not the compiled SCL block -
it is meant to catch logic errors quickly in VS Code before importing/compiling the real
block in TIA Portal. Field names are snake_case (idiomatic Python) instead of the SCL
block's PascalCase; the region numbering in comments matches FB_Valve.scl's REGION titles
so the two can be read side by side.

Timers accept an explicit `dt` (elapsed time since the previous scan) instead of reading a
system clock, so tests can simulate any amount of elapsed time deterministically.
"""

from dataclasses import dataclass, field
from datetime import timedelta


@dataclass
class HMIControl:
    """Mirrors UDT_Valve2C_HMI.Control."""
    mode_manual: bool = False
    mode_maintenance: bool = False
    open_cmd: bool = False
    close_cmd: bool = False
    reset_fault: bool = False


@dataclass
class HMIStatus:
    """Mirrors UDT_Valve2C_HMI.Status."""
    mode_auto: bool = False
    mode_manual: bool = False
    mode_maintenance: bool = False
    open: bool = False
    closed: bool = False
    moving: bool = False
    coil_open: bool = False
    coil_close: bool = False
    interlocked_open: bool = False
    interlocked_close: bool = False
    fault: bool = False
    fault_timeout_open: bool = False
    fault_timeout_close: bool = False
    fault_feedback_conflict: bool = False


@dataclass
class HMI:
    """Mirrors UDT_Valve2C_HMI."""
    control: HMIControl = field(default_factory=HMIControl)
    status: HMIStatus = field(default_factory=HMIStatus)


class TON:
    """IEC 61131 TON: Q follows (ET >= PT) only while IN is TRUE; IN=FALSE resets ET and Q."""

    def __init__(self):
        self.et = timedelta(0)
        self.q = False

    def __call__(self, IN: bool, PT: timedelta, dt: timedelta) -> bool:
        if IN:
            self.et = min(self.et + dt, PT)
            self.q = self.et >= PT
        else:
            self.et = timedelta(0)
            self.q = False
        return self.q


class RTrig:
    """IEC 61131 R_TRIG: TRUE for one call on a 0->1 transition of clk."""

    def __init__(self):
        self._prev = False

    def __call__(self, clk: bool) -> bool:
        q = clk and not self._prev
        self._prev = clk
        return q


class FBValve:
    """Port of FB_Valve. Call .scan(hmi, dt) once per simulated PLC cycle."""

    def __init__(self):
        # VAR_INPUT
        self.auto_open_cmd = False
        self.auto_close_cmd = False
        self.open_feedback = False
        self.close_feedback = False
        self.interlock_open = False
        self.interlock_close = False
        self.travel_time = timedelta(seconds=10)

        # VAR_OUTPUT
        self.coil_open = False
        self.coil_close = False
        self.open = False
        self.closed = False
        self.moving = False
        self.fault = False

        # VAR (internal)
        self._first_scan = True
        self.mode_auto = False
        self.mode_manual = False
        self.mode_maintenance = False
        self._target_open = False
        self._reset_fault_edge = RTrig()
        self._open_timer = TON()
        self._close_timer = TON()
        self._fault_timeout_open = False
        self._fault_timeout_close = False
        self._fault_feedback_conflict = False

    def scan(self, hmi: HMI, dt: timedelta = timedelta(milliseconds=1)) -> None:
        # 1. Initialization
        if self._first_scan:
            self._target_open = self.open_feedback
            self._first_scan = False

        self.mode_maintenance = hmi.control.mode_maintenance
        self.mode_manual = (not self.mode_maintenance) and hmi.control.mode_manual
        self.mode_auto = (not self.mode_maintenance) and (not self.mode_manual)

        reset_edge = self._reset_fault_edge(hmi.control.reset_fault)

        # 2. Manual control
        if self.mode_manual:
            if hmi.control.open_cmd and not hmi.control.close_cmd and self.interlock_open:
                self._target_open = True
            elif hmi.control.close_cmd and not hmi.control.open_cmd and self.interlock_close:
                self._target_open = False

        # 3. Automatic control
        if self.mode_auto:
            if self.auto_open_cmd and not self.auto_close_cmd and self.interlock_open:
                self._target_open = True
            elif self.auto_close_cmd and not self.auto_open_cmd and self.interlock_close:
                self._target_open = False

        # 4. Maintenance control
        if self.mode_maintenance:
            if hmi.control.open_cmd and not hmi.control.close_cmd:
                self._target_open = True
            elif hmi.control.close_cmd and not hmi.control.open_cmd:
                self._target_open = False

        # Coil resolution (uses this scan's mode/target but last scan's self.fault, exactly
        # like the SCL, since Fault itself is only recomputed further down in region 5)
        self.coil_open = (self._target_open and not self.open_feedback and not self.fault
                           and (self.mode_maintenance or self.interlock_open))
        self.coil_close = ((not self._target_open) and not self.close_feedback and not self.fault
                            and (self.mode_maintenance or self.interlock_close))

        # 5. Error handling
        open_timeout = self._open_timer(IN=self.coil_open, PT=self.travel_time, dt=dt)
        close_timeout = self._close_timer(IN=self.coil_close, PT=self.travel_time, dt=dt)

        if open_timeout:
            self._fault_timeout_open = True
        if close_timeout:
            self._fault_timeout_close = True
        if self.open_feedback and self.close_feedback:
            self._fault_feedback_conflict = True

        if reset_edge:
            self._fault_timeout_open = False
            self._fault_timeout_close = False
            if not (self.open_feedback and self.close_feedback):
                self._fault_feedback_conflict = False

        self.fault = self._fault_timeout_open or self._fault_timeout_close or self._fault_feedback_conflict

        # 6. HMI
        self.open = self.open_feedback and not self.close_feedback
        self.closed = self.close_feedback and not self.open_feedback
        self.moving = (not self.open) and (not self.closed) and (not self.fault)

        hmi.status.mode_auto = self.mode_auto
        hmi.status.mode_manual = self.mode_manual
        hmi.status.mode_maintenance = self.mode_maintenance
        hmi.status.open = self.open
        hmi.status.closed = self.closed
        hmi.status.moving = self.moving
        hmi.status.coil_open = self.coil_open
        hmi.status.coil_close = self.coil_close
        hmi.status.interlocked_open = not self.interlock_open
        hmi.status.interlocked_close = not self.interlock_close
        hmi.status.fault = self.fault
        hmi.status.fault_timeout_open = self._fault_timeout_open
        hmi.status.fault_timeout_close = self._fault_timeout_close
        hmi.status.fault_feedback_conflict = self._fault_feedback_conflict
