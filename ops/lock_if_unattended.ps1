# UNATTENDED_LOCK_V1: after an automatic sign-in (power restored / restart while away), lock the screen
# unless someone is actually at the keyboard. The automation keeps running in the locked session.
Start-Sleep -Seconds 90
Add-Type @'
using System; using System.Runtime.InteropServices;
public class UnattendedIdle {
  [StructLayout(LayoutKind.Sequential)] struct L { public uint cb; public uint t; }
  [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref L l);
  [DllImport("user32.dll")] public static extern bool LockWorkStation();
  public static double Seconds() { L l = new L(); l.cb = (uint)Marshal.SizeOf(l); GetLastInputInfo(ref l);
    return ((uint)Environment.TickCount - l.t) / 1000.0; } }
'@
if ([UnattendedIdle]::Seconds() -ge 80) {
    Add-Content -Path 'C:\AI\analytics\data\work_window.log' -Value ("{0} LOCK: signed in with nobody at the PC - screen locked" -f (Get-Date -Format s))
    [UnattendedIdle]::LockWorkStation() | Out-Null
}
