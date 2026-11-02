using System.Text.Json;

/// <summary>Writes JSON events and reads command values.</summary>
internal static class Json
{
    private static readonly System.Collections.Concurrent.BlockingCollection<byte[]> Queue = new();

    private static readonly Thread Writer = StartWriter();

    // Events are serialized on the caller (keeps order) and written by one background thread,
    // so the hook thread never blocks on the stdout pipe.
    private static Thread StartWriter()
    {
        var t = new Thread(() =>
        {
            using var output = Console.OpenStandardOutput();
            foreach (var line in Queue.GetConsumingEnumerable())
            {
                try
                {
                    output.Write(line);
                    output.Flush();
                }
                catch (IOException)
                {
                }
            }
        })
        {
            IsBackground = true,
            Name = "Event writer"
       
   };
        t.Start();
        return t;
    }

    internal static void Write(Action<Utf8JsonWriter> action)
    {
        var buffer = new MemoryStream();
        using (var writer = new Utf8JsonWriter(buffer))
        {
            writer.WriteStartObject();
            action(writer);
            writer.WriteEndObject();
        }

        buffer.WriteByte(10);
        try
        {
            Queue.Add(buffer.ToArray());
        }
        catch (InvalidOperationException)
        {
        }
    }

    internal static void Flush()
    {
        Queue.CompleteAdding();
        Writer.Join(2000);
    }

    internal static void Ready() => Write(w => w.WriteString("ev", "ready"));

    internal static void Log(string msg) => Write(w =>
    {
        w.WriteString("ev", "log");
        w.WriteString("msg", msg);
    });

    internal static void Active(bool value) => Write(w =>
    {
        w.WriteString("ev", "active");
        w.WriteBoolean("value", value);
    });

    internal static void Ctrl(string state, string? serial = null, string? message = null) => Write(w =>
    {
        w.WriteString("ev", "ctrl");
        w.WriteString("state", state);
        if (serial != null)
            w.WriteString("serial", serial);
        if (message != null)
            w.WriteString("message", message);
    });

    internal static void Audio(string state, int? code = null, string? message = null) => Write(w =>
    {
        w.WriteString("ev", "audio");
        w.WriteString("state", state);
        if (code.HasValue)
            w.WriteNumber("code", code.Value);
        if (message != null)
            w.WriteString("message", message);
    });

    internal static void Info(TabletInfo i) => Write(w =>
    {
        w.WriteString("ev", "info");
        w.WriteNumber("width", i.Width);
        w.WriteNumber("height", i.Height);
        w.WriteNumber("gainX", i.GainX);
        w.WriteNumber("gainY", i.GainY);
        w.WriteBoolean("linear", i.Linear);
    });

    internal static string? String(JsonElement e, string key) =>
        e.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString()
            : null;

    internal static bool Bool(JsonElement e, string key, bool fallback) =>
        e.TryGetProperty(key, out var v) && (v.ValueKind == JsonValueKind.True || v.ValueKind == JsonValueKind.False)
            ? v.GetBoolean()
            : fallback;

    internal static int Int(JsonElement e, string key, int fallback) =>
        e.TryGetProperty(key, out var v) && v.TryGetInt32(out int n)
            ? n
            : fallback;

    internal static double Double(JsonElement e, string key, double fallback) =>
        e.TryGetProperty(key, out var v) && v.TryGetDouble(out double n)
            ? n
            : fallback;
}
