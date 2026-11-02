using System.Runtime.InteropServices;

internal record Monitor(int Left, int Top, int Right, int Bottom, bool Primary, string Name)
{
    internal int Width => Right - Left;

    internal int Height => Bottom - Top;
}

/// <summary>Enumerates and selects monitors.</summary>
internal static class Monitors
{
    internal static List<Monitor> Get()
    {
        var result = new List<Monitor>();
        Native.MonitorCallback callback = (h, dc, rect, data) =>
        {
            var i = new Native.MonitorInfo
            {
                Size = (uint)Marshal.SizeOf<Native.MonitorInfo>(),
                Name = ""
           
       };
            if (Native.GetMonitorInfo(h, ref i))
                result.Add(new(i.Monitor.Left, i.Monitor.Top, i.Monitor.Right, i.Monitor.Bottom, (i.Flags & 1) != 0, i.Name));
            return true;
       
   };
        Native.EnumDisplayMonitors(0, 0, callback, 0);
        return result.OrderByDescending(m => m.Primary).ThenBy(m => m.Left).ThenBy(m => m.Top).ToList();
    }

    internal static int Target(List<Monitor> list, int index, string side)
    {
        if (index >= 0 && index < list.Count)
            return index;
        if (list.Count == 0)
            return -1;
        int best = 0;
        for (int i = 1; i < list.Count; i++)
            if (side switch
            {
                "left" => list[i].Left < list[best].Left,
                "top" => list[i].Top < list[best].Top,
                "bottom" => list[i].Bottom > list[best].Bottom,
                _ => list[i].Right > list[best].Right
            })
                best = i;
        return best;
    }

    internal static void Emit(List<Monitor> list, int target) => Json.Write(w =>
    {
        w.WriteString("ev", "monitors");
        w.WriteStartArray("list");
        foreach (var m in list)
        {
            w.WriteStartObject();
            w.WriteNumber("left", m.Left);
            w.WriteNumber("top", m.Top);
            w.WriteNumber("right", m.Right);
            w.WriteNumber("bottom", m.Bottom);
            w.WriteBoolean("primary", m.Primary);
            w.WriteString("name", m.Name);
            w.WriteEndObject();
        }

        w.WriteEndArray();
        w.WriteNumber("target", target);
    });
}
