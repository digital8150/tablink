using System.Runtime.InteropServices;
using System.Text.Json;

/// <summary>Coordinates input control across displays.</summary>
internal sealed class MultiControl
{
    private readonly InputHook hook;

    private ScrcpyControl? ctrl;

    private TabletInfo info = new();

    private List<Monitor> monitors = [];

    private Monitor? mon;

    private bool enabled = true;

    private bool clipboard = true;

    private bool active;

    private string side = "right";

    private string hangul = "shift_space";

    private int monitor = -1;

    private double speed = 1;

    private int parkX;

    private int parkY;

    private int exitX;

    private int exitY;

    private int buttons;

    private int pcButtons;

    private int edgeHits;

    private int wheel;

    private int hwheel;

    private int mods;

    private double tx;

    private double ty;

    private double rx;

    private double ry;

    private readonly List<int> keys = [];

    private readonly HashSet<int> tabletVks = [];

    private readonly HashSet<int> pcVks = [];

    private readonly HashSet<int> swallowUp = [];

    private readonly HashSet<int> heldCtrl = [];

    private readonly HashSet<int> heldAlt = [];

    private uint? clipboardSeq;
    private bool hotkeyHeld;

    internal MultiControl(InputHook hook)
    {
        this.hook = hook;
    }

    private bool Ready => enabled && ctrl != null && ctrl.Alive;

    internal void Configure(JsonElement root)
    {
        lock (this)
        {
            enabled = Json.Bool(root, "enabled", enabled);
            side = Json.String(root, "side")is string s && new[]
            {
                "right",
                "left",
                "top",
                "bottom"
            }.Contains(s) ? s : side;
            monitor = Json.Int(root, "monitor", monitor);
            speed = Math.Max(0.01, Json.Double(root, "speed", speed));
            hangul = Json.String(root, "hangul") ?? hangul;
            clipboard = Json.Bool(root, "clipboard", clipboard);
            if (!enabled && active)
                Leave(null, null);
        }

        RefreshMonitors();
    }

    internal void RefreshMonitors()
    {
        var list = Monitors.Get();
        int target;
        lock (this)
        {
            monitors = list;
            target = Monitors.Target(list, monitor, side);
        }

        Monitors.Emit(list, target);
    }

    private Monitor? Target()
    {
        int i = Monitors.Target(monitors, monitor, side);
        return i < 0 ? null : monitors[i];
    }

    internal void SetControl(ScrcpyControl? value)
    {
        lock (this)
        {
            if (value == null && active)
                Leave(null, null);
            ctrl = value;
        }
    }

    internal void UpdateInfo(TabletInfo value)
    {
        lock (this)
        {
            if (active && (info.Width != value.Width || info.Height != value.Height))
            {
                double fx = tx / Math.Max(info.Width - 1, 1), fy = ty / Math.Max(info.Height - 1, 1);
                info = value;
                Position(fx * (value.Width - 1), fy * (value.Height - 1));
            }
            else
                info = value;
        }

        Json.Info(value);
    }

    private bool Covered(int x, int y) => monitors.Any(m => m.Left <= x && x < m.Right && m.Top <= y && y < m.Bottom);

    private bool AtEdge(int x, int y)
    {
        mon = Target();
        if (mon == null)
            return false;
        var m = mon;
        return side switch
        {
            "right" => x >= m.Right - 1 && m.Top <= y && y < m.Bottom && !Covered(m.Right, y),
            "left" => x <= m.Left && m.Top <= y && y < m.Bottom && !Covered(m.Left - 1, y),
            "top" => y <= m.Top && m.Left <= x && x < m.Right && !Covered(x, m.Top - 1),
            _ => y >= m.Bottom - 1 && m.Left <= x && x < m.Right && !Covered(x, m.Bottom)
        };
    }

