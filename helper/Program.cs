using System.Collections.Concurrent;
using System.Text.Json;

/// <summary>Runs the helper command loop.</summary>
internal static class Program
{
    private static void Main()
    {
        Native.SetProcessDpiAwarenessContext(new nint(-4));
        using var job = new JobObject();
        MultiControl? mc = null;
        var hook = new InputHook(() => ThreadPool.QueueUserWorkItem(_ => mc?.RefreshMonitors()));
        mc = new MultiControl(hook);
        hook.Control = mc;
        var audio = new AudioProcess(job);
        using var commands = new BlockingCollection<Action>();
        ScrcpyControl? control = null;
        InfoPoller? poller = null;
        string? serial = null;
        void Detach(bool emit)
        {
            mc.SetControl(null);
            poller?.Dispose();
            poller = null;
            control?.Stop();
            control = null;
            if (emit)
                Json.Ctrl("off", serial);
            serial = null;
        }

        var worker = new Thread(() =>
        {
            foreach (var action in commands.GetConsumingEnumerable())
            {
                try
                {
                    action();
                }
                catch (Exception e)
                {
                    Json.Log(e.Message);
                }
            }
        })
        {
            IsBackground = true,
            Name = "Control worker"
       
   };
        worker.Start();
        hook.Start();
        Json.Ready();
        mc.RefreshMonitors();
        string? line;
        while ((line = Console.ReadLine()) != null)
        {
            try
            {
                using var doc = JsonDocument.Parse(line);
                var root = doc.RootElement;
                string? cmd = Json.String(root, "cmd");
                if (cmd == "quit")
                    break;
                switch (cmd)
                {
                    case "config":
                        mc.Configure(root);
                        break;
                    case "monitors":
                        mc.RefreshMonitors();
                        break;
                    case "toggle":
                        mc.Toggle();
                        break;
                    case "detach":
                        commands.Add(() => Detach(true));
                        break;
                    case "attach":
                        string newSerial = Json.String(root, "serial") ?? "", adb = Json.String(root, "adb") ?? "", server = Json.String(root, "server") ?? "", version = Json.String(root, "version") ?? "";
                        commands.Add(() =>
                        {
                            Detach(false);
                            serial = newSerial;
                            Json.Ctrl("starting", serial);
                            ScrcpyControl? next = null;
                            try
                            {
                                next = new ScrcpyControl(job, adb, newSerial, server, version, mc.DeviceClipboard, () =>
                                {
                                    try
                                    {
                                        commands.Add(() =>
                                        {
                                            if (ReferenceEquals(control, next))
                                            {
                                                mc.SetControl(null);
                                                Json.Ctrl("dead", newSerial);
                                            }
                                        });
                                    }
                                    catch (InvalidOperationException)
                                    {
                                    }
                                });
                                control = next;
                                next.Start();
                                if (!next.Alive)
                                    throw new IOException("Control connection closed");
                                mc.SetControl(next);
                                Json.Ctrl("alive", serial);
                                Thread.Sleep(300);
                                poller = new InfoPoller(job, adb, newSerial, mc.UpdateInfo);
                            }
                            catch (Exception e)
                            {
                                mc.SetControl(null);
                                next?.Stop();
                                control = null;
                                Json.Ctrl("error", newSerial, e.Message);
                            }
                        });
                        break;
                    case "audio":
                        audio.Start(Json.String(root, "serial"), Json.String(root, "scrcpy"), Json.String(root, "source") ?? "playback", Json.Bool(root, "dup", false), Json.Int(root, "buffer", 50));
                        break;
                }
            }
            catch (Exception e)
            {
                Json.Log(e.Message);
            }
        }

        commands.Add(() => Detach(true));
        commands.CompleteAdding();
        worker.Join();
        audio.Stop();
        hook.Stop();
        Json.Flush();
    }
}
