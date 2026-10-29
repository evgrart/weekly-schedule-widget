param([long]$WindowHandle, [string]$OutputPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class DemoCapture {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr c);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, System.Text.StringBuilder b, int n);
  public struct RECT { public int L,T,R,B; }
}
'@
[void][DemoCapture]::SetProcessDpiAwarenessContext([IntPtr](-4))
$handle = [IntPtr]$WindowHandle
$title = New-Object System.Text.StringBuilder 256
[void][DemoCapture]::GetWindowText($handle,$title,256)
if ($title.ToString() -ne 'Weekly Schedule Demo') { throw 'Only the synthetic demo window may be captured.' }
$rect = New-Object DemoCapture+RECT
if (-not [DemoCapture]::GetWindowRect($handle,[ref]$rect)) { throw 'Missing demo window' }
$bitmap = New-Object System.Drawing.Bitmap ($rect.R-$rect.L),($rect.B-$rect.T)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$dc = $graphics.GetHdc()
try {
    if (-not [DemoCapture]::PrintWindow($handle,$dc,2)) { throw 'Capture failed' }
} finally { $graphics.ReleaseHdc($dc) }
try { $bitmap.Save($OutputPath) } finally { $graphics.Dispose(); $bitmap.Dispose() }
