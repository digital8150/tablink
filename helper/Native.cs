using System.Runtime.InteropServices;

/// <summary>Declares Windows native interop types and functions.</summary>
internal static class Native
{
    [StructLayout(LayoutKind.Sequential)]
    internal struct Rect
    {
        internal int Left;

        internal int Top;

        internal int Right;

        internal int Bottom;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    internal struct MonitorInfo
    {
        internal uint Size;

        internal Rect Monitor;

        internal Rect Work;

        internal uint Flags;

        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)]
        internal string Name;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    internal struct WindowClass
    {
        internal uint Size;

        internal uint Style;

        internal nint Procedure;

        internal int ClassExtra;

        internal int WindowExtra;

        internal nint Instance;

        internal nint Icon;

        internal nint Cursor;

        internal nint Background;

        internal nint MenuName;

        [MarshalAs(UnmanagedType.LPWStr)]
        internal string ClassName;

        internal nint SmallIcon;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct Message
    {
        internal nint Hwnd;

        internal uint Id;

        internal nuint WParam;

        internal nint LParam;

        internal uint Time;

        internal int X;

        internal int Y;

        internal uint Private;
    }

    internal delegate bool MonitorCallback(nint monitor, nint dc, nint rect, nint data);

    internal delegate nint HookProc(int code, nuint wparam, nint lparam);

    internal delegate nint WindowProc(nint hwnd, uint msg, nuint wparam, nint lparam);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool SetProcessDpiAwarenessContext(nint context);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool EnumDisplayMonitors(nint dc, nint clip, MonitorCallback callback, nint data);

    [DllImport("user32.dll", EntryPoint = "GetMonitorInfoW", CharSet = CharSet.Unicode)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool GetMonitorInfo(nint monitor, ref MonitorInfo info);

    [DllImport("kernel32.dll")]
    internal static extern uint GetCurrentThreadId();

    [DllImport("kernel32.dll", EntryPoint = "GetModuleHandleW", CharSet = CharSet.Unicode)]
    internal static extern nint GetModuleHandle(string? name);

    [DllImport("user32.dll", EntryPoint = "RegisterClassExW", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern ushort RegisterClassEx(ref WindowClass wc);

    [DllImport("user32.dll", EntryPoint = "CreateWindowExW", CharSet = CharSet.Unicode, SetLastError = true)]
    internal static extern nint CreateWindowEx(uint ex, string cls, string name, uint style, int x, int y, int w, int h, nint parent, nint menu, nint instance, nint param);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool SetLayeredWindowAttributes(nint hwnd, uint key, byte alpha, uint flags);

    [DllImport("user32.dll", EntryPoint = "SetWindowsHookExW", SetLastError = true)]
    internal static extern nint SetWindowsHookEx(int id, HookProc proc, nint instance, uint thread);

    [DllImport("user32.dll")]
    internal static extern nint CallNextHookEx(nint hook, int code, nuint wp, nint lp);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool UnhookWindowsHookEx(nint hook);

    [DllImport("user32.dll", EntryPoint = "DefWindowProcW")]
    internal static extern nint DefWindowProc(nint hwnd, uint msg, nuint wp, nint lp);

    [DllImport("user32.dll")]
    internal static extern nint SetCursor(nint cursor);

    [DllImport("user32.dll", EntryPoint = "GetMessageW")]
    internal static extern int GetMessage(out Message msg, nint hwnd, uint min, uint max);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool TranslateMessage(ref Message msg);

    [DllImport("user32.dll", EntryPoint = "DispatchMessageW")]
    internal static extern nint DispatchMessage(ref Message msg);

    [DllImport("user32.dll", EntryPoint = "PostThreadMessageW")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool PostThreadMessage(uint id, uint msg, nuint wp, nint lp);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool DestroyWindow(nint hwnd);

    [StructLayout(LayoutKind.Sequential)]
    internal struct Point
    {
        internal int X;

        internal int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct MouseData
    {
        internal Point Point;

        internal uint Data;

        internal uint Flags;

        internal uint Time;

        internal nuint Extra;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct KeyData
    {
        internal uint Vk;

        internal uint Scan;

        internal uint Flags;

        internal uint Time;

        internal nuint Extra;
    }

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool GetCursorPos(out Point point);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool SetWindowPos(nint hwnd, nint after, int x, int y, int w, int h, uint flags);

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static extern bool ShowWindowAsync(nint hwnd, int command);
}
