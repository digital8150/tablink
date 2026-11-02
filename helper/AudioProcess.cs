using System.Diagnostics;

/// <summary>Manages the scrcpy audio process.</summary>
internal sealed class AudioProcess
{
    private readonly JobObject job;

    private readonly object gate = new();

    private Process? process;

    internal AudioProcess(JobObject job)
    {
        this.job = job;
    }

    internal void Stop()
    {
        Process? old;
        lock (gate)
        {
            old = process;
            process = null;
        }

        if (old != null)
        {
            try
            {
                if (!old.HasExited)
                    old.Kill();
            }
            catch (InvalidOperationException)
            {
            }
        }

        Json.Audio("off");
    }

    internal void Start(string? serial, string? exe, string source, bool dup, int buffer)
    {
        Stop();
        if (string.IsNullOrEmpty(serial))
            return;
        try
        {
            var args = new List<string>
            {
                "-s",
                serial,
                "--no-video",
                "--no-control",
                "--no-window",
                "--no-power-on",
                $"--audio-buffer={buffer}",
                $"--audio-source={source}"};
            if (source == "playback" && dup)
                args.Add("--audio-dup");
            var p = job.Start(exe ?? throw new ArgumentException("Missing scrcpy path"), args.ToArray());
            lock (gate)
                process = p;
            Json.Audio("running");
            void Pump(StreamReader reader)
            {
                string? line;
                while ((line = reader.ReadLine()) != null)
                    if (line.Contains("ERROR", StringComparison.Ordinal) || line.Contains("WARN", StringComparison.Ordinal))
                        Json.Log("scrcpy: " + line.Trim());
            }

            _ = Task.Run(() => Pump(p.StandardOutput));
            _ = Task.Run(() => Pump(p.StandardError));
            _ = Task.Run(() =>
            {
                p.WaitForExit();
                lock (gate)
                {
                    if (process == p)
                    {
                        process = null;
                        Json.Audio("stopped", p.ExitCode);
                    }
                }

                p.Dispose();
            });
        }
        catch (Exception e)
        {
            Json.Audio("error", message: e.Message);
        }
    }
}