    internal bool Mouse(uint msg, int x, int y, uint data, bool injected)
    {
        lock (this)
        {
            if (active && !Ready)
                Leave(null, null);
            int bit = msg switch
            {
                0x201 or 0x202 => 1,
                0x204 or 0x205 => 2,
                0x207 or 0x208 => 4,
                0x20b or 0x20c => (data >> 16) == 1 ? 8 : 16,
                _ => 0
           
       };
            bool down = msg is 0x201 or 0x204 or 0x207 or 0x20b;
            if (!active)
            {
                if (!injected && bit != 0)
                    pcButtons = down ? pcButtons | bit : pcButtons & ~bit;
                if (msg == 0x200 && !injected && Ready && pcButtons == 0)
                {
                    if (AtEdge(x, y))
                    {
                        if (++edgeHits >= 2)
                        {
                            edgeHits = 0;
                            Enter(x, y, false);
                            return true;
                        }
                    }
                    else
                        edgeHits = 0;
                }

                return false;
            }

            if (msg == 0x200 && !injected)
            {
                int dx = x - parkX, dy = y - parkY;
                if (dx != 0 || dy != 0)
                    Move(dx, dy);
            }
            else if (bit != 0)
            {
                buttons = down ? buttons | bit : buttons & ~bit;
                ctrl?.Mouse(buttons: buttons, barrier: true);
            }
            else if (msg is 0x20a or 0x20e)
            {
                int delta = (short)(data >> 16);
                if (msg == 0x20a)
                {
                    wheel += delta;
                    int n = wheel / 120;
                    wheel -= n * 120;
                    if (n != 0)
                        ctrl?.Mouse(buttons: buttons, wheel: n);
                }
                else
                {
                    hwheel += delta;
                    int n = hwheel / 120;
                    hwheel -= n * 120;
                    if (n != 0)
                        ctrl?.Mouse(buttons: buttons, hwheel: n);
                }
            }

            return true;
        }
    }

    private void Position(double x, double y)
    {
        ctrl?.Mouse(-32767, -32767, buttons, barrier: true);
        ctrl?.Mouse(-32767, -32767, buttons, barrier: true);
        int ix = (int)Math.Round(x / info.GainX), iy = (int)Math.Round(y / info.GainY);
        ctrl?.Mouse(ix, iy, buttons, barrier: true);
        tx = Math.Clamp(ix * info.GainX, 0, info.Width - 1);
        ty = Math.Clamp(iy * info.GainY, 0, info.Height - 1);
        rx = ry = 0;
    }

    private void Enter(int x, int y, bool center)
    {
        var m = mon ?? Target();
        if (m == null || ctrl == null)
            return;
        mon = m;
        double fx = Math.Clamp((double)(x - m.Left) / m.Width, 0, 1), fy = Math.Clamp((double)(y - m.Top) / m.Height, 0, 1);
        double px = x, py = y, targetX, targetY;
        if (center)
        {
            targetX = info.Width / 2.0;
            targetY = info.Height / 2.0;
        }
        else if (side == "right")
        {
            targetX = 0;
            targetY = fy * (info.Height - 1);
            px = m.Right - 1;
        }
        else if (side == "left")
        {
            targetX = info.Width - 1;
            targetY = fy * (info.Height - 1);
            px = m.Left;
        }
        else if (side == "top")
        {
            targetX = fx * (info.Width - 1);
            targetY = info.Height - 1;
            py = m.Top;
        }
        else
        {
            targetX = fx * (info.Width - 1);
            targetY = 0;
            py = m.Bottom - 1;
        }

        buttons = wheel = hwheel = 0;
        Position(targetX, targetY);
        parkX = (m.Left + m.Right) / 2;
        parkY = (m.Top + m.Bottom) / 2;
        exitX = (int)px;
        exitY = (int)py;
        active = true;
        hook.ShowBlocker(parkX, parkY);
        Native.SetCursorPos(parkX, parkY);
        Json.Active(true);
        if (clipboard)
        {
            var c = ctrl;
            ThreadPool.QueueUserWorkItem(_ =>
            {
                uint seq = Clipboard.GetClipboardSequenceNumber();
                lock (this)
                {
                    if (!clipboard || clipboardSeq == seq || ctrl != c)
                        return;
                    clipboardSeq = seq;
                }

                string? text = Clipboard.Get();
                if (!string.IsNullOrEmpty(text))
                    c.SetClipboard(text);
            });
        }
    }

    private void Move(int dx, int dy)
    {
        double nx = tx + dx * speed, ny = ty + dy * speed;
        if ((side == "right" && nx < 0) || (side == "left" && nx > info.Width - 1) || (side == "top" && ny > info.Height - 1) || (side == "bottom" && ny < 0))
        {
            Leave(nx, ny);
            return;
        }

        double cx = (nx - tx) / info.GainX + rx, cy = (ny - ty) / info.GainY + ry;
        int ix = (int)Math.Round(cx), iy = (int)Math.Round(cy);
        rx = cx - ix;
        ry = cy - iy;
        if (ix != 0 || iy != 0)
            ctrl?.Mouse(ix, iy, buttons);
        tx += ix * info.GainX;
        ty += iy * info.GainY;
        if (tx < 0 || tx > info.Width - 1)
        {
            tx = Math.Clamp(tx, 0, info.Width - 1);
            rx = 0;
        }

        if (ty < 0 || ty > info.Height - 1)
        {
            ty = Math.Clamp(ty, 0, info.Height - 1);
            ry = 0;
        }
    }

