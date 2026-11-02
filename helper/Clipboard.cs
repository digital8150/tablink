using System.Runtime.InteropServices;

/// <summary>Accesses the Windows clipboard.</summary>
internal static class Clipboard
{
    [DllImport("user32.dll")]
    private static extern bool OpenClipboard(nint owner);

    [DllImport("user32.dll")]
    private static extern bool CloseClipboard();

    [DllImport("user32.dll")]
    private static extern bool EmptyClipboard();

    [DllImport("user32.dll")]
    private static extern nint GetClipboardData(uint format);

    [DllImport("user32.dll")]
    private static extern nint SetClipboardData(uint format, nint memory);

    [DllImport("user32.dll")]
    internal static extern uint GetClipboardSequenceNumber();

    [DllImport("kernel32.dll")]
    private static extern nint GlobalAlloc(uint flags, nuint size);

    [DllImport("kernel32.dll")]
    private static extern nint GlobalLock(nint memory);

    [DllImport("kernel32.dll")]
    private static extern bool GlobalUnlock(nint memory);

    [DllImport("kernel32.dll")]
    private static extern nint GlobalFree(nint memory);

    private static bool Open()
    {
        for (int i = 0; i < 5; i++)
        {
            if (OpenClipboard(0))
                return true;
            Thread.Sleep(20);
        }

        return false;
    }

    internal static string? Get()
    {
        if (!Open())
            return null;
        try
        {
            nint h = GetClipboardData(13);
            if (h == 0)
                return null;
            nint p = GlobalLock(h);
            if (p == 0)
                return null;
            try
            {
                return Marshal.PtrToStringUni(p);
            }
            finally
            {
                GlobalUnlock(h);
            }
        }
        finally
        {
            CloseClipboard();
        }
    }

    internal static bool Set(string text)
    {
        if (!Open())
            return false;
        try
        {
            if (!EmptyClipboard())
                return false;
            nint h = GlobalAlloc(2, (nuint)((text.Length + 1) * 2));
            if (h == 0)
                return false;
            nint p = GlobalLock(h);
            if (p == 0)
            {
                GlobalFree(h);
                return false;
            }

            Marshal.Copy((text + '\0').ToCharArray(), 0, p, text.Length + 1);
            GlobalUnlock(h);
            if (SetClipboardData(13, h) != 0)
                return true;
            GlobalFree(h);
            return false;
        }
        finally
        {
            CloseClipboard();
        }
    }
}
