using System.Runtime.InteropServices;

/// <summary>Handles Windows input hooks.</summary>
internal sealed class InputHook
{
    private const uint WmQuit = 0x12;

    private const uint WmSetCursor = 0x20;

    private const uint WmDisplayChange = 0x7e;

    private readonly Native.HookProc mouse;

    private readonly Native.HookProc keyboard;

    private readonly Native.WindowProc window;

    private readonly Action displayChanged;

    private readonly ManualResetEventSlim ready = new(false);

    private readonly Thread thread;

    private uint threadId;

    private nint hwnd;

    internal MultiControl? Control;

    private Exception? failure;

    internal InputHook(Action displayChanged)
    {
        this.displayChanged = displayChanged;
        mouse = MouseProc;
        keyboard = KeyProc;
        window = WindowProc;
        thread = new Thread(Run)
        {
            IsBackground = true,
            Name = "Input hooks"
       
   };
    }

    internal void Start()
    {
        thread.Start();
        if (!ready.Wait(TimeSpan.FromSeconds(5)))
            throw new InvalidOperationException("Hook thread did not start");
        if (failure != null)
            throw new InvalidOperationException("Could not install input hooks", failure);
    }

    internal void Stop()
    {
        if (threadId != 0)
            Native.PostThreadMessage(threadId, WmQuit, 0, 0);
        thread.Join(5000);
    }

    private nint MouseProc(int code, nuint wp, nint lp)
    {
        try
        {
            if (code == 0)
            {
                var d = Marshal.PtrToStructure<Native.MouseData>(lp);
                if (Control?.Mouse((uint)wp, d.Point.X, d.Point.Y, d.Data, (d.Flags & 1) != 0) == true)
                    return 1;
            }
        }
        catch (Exception e)
        {
            ThreadPool.QueueUserWorkItem(_ => Json.Log(e.Message));
        }

        return Native.CallNextHookEx(0, code, wp, lp);
    }

    private nint KeyProc(int code, nuint wp, nint lp)
    {
        try
        {
            if (code == 0)
            {
                var d = Marshal.PtrToStructure<Native.KeyData>(lp);
                if (Control?.Key((int)d.Vk, (int)d.Scan, (d.Flags & 1) != 0, (uint)wp is 0x100 or 0x104, (d.Flags & 0x10) != 0) == true)
                    return 1;
            }
        }
        catch (Exception e)
        {
            ThreadPool.QueueUserWorkItem(_ => Json.Log(e.Message));
        }

        return Native.CallNextHookEx(0, code, wp, lp);
    }

    private nint WindowProc(nint hwnd, uint msg, nuint wp, nint lp)
    {
        if (msg == WmSetCursor)
        {
            Native.SetCursor(0);
            return 1;
        }

        if (msg == WmDisplayChange)
        {
            try
            {
                displayChanged();
            }
            catch (Exception e)
            {
                Json.Log(e.Message);
            }
        }

        return Native.DefWindowProc(hwnd, msg, wp, lp);
    }

    internal void ShowBlocker(int x, int y)
    {
        if (hwnd != 0)
            Native.SetWindowPos(hwnd, -1, x - 24, y - 24, 48, 48, 0x4050);
    } // NOACTIVATE|SHOWWINDOW|ASYNCWINDOWPOS: never block on the hook thread

    internal void HideBlocker()
    {
        if (hwnd != 0)
            Native.ShowWindowAsync(hwnd, 0);
    }

    private void Run()
    {
        nint mh = 0, kh = 0;
        try
        {
            threadId = Native.GetCurrentThreadId();
            nint instance = Native.GetModuleHandle(null);
            var wc = new Native.WindowClass
            {
                Size = (uint)Marshal.SizeOf<Native.WindowClass>(),
                Procedure = Marshal.GetFunctionPointerForDelegate(window),
                Instance = instance,
                ClassName = "TabLinkCursorBlocker"
           
       };
            if (Native.RegisterClassEx(ref wc) == 0)
                throw new System.ComponentModel.Win32Exception();
            hwnd = Native.CreateWindowEx(0x08080088, wc.ClassName, "TabLink cursor blocker", 0x80000000, 0, 0, 48, 48, 0, 0, instance, 0);
            if (hwnd == 0)
                throw new System.ComponentModel.Win32Exception();
            if (!Native.SetLayeredWindowAttributes(hwnd, 0, 1, 2))
                throw new System.ComponentModel.Win32Exception();
            mh = Native.SetWindowsHookEx(14, mouse, instance, 0);
            kh = Native.SetWindowsHookEx(13, keyboard, instance, 0);
            if (mh == 0 || kh == 0)
                throw new System.ComponentModel.Win32Exception();
            ready.Set();
            while (Native.GetMessage(out var msg, 0, 0, 0) > 0)
            {
                Native.TranslateMessage(ref msg);
                Native.DispatchMessage(ref msg);
            }
        }
        catch (Exception e)
        {
            failure = e;
            ready.Set();
        }
        finally
        {
            if (mh != 0)
                Native.UnhookWindowsHookEx(mh);
            if (kh != 0)
                Native.UnhookWindowsHookEx(kh);
            if (hwnd != 0)
                Native.DestroyWindow(hwnd);
        }
    }
}