    private void Leave(double? x, double? y)
    {
        active = false;
        if (ctrl?.Alive == true)
        {
            ctrl.Keyboard(0, []);
            ctrl.Mouse(barrier: true);
        }

        swallowUp.UnionWith(tabletVks);
        tabletVks.Clear();
        keys.Clear();
        mods = buttons = edgeHits = 0;
        hook.HideBlocker();
        var m = mon ?? Target();
        if (m != null)
        {
            double px = exitX, py = exitY;
            if (x.HasValue && y.HasValue)
            {
                double fx = Math.Clamp(x.Value / Math.Max(info.Width - 1, 1), 0, 1), fy = Math.Clamp(y.Value / Math.Max(info.Height - 1, 1), 0, 1);
                if (side == "right")
                {
                    px = m.Right - 3;
                    py = m.Top + fy * (m.Height - 1);
                }
                else if (side == "left")
                {
                    px = m.Left + 2;
                    py = m.Top + fy * (m.Height - 1);
                }
                else if (side == "top")
                {
                    px = m.Left + fx * (m.Width - 1);
                    py = m.Top + 2;
                }
                else
                {
                    px = m.Left + fx * (m.Width - 1);
                    py = m.Bottom - 3;
                }
            }
            else if (AtEdge(exitX, exitY))
            {
                if (side == "right")
                    px -= 3;
                if (side == "left")
                    px += 2;
                if (side == "top")
                    py += 2;
                if (side == "bottom")
                    py -= 3;
            }

            Native.SetCursorPos((int)px, (int)py);
        }

        Json.Active(false);
    }

    internal void Toggle()
    {
        lock (this)
        {
            if (!Ready)
                return;
            if (active)
                Leave(null, null);
            else
            {
                Native.GetCursorPos(out var p);
                mon = Target();
                Enter(p.X, p.Y, true);
            }
        }
    }

    internal void DeviceClipboard(string text)
    {
        bool use;
        lock (this)
            use = clipboard;
        if (use && text.Length != 0 && Clipboard.Set(text))
            lock (this)
                clipboardSeq = Clipboard.GetClipboardSequenceNumber();
    }

    internal bool Key(int vk, int scan, bool extended, bool down, bool injected)
    {
        if (injected)
            return false;
        lock (this)
        {
            HashSet<int>? held = vk is 0x11 or 0xa2 or 0xa3
                ? heldCtrl
                : vk is 0x12 or 0xa4 or 0xa5
                    ? heldAlt
                    : null;
            if (held != null)
            {
                if (down)
                    held.Add(vk);
                else
                    held.Remove(vk);
            }

            if (vk == 0x4d && heldCtrl.Count != 0 && heldAlt.Count != 0 && Ready)
            {
                if (down)
                {
                    // autorepeat sends more downs; toggle only on the first one
                    if (!hotkeyHeld)
                    {
                        hotkeyHeld = true;
                        Toggle();
                    }

                    swallowUp.Add(vk);
                }
                else
                {
                    hotkeyHeld = false;
                    swallowUp.Remove(vk);
                }

                return true;
            }

            if (vk == 0x4d && !down)
                hotkeyHeld = false; // M released after Ctrl/Alt

            if (!active)
            {
                if (down)
                {
                    pcVks.Add(vk);
                    return false;
                }

                if (swallowUp.Remove(vk))
                    return true;
                pcVks.Remove(vk);
                return false;
            }

            if (!down && pcVks.Contains(vk) && !tabletVks.Contains(vk))
            {
                pcVks.Remove(vk);
                return false;
            }

            if (down && pcVks.Contains(vk))
                return true;
            if (vk == 0x15 && hangul == "shift_space")
            {
                if (down && tabletVks.Add(vk))
                {
                    ctrl?.Keyboard(mods | 2, keys.Append(0x2c));
                    ctrl?.Keyboard(mods, keys);
                }
                else if (!down)
                    tabletVks.Remove(vk);
                return true;
            }

            int usage = KeyMap.Get(vk, scan, extended);
            if (usage == 0)
                return true;
            if (down)
                tabletVks.Add(vk);
            else
                tabletVks.Remove(vk);
            if (usage is >= 0xe0 and <= 0xe7)
            {
                int bit = 1 << (usage - 0xe0);
                int next = down ? mods | bit : mods & ~bit;
                if (next == mods)
                    return true;
                mods = next;
            }
            else if (down)
            {
                if (keys.Contains(usage))
                    return true;
                keys.Add(usage);
                if (keys.Count > 6)
                    keys.RemoveAt(0);
            }
            else if (!keys.Remove(usage))
                return true;
            ctrl?.Keyboard(mods, keys);
            return true;
        }
    }
}
