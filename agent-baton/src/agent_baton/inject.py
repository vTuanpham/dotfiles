"""Type a secret into a Windows window at the OS level, without it touching a command line.

Works for anything on the desktop: the host Chrome, a WSLg window (Windows draws it too), any
app. The target window is found by the title the human approved on the form; the script
re-checks that window is the foreground one and not a terminal right before it types.
The secret travels on PowerShell's stdin, never in its arguments, so a process listing cannot show it."""

import base64
import json
import shutil
import subprocess

from agent_baton import x11

POWERSHELL = "powershell.exe"
SEND_TIMEOUT_S = 30
CODES = {
    2: "no visible window matches that title",
    3: "could not bring that window to the front",
    4: "the front window changed before typing; nothing was typed",
    5: "that window is on the never-type list (a terminal or agent UI)",
    6: "the typing payload is missing or empty",
    7: "typing stopped or Windows rejected input; entry may be incomplete",
    8: "the approved window is not in front; run focus, click its field, then type",
}
HELPERS = r"""
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.Text; using System.Collections.Generic;
public static class Bt {
  public static IntPtr InputTarget;
  delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc p, IntPtr l);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] static extern void keybd_event(byte vk, byte scan, uint flags, UIntPtr extra);
  [DllImport("user32.dll")] static extern uint SendInput(uint n, INPUT[] i, int size);
  [StructLayout(LayoutKind.Sequential)] struct KEYBDINPUT { public ushort vk; public ushort scan; public uint flags; public uint time; public IntPtr extra; }
  [StructLayout(LayoutKind.Explicit, Size=40)] struct INPUT { [FieldOffset(0)] public uint type; [FieldOffset(8)] public KEYBDINPUT ki; }
  public static string Title(IntPtr h) { var s = new StringBuilder(512); GetWindowText(h, s, 512); return s.ToString(); }
  public static List<IntPtr> Windows() {
    var found = new List<IntPtr>();
    EnumWindows((h, l) => { if (IsWindowVisible(h) && Title(h).Length > 0) found.Add(h); return true; }, IntPtr.Zero);
    return found;
  }
  public static bool Focus(IntPtr h) {
    if (IsIconic(h)) ShowWindow(h, 9);
    // Alt steals the focused browser field even when the window is already active.
    if (GetForegroundWindow() == h) return true;
    SetForegroundWindow(h);
    System.Threading.Thread.Sleep(250);
    if (GetForegroundWindow() == h) return true;
    keybd_event(0x12, 0, 0, UIntPtr.Zero); SetForegroundWindow(h); keybd_event(0x12, 0, 2, UIntPtr.Zero);
    System.Threading.Thread.Sleep(250);
    return GetForegroundWindow() == h;
  }
  static void Key(ushort vk, ushort scan, uint flags) {
    if ((flags & 2) == 0 && InputTarget != IntPtr.Zero && GetForegroundWindow() != InputTarget)
      throw new InvalidOperationException("The approved window lost keyboard focus");
    var i = new INPUT[1]; i[0].type = 1; i[0].ki.vk = vk; i[0].ki.scan = scan; i[0].ki.flags = flags;
    if (SendInput(1, i, 40) != 1) throw new InvalidOperationException("Windows rejected keyboard input");
  }
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern short VkKeyScan(char c);
  [DllImport("user32.dll")] static extern uint MapVirtualKey(uint code, uint type);
  // Real key codes, because Unicode key events are dropped by WSLg windows; Unicode only for characters the layout lacks.
  public static void Text(string text) {
    foreach (char c in text) {
      short r = VkKeyScan(c);
      if (r == -1) { Key(0, c, 4); Key(0, c, 6); }
      else {
        ushort vk = (ushort)(r & 0xFF); ushort scan = (ushort)MapVirtualKey(vk, 0); bool shift = (r & 0x100) != 0;
        if (shift) Key(0x10, 0x2A, 0);
        try { Key(vk, scan, 0); Key(vk, scan, 2); }
        finally { if (shift) Key(0x10, 0x2A, 2); }
      }
      System.Threading.Thread.Sleep(12);
    }
  }
  public static void Enter() { Key(13, 0, 0); Key(13, 0, 2); }
  public static void Clear() {
    Key(0x11, 0x1D, 0);
    try { Key(0x41, 0x1E, 0); Key(0x41, 0x1E, 2); }
    finally { Key(0x11, 0x1D, 2); }
    Key(8, 0x0E, 0); Key(8, 0x0E, 2);
  }
}
"@
"""
LIST = (
    HELPERS
    + r"""
[Bt]::Windows() | ForEach-Object { [Bt]::Title($_) } | Select-Object -Unique
"""
)
TYPE = (
    HELPERS
    + r"""
$ErrorActionPreference = 'Stop'
trap { exit 7 }
$job = [Console]::In.ReadToEnd() | ConvertFrom-Json
if (-not $job.focus -and ($job.text -isnot [string] -or $job.text.Length -eq 0)) { exit 6 }
$match = [Bt]::Windows() | Where-Object { [Bt]::Title($_).ToLower().Contains($job.window.ToLower()) } | Select-Object -First 1
if (-not $match) { exit 2 }
$front = [Bt]::Title($match).ToLower()
if (-not $front.Contains($job.window.ToLower())) { exit 4 }
foreach ($bad in $job.deny) { if ($front.Contains($bad.ToLower())) { exit 5 } }
if ($job.focus) {
  if (-not [Bt]::Focus($match)) { exit 3 }
  exit 0
}
if ([Bt]::GetForegroundWindow() -ne $match) { exit 8 }
[Bt]::InputTarget = $match
if ($job.clear) { [Bt]::Clear() }
[Bt]::Text($job.text)
if ($job.enter) { [Bt]::Enter() }
"""
)


def run_script(script, stdin="", *, timeout=SEND_TIMEOUT_S):
    if not shutil.which(POWERSHELL):
        raise FileNotFoundError(POWERSHELL)
    # EncodedCommand controls source encoding, not Windows console pipes.
    script = (
        "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false); "
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false);\n"
        + script
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        input=stdin,
        capture_output=True,
        encoding="utf-8",
        timeout=timeout,
    )


def windows():
    result = run_script(LIST)
    return [line.strip() for line in result.stdout.replace("\r", "").splitlines() if line.strip()]


def type_into(window, text, enter, deny, clear=False):
    """Return a status line; never the text. The payload goes in on stdin."""
    handled = x11.type_into(window, text, enter, deny, clear)  # WSLg windows only accept X11 input
    if handled is not None:
        return handled
    job = json.dumps(
        {"window": window, "text": text, "enter": bool(enter), "deny": deny, "clear": bool(clear)}
    )
    result = run_script(TYPE, stdin=job)
    if result.returncode:
        return f"refused: {CODES.get(result.returncode, f'powershell exited {result.returncode}')}"
    return "typed" + (" and pressed Enter" if enter else "")


def focus(window, deny):
    """Activate an approved window before the harness selects its input field."""
    handled = x11.type_into(window, "", False, deny)
    if handled is not None:
        return "focused; click the field before typing" if handled == "typed" else handled
    result = run_script(TYPE, stdin=json.dumps({"window": window, "deny": deny, "focus": True}))
    if result.returncode:
        return f"refused: {CODES.get(result.returncode, f'powershell exited {result.returncode}')}"
    return "focused; click the field before typing"
