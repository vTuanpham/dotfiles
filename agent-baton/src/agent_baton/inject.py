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
}
HELPERS = r"""
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices; using System.Text; using System.Collections.Generic;
public static class Bt {
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
    keybd_event(0x12, 0, 0, UIntPtr.Zero); SetForegroundWindow(h); keybd_event(0x12, 0, 2, UIntPtr.Zero);
    System.Threading.Thread.Sleep(250);
    return GetForegroundWindow() == h;
  }
  static void Key(ushort vk, ushort scan, uint flags) {
    var i = new INPUT[1]; i[0].type = 1; i[0].ki.vk = vk; i[0].ki.scan = scan; i[0].ki.flags = flags;
    SendInput(1, i, 40);
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
        Key(vk, scan, 0); Key(vk, scan, 2);
        if (shift) Key(0x10, 0x2A, 2);
      }
      System.Threading.Thread.Sleep(12);
    }
  }
  public static void Enter() { Key(13, 0, 0); Key(13, 0, 2); }
  public static void Clear() { Key(0x11, 0x1D, 0); Key(0x41, 0x1E, 0); Key(0x41, 0x1E, 2); Key(0x11, 0x1D, 2); Key(8, 0x0E, 0); Key(8, 0x0E, 2); }
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
$job = [Console]::In.ReadToEnd() | ConvertFrom-Json
$match = [Bt]::Windows() | Where-Object { [Bt]::Title($_).ToLower().Contains($job.window.ToLower()) } | Select-Object -First 1
if (-not $match) { exit 2 }
if (-not [Bt]::Focus($match)) { exit 3 }
$front = [Bt]::Title([Bt]::GetForegroundWindow()).ToLower()
if (-not $front.Contains($job.window.ToLower())) { exit 4 }
foreach ($bad in $job.deny) { if ($front.Contains($bad.ToLower())) { exit 5 } }
if ($job.clear) { [Bt]::Clear() }
[Bt]::Text($job.text)
if ($job.enter) { [Bt]::Enter() }
"""
)


def run_script(script, stdin=""):
    if not shutil.which(POWERSHELL):
        raise FileNotFoundError(POWERSHELL)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode()
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=SEND_TIMEOUT_S,
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
