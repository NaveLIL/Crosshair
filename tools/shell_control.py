"""Observation protocol shared by the TCG Shell harness and live GUI adapter.

This module contains no Shell navigation or rendering. Addresses are synthetic
E2B guest VA/PA; the QTest connection observes only the running QEMU process.
"""
import struct
import time

from qtest_pxa import equal
from smoke_security import read_bytes
from smoke_tasks import task_records

MACHINE = "crosshair-blueangel-display-test"
DISPLAY, INPUT, MAILBOX = 0x10000000, 0x10001000, 0xA0000100
FB_BYTES, USER_BASE, SHELL_PA = 153600, 0x01000000, 0xA0400000
FIELDS = """magic version stage error ticks switches current events_delivered frames input_drained
queue_len queue_dropped waits wakes busy_preemptions shell_preemptions fb_pa fb_bytes ttbr sctlr
dacr pid last_present_ptr last_present_len last_wait_frame last_irq_frame queue_capacity last_svc_psr
last_user_psr last_fault_kind api_rejections busy_counter_sample""".split()
SNAPSHOT = """screen desktop_selected launcher_selected settings_selected today_selected overlay
overlay_selected theme opened_mask history_depth events_processed revision renders runtime_valid
runtime_ticks runtime_switches""".split()
METRICS = """version valid ticks switches task_count ready_tasks running_tasks faulted_tasks working_ram_bytes
events_delivered input_overflows reserved""".split()
PROBE_RETURNS = [-14, -14, -22, -22, -22, -14, -22, -14, -38, -14, -22, 0]
ACTIONS = {"up": 0, "down": 1, "left": 2, "right": 3, "select": 4, "back": 5,
           "menu": 6, "home": 7, "soft-left": 8, "soft-right": 9, "switch": 10}


def physical(virtual):
    if not USER_BASE <= virtual < 0x01048000:
        raise ValueError(f"Shell User VA outside reserved extent: {virtual:#x}")
    return SHELL_PA + virtual - USER_BASE


def record(memory, address):
    return dict(zip(FIELDS, struct.unpack("<32I", read_bytes(memory, address, 128))))


def user_record(memory, symbols):
    values = struct.unpack("<44I", read_bytes(memory, physical(symbols["SHELL_USER_RECORD"]), 176))
    return dict(zip(("magic", "version", "state", "last_event"), values[:4]),
                snapshot=dict(zip(SNAPSHOT, values[4:20])), metrics=dict(zip(METRICS, values[20:32])),
                probe_returns=list(values[32:44]))


def wire(action):
    if not 0 <= action <= 12:
        raise ValueError("unknown logical Shell action")
    return ((action + 1) << 24) if action <= 6 else (8 << 24) | (0xE000 + action - 7)


def pointer_wire(x, y):
    if not 0 <= x < 240 or not 0 <= y < 320:
        raise ValueError("logical pointer outside240x320 guest image")
    return 0x08000000 | (0xF0000 + (y << 8) + x)


def pointer_coordinates(value):
    """Logical points in atomic emulator-reserved scalar blocks, not scan codes."""
    if value >> 24 != 8 or not 0x90000 <= (value & 0xFFFFFF) <= 0x10FFFF:
        return None
    point = ((value & 0xFFFFFF) - 0x90000) & 0x1FFFF
    x, y = point & 255, point >> 8
    return (x, y) if x < 240 and y < 320 else None


def pointer_phase_wire(phase, x=0, y=0, held_ms=0):
    """1Press/2Move/3Release/4Cancel/5measuredHold; invalid points are testable."""
    if phase in (1, 2, 3):
        if not 0 <= x <= 255 or not 0 <= y <= 511:
            raise ValueError("pointer carrier exceeds its bounded coordinate bits")
        base = {1: 0xD0000, 2: 0xB0000, 3: 0x90000}[phase]
        return 0x08000000 | (base + (y << 8) + x)
    if phase == 4:
        return 0x0800E006
    if phase == 5 and 0 <= held_ms <= 0xFFFFFFFF:
        return 0x08000000 | (0xE100 + min(held_ms, 4095))
    raise ValueError("invalid pointer phase or held duration")


def hardware_key_wire(edge, key):
    if edge not in (0, 1, 2) or not 0 <= key <= 12:
        raise ValueError("invalid semantic hardware key/edge")
    return 0x08000000 | (0xE010 + (edge << 4) + key)


UX_FIELDS = """version chrome_mode content_y content_height panel pointer_active pointer_target pointer_cancelled
scroll_offset scroll_max gesture_serial actions_invoked input_cancels last_phase panel_invocations mode_changes
held_keys last_key_phase last_key key_actions""".split()


def ux_record(memory, symbols):
    values = struct.unpack("<20I", read_bytes(memory, physical(symbols["SHELL_UX_METRICS"]), 80))
    return dict(zip(UX_FIELDS, values))


def await_stable(memory, symbols, user_symbols, events, process, timeout=30, shell_events=None):
    if shell_events is None:
        shell_events = events
    deadline = time.monotonic() + timeout
    while True:
        r = record(memory, symbols["CROSSHAIR_SHELL_RECORD"])
        if r["magic"] == 0x53484C4C and r["error"]:
            raise AssertionError(f"Shell kernel error: {r}")
        if r["magic"] == 0x53484C4C and r["stage"] == 2 and r["events_delivered"] == events and r["queue_len"] == 0:
            tasks = task_records(memory, symbols["TASKS"])
            if tasks[1]["state"] == 4:
                u = user_record(memory, user_symbols)
                if u["state"] == 2 and u["snapshot"]["events_processed"] == shell_events:
                    # TCG may finish a frame between the first header read and
                    # Waiting observation. Re-read publication fields rather
                    # than interpreting a torn live snapshot as guest failure.
                    r = record(memory, symbols["CROSSHAIR_SHELL_RECORD"])
                    if r["events_delivered"] == events and r["queue_len"] == 0 and memory.readl(DISPLAY + 0x14) == r["frames"] == u["snapshot"]["renders"]:
                        return r, u, tasks
        if process.poll() is not None or time.monotonic() >= deadline:
            raise TimeoutError(f"Shell did not finish event{events} and enter WaitEvent: rc={process.poll()}, record={r}")
        time.sleep(0.002)
