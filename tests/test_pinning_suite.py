#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
VirtualDesktopAccessor - Interactive & Automated Pinning Verification Suite

Tests the distinction between:
  1. PinWindow (individual window pinning)
  2. PinApp (entire application pinning with Task View parity)
  3. Dynamic desktop switch reconciliation (SyncPinnedApps)

Covers:
  - Windows Terminal (WinUI 3 XAML Islands / ~Wh~ sub-AUMIDs)
  - Windows Notepad (Modern packaged WinUI 3 tabbed app)
  - Classic Win32 / Any user-selected multi-window application
"""

import argparse
import ctypes
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

# Try importing pyvda for robust shell view inspection
try:
    import pyvda
    import pyvda.pyvda as pvd
    HAS_PYVDA = True
except ImportError:
    HAS_PYVDA = False

# Try importing win32gui for window titles and handles
try:
    import win32gui
    HAS_WIN32GUI = True
except ImportError:
    HAS_WIN32GUI = False


def find_dll_path() -> str:
    """Find the compiled VirtualDesktopAccessor DLL."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    candidates = [
        os.path.join(repo_root, "target", "release", "VirtualDesktopAccessor.dll"),
        os.path.join(repo_root, "target", "debug", "VirtualDesktopAccessor.dll"),
        os.path.join(repo_root, "dll", "VirtualDesktopAccessor.dll"),
        os.path.join(repo_root, "VirtualDesktopAccessor.dll"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(f"VirtualDesktopAccessor.dll not found. Searched: {candidates}")


class VdaBridge:
    """Wrapper around VirtualDesktopAccessor.dll C-exports."""

    def __init__(self, dll_path: str):
        self.dll = ctypes.cdll.LoadLibrary(dll_path)
        self._setup_signatures()

    def _setup_signatures(self):
        # Desktop navigation
        self.dll.GetCurrentDesktopNumber.restype = ctypes.c_int32
        self.dll.GetDesktopCount.restype = ctypes.c_int32
        self.dll.GoToDesktopNumber.argtypes = [ctypes.c_int32]
        self.dll.GoToDesktopNumber.restype = ctypes.c_int32
        self.dll.CreateDesktop.restype = ctypes.c_int32
        self.dll.RemoveDesktop.argtypes = [ctypes.c_int32, ctypes.c_int32]
        self.dll.RemoveDesktop.restype = ctypes.c_int32

        # Window state
        self.dll.IsWindowOnCurrentVirtualDesktop.argtypes = [ctypes.c_void_p]
        self.dll.IsWindowOnCurrentVirtualDesktop.restype = ctypes.c_int32
        self.dll.IsWindowOnDesktopNumber.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        self.dll.IsWindowOnDesktopNumber.restype = ctypes.c_int32
        self.dll.MoveWindowToDesktopNumber.argtypes = [ctypes.c_void_p, ctypes.c_int32]
        self.dll.MoveWindowToDesktopNumber.restype = ctypes.c_int32

        # Pinning
        self.dll.IsPinnedWindow.argtypes = [ctypes.c_void_p]
        self.dll.IsPinnedWindow.restype = ctypes.c_int32
        self.dll.PinWindow.argtypes = [ctypes.c_void_p]
        self.dll.PinWindow.restype = ctypes.c_int32
        self.dll.UnPinWindow.argtypes = [ctypes.c_void_p]
        self.dll.UnPinWindow.restype = ctypes.c_int32

        self.dll.IsPinnedApp.argtypes = [ctypes.c_void_p]
        self.dll.IsPinnedApp.restype = ctypes.c_int32
        self.dll.PinApp.argtypes = [ctypes.c_void_p]
        self.dll.PinApp.restype = ctypes.c_int32
        self.dll.UnPinApp.argtypes = [ctypes.c_void_p]
        self.dll.UnPinApp.restype = ctypes.c_int32

        # Sync
        if hasattr(self.dll, "SyncPinnedApps"):
            self.dll.SyncPinnedApps.restype = ctypes.c_int32
        else:
            self.dll.SyncPinnedApps = None

    def get_current_desktop(self) -> int:
        return self.dll.GetCurrentDesktopNumber()

    def get_desktop_count(self) -> int:
        return self.dll.GetDesktopCount()

    def go_to_desktop(self, num: int) -> bool:
        return self.dll.GoToDesktopNumber(num) == 1

    def is_window_on_current_desktop(self, hwnd: int) -> bool:
        return self.dll.IsWindowOnCurrentVirtualDesktop(hwnd) == 1

    def is_window_on_desktop(self, hwnd: int, desk_num: int) -> bool:
        return self.dll.IsWindowOnDesktopNumber(hwnd, desk_num) == 1

    def is_pinned_window(self, hwnd: int) -> bool:
        return self.dll.IsPinnedWindow(hwnd) == 1

    def pin_window(self, hwnd: int) -> bool:
        return self.dll.PinWindow(hwnd) == 1

    def unpin_window(self, hwnd: int) -> bool:
        return self.dll.UnPinWindow(hwnd) == 1

    def is_pinned_app(self, hwnd: int) -> bool:
        return self.dll.IsPinnedApp(hwnd) == 1

    def pin_app(self, hwnd: int) -> bool:
        return self.dll.PinApp(hwnd) == 1

    def unpin_app(self, hwnd: int) -> bool:
        return self.dll.UnPinApp(hwnd) == 1

    def sync_pinned_apps(self) -> int:
        if self.dll.SyncPinnedApps:
            return self.dll.SyncPinnedApps()
        return 0


class WindowInfo:
    def __init__(self, hwnd: int, app_id: str = "", base_app_id: str = "", title: str = ""):
        self.hwnd = hwnd
        self.app_id = app_id
        self.base_app_id = base_app_id or (app_id.split("~Wh~")[0] if "~Wh~" in app_id else app_id)
        self.title = title

    def __repr__(self):
        return f"Window(hwnd={self.hwnd:#x}, base_id='{self.base_app_id}', title='{self.title[:30]}')"


def get_active_app_windows() -> Dict[str, List[WindowInfo]]:
    """Enumerate all active managed windows grouped by canonical base_app_id."""
    grouped: Dict[str, List[WindowInfo]] = {}

    if HAS_PYVDA:
        try:
            # Refresh collection to eliminate stale/dead views
            if hasattr(pvd, "managers") and hasattr(pvd.managers, "view_collection"):
                try:
                    pvd.managers.view_collection.RefreshCollection()
                except Exception:
                    pass
            apps = pyvda.get_apps_by_z_order(switcher_windows=False, current_desktop=False)
            for a in apps:
                if not a.app_id or not a.hwnd:
                    continue
                title = ""
                if HAS_WIN32GUI:
                    try:
                        title = win32gui.GetWindowText(a.hwnd)
                    except Exception:
                        pass
                w = WindowInfo(hwnd=a.hwnd, app_id=a.app_id, base_app_id=a.base_app_id, title=title)
                grouped.setdefault(w.base_app_id, []).append(w)
        except Exception as e:
            print(f"  [Notice] pyvda enumeration error: {e}")

    return grouped


class TestSuiteRunner:
    def __init__(self, vda: VdaBridge, step_delay: float = 1.5, interactive: bool = False):
        self.vda = vda
        self.step_delay = step_delay
        self.interactive = interactive
        self.created_desktop_count = 0
        self.initial_desktop = vda.get_current_desktop()
        self.pinned_windows_to_clean: List[int] = []

    def pause(self, message: str = ""):
        """Pause between steps for visual inspection."""
        if message:
            print(f"      >> {message}")
        if self.interactive:
            input("      [Press Enter to proceed to next step...]")
        elif self.step_delay > 0:
            time.sleep(self.step_delay)

    def ensure_two_desktops(self) -> int:
        """Ensure at least 2 desktops exist. Returns target secondary desktop index."""
        count = self.vda.get_desktop_count()
        if count < 2:
            print("  [*] Only 1 virtual desktop found. Creating temporary test desktop...")
            new_idx = self.vda.dll.CreateDesktop()
            if new_idx >= 0:
                self.created_desktop_count += 1
                count = self.vda.get_desktop_count()
                print(f"  [*] Created temporary Desktop {new_idx}. Total desktops now: {count}")
            else:
                raise RuntimeError("Failed to create temporary virtual desktop for test.")
        
        # Target desktop is 0 if currently on 1+, else 1
        current = self.vda.get_current_desktop()
        target = 0 if current > 0 else 1
        return target

    def cleanup(self):
        """Restore original desktop state, unpin all test windows, clean temporary desktops."""
        print("\n=======================================================")
        print("  CLEANUP & RESTORATION")
        print("=======================================================")
        # Unpin any windows
        for hwnd in self.pinned_windows_to_clean:
            try:
                self.vda.unpin_app(hwnd)
            except Exception:
                pass
            try:
                self.vda.unpin_window(hwnd)
            except Exception:
                pass
        self.pinned_windows_to_clean.clear()

        # Restore original desktop
        curr = self.vda.get_current_desktop()
        if curr != self.initial_desktop:
            print(f"  [*] Restoring user to original Desktop {self.initial_desktop}...")
            self.vda.go_to_desktop(self.initial_desktop)
            time.sleep(0.5)

        print("  [OK] Workspace restored to clean state.\n")

    def run_window_vs_app_test(self, app_name: str, w1: WindowInfo, w2: WindowInfo):
        """Execute the comprehensive PinWindow vs PinApp test matrix on two windows."""
        print(f"\n-------------------------------------------------------")
        print(f"  TESTING TARGET: {app_name}")
        print(f"  Window 1: HWND {w1.hwnd:#x} ('{w1.title[:25]}') | ID: {w1.app_id}")
        print(f"  Window 2: HWND {w2.hwnd:#x} ('{w2.title[:25]}') | ID: {w2.app_id}")
        print(f"-------------------------------------------------------")

        self.pinned_windows_to_clean.extend([w1.hwnd, w2.hwnd])
        home_desktop = self.vda.get_current_desktop()
        target_desktop = self.ensure_two_desktops()

        print(f"  [Context] Home Desktop: {home_desktop} | Target Desktop: {target_desktop}")

        # Ensure both windows start unpinned
        self.vda.unpin_app(w1.hwnd)
        self.vda.unpin_window(w1.hwnd)
        self.vda.unpin_app(w2.hwnd)
        self.vda.unpin_window(w2.hwnd)

        assert not self.vda.is_pinned_window(w1.hwnd), "Window 1 must start unpinned"
        assert not self.vda.is_pinned_app(w1.hwnd), "Window 1 must start app-unpinned"
        assert not self.vda.is_pinned_window(w2.hwnd), "Window 2 must start unpinned"

        # =====================================================================
        # PHASE 1: PIN WINDOW (Individual Window Pinning)
        # =====================================================================
        print("\n  >>> PHASE 1: Testing PinWindow (Individual Window Only)")
        print(f"      Calling PinWindow(w1={w1.hwnd:#x})...")
        res_pw = self.vda.pin_window(w1.hwnd)
        assert res_pw, "PinWindow call must succeed"

        # Assert local states
        w1_is_pw = self.vda.is_pinned_window(w1.hwnd)
        w1_is_pa = self.vda.is_pinned_app(w1.hwnd)
        w2_is_pw = self.vda.is_pinned_window(w2.hwnd)
        w2_is_pa = self.vda.is_pinned_app(w2.hwnd)

        print(f"      Window 1: IsPinnedWindow={w1_is_pw}, IsPinnedApp={w1_is_pa}")
        print(f"      Window 2: IsPinnedWindow={w2_is_pw}, IsPinnedApp={w2_is_pa}")

        assert w1_is_pw == 1, "Window 1 MUST be pinned"
        assert w1_is_pa == 0, "Window 1 app MUST NOT be pinned when using PinWindow"
        assert w2_is_pw == 0, "Window 2 MUST NOT be pinned"
        assert w2_is_pa == 0, "Window 2 app MUST NOT be pinned"
        print("      [PASS] State verification on Home Desktop.")

        # Switch to Target Desktop and verify OS visibility
        print(f"      Switching to Desktop {target_desktop} to verify isolation...")
        self.vda.go_to_desktop(target_desktop)
        self.pause(f"Now on Desktop {target_desktop}: Window 1 should be VISIBLE, Window 2 should be HIDDEN")

        w1_on_target = self.vda.is_window_on_current_desktop(w1.hwnd)
        w2_on_target = self.vda.is_window_on_current_desktop(w2.hwnd)
        print(f"      Window 1 on Desktop {target_desktop}: {w1_on_target}")
        print(f"      Window 2 on Desktop {target_desktop}: {w2_on_target}")

        assert w1_on_target == 1, f"Window 1 MUST appear on Desktop {target_desktop}"
        assert w2_on_target == 0, f"Window 2 MUST NOT appear on Desktop {target_desktop} (isolation check)"
        print("      [PASS] Single-window isolation verified on Target Desktop.")

        # Return to home desktop and unpin
        self.vda.go_to_desktop(home_desktop)
        self.vda.unpin_window(w1.hwnd)
        assert not self.vda.is_pinned_window(w1.hwnd), "Window 1 unpin must succeed"
        self.pause(f"Returned to Desktop {home_desktop} and unpinned Window 1.")

        # =====================================================================
        # PHASE 2: PIN APP (Task View Parity & Sibling Synchronization)
        # =====================================================================
        print("\n  >>> PHASE 2: Testing PinApp (Task View Parity - Entire Application)")
        print(f"      Calling PinApp(w1={w1.hwnd:#x})...")
        res_pa = self.vda.pin_app(w1.hwnd)
        assert res_pa, "PinApp call must succeed"

        # Assert local states
        w1_is_pw = self.vda.is_pinned_window(w1.hwnd)
        w1_is_pa = self.vda.is_pinned_app(w1.hwnd)
        w2_is_pw = self.vda.is_pinned_window(w2.hwnd)
        w2_is_pa = self.vda.is_pinned_app(w2.hwnd)

        print(f"      Window 1: IsPinnedWindow={w1_is_pw}, IsPinnedApp={w1_is_pa}")
        print(f"      Window 2: IsPinnedWindow={w2_is_pw}, IsPinnedApp={w2_is_pa}")

        assert w1_is_pa == 1, "Window 1 app MUST report pinned"
        assert w1_is_pw == 1, "Window 1 view MUST be pinned"
        assert w2_is_pa == 1, "Window 2 app MUST report pinned (same package)"
        assert w2_is_pw == 1, "Window 2 view MUST be synchronized by PinApp (Task View parity)!"
        print("      [PASS] Sibling synchronization verified on Home Desktop.")

        # Switch to Target Desktop and verify both are present
        print(f"      Switching to Desktop {target_desktop} to verify full app propagation...")
        self.vda.go_to_desktop(target_desktop)
        self.pause(f"Now on Desktop {target_desktop}: BOTH Window 1 AND Window 2 should be VISIBLE!")

        w1_on_target = self.vda.is_window_on_current_desktop(w1.hwnd)
        w2_on_target = self.vda.is_window_on_current_desktop(w2.hwnd)
        print(f"      Window 1 on Desktop {target_desktop}: {w1_on_target}")
        print(f"      Window 2 on Desktop {target_desktop}: {w2_on_target}")

        assert w1_on_target == 1, f"Window 1 MUST appear on Desktop {target_desktop}"
        assert w2_on_target == 1, f"Window 2 MUST appear on Desktop {target_desktop} (multi-window propagation)!"
        print("      [PASS] Multi-window presence verified on Target Desktop.")

        # Return to home desktop
        self.vda.go_to_desktop(home_desktop)

        # =====================================================================
        # PHASE 3: DYNAMIC RECONCILIATION (SyncPinnedApps)
        # =====================================================================
        print("\n  >>> PHASE 3: Testing Desktop Switch Reconciliation (SyncPinnedApps)")
        print("      Simulating an unpinned secondary window while app is pinned...")
        # Unpin w2's view alone while app is still pinned
        self.vda.unpin_window(w2.hwnd)
        assert self.vda.is_pinned_window(w2.hwnd) == 0, "Window 2 view temporarily unpinned"
        assert self.vda.is_pinned_app(w2.hwnd) == 1, "App is still pinned"

        print(f"      Switching to Desktop {target_desktop} (switch_desktop automatically triggers SyncPinnedApps)...")
        self.vda.go_to_desktop(target_desktop)
        self.pause(f"On Desktop {target_desktop}: switch_desktop should have auto-reconciled Window 2!")

        # Verify Window 2 view was automatically re-pinned
        w2_is_reconciled = self.vda.is_pinned_window(w2.hwnd)
        w2_on_target_now = self.vda.is_window_on_current_desktop(w2.hwnd)
        print(f"      Window 2 IsPinnedWindow after switch: {w2_is_reconciled}")
        print(f"      Window 2 on Desktop {target_desktop}: {w2_on_target_now}")

        assert w2_is_reconciled == 1, "Window 2 MUST have been auto-pinned by switch_desktop sync!"
        assert w2_on_target_now == 1, "Window 2 MUST be visible on target desktop!"
        print("      [PASS] Dynamic desktop-switch reconciliation verified.")

        # Return to home desktop and clean up app pin
        self.vda.go_to_desktop(home_desktop)
        print("      Calling UnPinApp(w1)...")
        self.vda.unpin_app(w1.hwnd)

        assert self.vda.is_pinned_app(w1.hwnd) == 0, "Window 1 app unpinned"
        assert self.vda.is_pinned_window(w1.hwnd) == 0, "Window 1 view unpinned"
        assert self.vda.is_pinned_app(w2.hwnd) == 0, "Window 2 app unpinned"
        assert self.vda.is_pinned_window(w2.hwnd) == 0, "Window 2 view unpinned"
        print("      [PASS] Clean application teardown verified.")
        print(f"  [SUCCESS] Target {app_name} passed all 3 verification phases!\n")


def main():
    parser = argparse.ArgumentParser(description="VirtualDesktopAccessor Pinning Test Suite")
    parser.add_argument("--watch", action="store_true", help="Pause between steps so you can visually watch windows migrate")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay in seconds between steps when watching (default: 2.0s)")
    parser.add_argument("--interactive", action="store_true", help="Prompt [Enter] before each action (manual inspection mode)")
    parser.add_argument("--auto-spawn", action="store_true", help="Automatically spawn test instances of Notepad/Terminal if missing")
    parser.add_argument("--target", type=str, default="", help="Filter specific target (e.g. 'terminal', 'notepad', 'other', 'all')")
    args = parser.parse_args()

    dll_path = find_dll_path()
    print("=======================================================")
    print("  VirtualDesktopAccessor - Pinning Verification Suite")
    print("=======================================================")
    print(f"  DLL: {dll_path}")

    vda = VdaBridge(dll_path)
    curr_desk = vda.get_current_desktop()
    total_desk = vda.get_desktop_count()
    print(f"  Current Virtual Desktop: {curr_desk} (Total Desktops: {total_desk})")

    step_delay = args.delay if args.watch else (0.2 if not args.interactive else 0)
    runner = TestSuiteRunner(vda, step_delay=step_delay, interactive=args.interactive)
    spawned_processes = []

    try:
        active_apps = get_active_app_windows()

        # Target 1: Windows Terminal
        terminal_key = next((k for k in active_apps if "terminal" in k.lower()), None)
        terminal_wins = active_apps.get(terminal_key, []) if terminal_key else []

        # Target 2: Notepad
        notepad_key = next((k for k in active_apps if "notepad" in k.lower()), None)
        notepad_wins = active_apps.get(notepad_key, []) if notepad_key else []

        # Auto-spawn if requested
        if args.auto_spawn:
            import subprocess
            if ("terminal" in args.target.lower() or not args.target) and len(terminal_wins) < 2:
                print("  [*] Auto-spawning 2 Windows Terminal windows...")
                p1 = subprocess.Popen(["wt.exe", "-w", "test_win_1"])
                time.sleep(1.0)
                p2 = subprocess.Popen(["wt.exe", "-w", "test_win_2"])
                time.sleep(2.0)
                spawned_processes.extend([p1, p2])
                active_apps = get_active_app_windows()
                terminal_key = next((k for k in active_apps if "terminal" in k.lower()), None)
                terminal_wins = active_apps.get(terminal_key, []) if terminal_key else []

            if ("notepad" in args.target.lower() or not args.target) and len(notepad_wins) < 2:
                print("  [*] Auto-spawning Notepad instances...")
                p1 = subprocess.Popen(["notepad.exe"])
                time.sleep(1.0)
                p2 = subprocess.Popen(["notepad.exe"])
                time.sleep(1.5)
                spawned_processes.extend([p1, p2])
                active_apps = get_active_app_windows()
                notepad_key = next((k for k in active_apps if "notepad" in k.lower()), None)
                notepad_wins = active_apps.get(notepad_key, []) if notepad_key else []

        print(f"\n  Discovered active managed applications: {len(active_apps)}")
        for base_id, win_list in active_apps.items():
            print(f"    - {base_id}: {len(win_list)} window(s)")

        # Target 3: Other multi-window applications (e.g. IDE, Explorer, Chrome)
        other_candidates = [(k, v) for k, v in active_apps.items() if len(v) >= 2 and k not in (terminal_key, notepad_key)]

        targets_to_run = []

        if not args.target or "terminal" in args.target.lower() or args.target.lower() == "all":
            if len(terminal_wins) >= 2:
                targets_to_run.append(("Windows Terminal (XAML Island / ~Wh~)", terminal_wins[0], terminal_wins[1]))
            else:
                print("\n  [!] Windows Terminal has less than 2 open windows.")
                print("      Please open 2 Windows Terminal windows (e.g. open terminal and press Ctrl+Shift+N or tear off a tab).")
                if args.interactive:
                    input("      Open 2 Windows Terminal windows now, then press Enter to scan again...")
                    active_apps = get_active_app_windows()
                    terminal_key = next((k for k in active_apps if "terminal" in k.lower()), None)
                    terminal_wins = active_apps.get(terminal_key, []) if terminal_key else []
                    if len(terminal_wins) >= 2:
                        targets_to_run.append(("Windows Terminal (XAML Island / ~Wh~)", terminal_wins[0], terminal_wins[1]))
                    else:
                        print(f"      Found {len(terminal_wins)} terminal window(s). Skipping Terminal test.")
                else:
                    print("      Tip: Run with --interactive to pause and detect when you open them, or use --auto-spawn.")

        if not args.target or "notepad" in args.target.lower() or args.target.lower() == "all":
            if len(notepad_wins) >= 2:
                targets_to_run.append(("Windows Notepad (Packaged WinUI 3)", notepad_wins[0], notepad_wins[1]))
            else:
                print("\n  [!] Windows Notepad has less than 2 open windows.")
                print("      Tip: In Notepad, press Ctrl+Shift+N to open a second window.")
                if args.interactive:
                    input("      Open 2 Notepad windows now, then press Enter to scan again...")
                    active_apps = get_active_app_windows()
                    notepad_key = next((k for k in active_apps if "notepad" in k.lower()), None)
                    notepad_wins = active_apps.get(notepad_key, []) if notepad_key else []
                    if len(notepad_wins) >= 2:
                        targets_to_run.append(("Windows Notepad (Packaged WinUI 3)", notepad_wins[0], notepad_wins[1]))
                    else:
                        print(f"      Found {len(notepad_wins)} Notepad window(s). Skipping Notepad test.")

        # Include other multi-window apps if available
        if other_candidates and (not args.target or "other" in args.target.lower() or args.target.lower() == "all"):
            cand_name, cand_wins = other_candidates[0]
            targets_to_run.append((f"Multi-Window App ({cand_name})", cand_wins[0], cand_wins[1]))

        if not targets_to_run:
            print("\n  [!] No target with 2+ windows found to execute.")
            print("  Please open 2 instances of Windows Terminal or Notepad and re-run:")
            print("    py -3.10 tests/test_pinning_suite.py --interactive --watch")
            sys.exit(1)

        print(f"\n  [*] Ready to execute tests across {len(targets_to_run)} application target(s).")
        for app_label, w1, w2 in targets_to_run:
            runner.run_window_vs_app_test(app_label, w1, w2)

        print("\n=======================================================")
        print("  ALL PINNING VERIFICATION SUITES PASSED WITH 100% SUCCESS!")
        print("=======================================================\n")

    finally:
        for p in spawned_processes:
            try:
                p.terminate()
            except Exception:
                pass
        runner.cleanup()


if __name__ == "__main__":
    main()
