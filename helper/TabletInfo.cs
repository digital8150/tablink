using System.Text.RegularExpressions;

internal sealed record TabletInfo(int Width = 2960, int Height = 1848, double GainX = 1.786, double GainY = 1.786, bool Linear = true)
{
    internal static TabletInfo Query(JobObject job, string adb, string serial)
    {
        string output = job.Run(adb, 10000, "-s", serial, "shell", "dumpsys", "input");
        int width = 2960, height = 1848;
        double gx = 1.786, gy = 1.786;
        bool linear = true;
        var frame = Regex.Match(output, @"displayId=0,.*?logicalFrame=\[(-?\d+), (-?\d+), (\d+), (\d+)\]");
        if (frame.Success)
        {
            width = int.Parse(frame.Groups[3].Value) - int.Parse(frame.Groups[1].Value);
            height = int.Parse(frame.Groups[4].Value) - int.Parse(frame.Groups[2].Value);
        }

        int start = output.IndexOf(": Multi Control Mouse\n", Math.Max(0, output.IndexOf("Input Reader State", StringComparison.Ordinal)), StringComparison.Ordinal);
        if (start >= 0)
        {
            string section = output.Substring(start, Math.Min(4000, output.Length - start));
            var sx = Regex.Match(section, @"XScale: ([\d.]+)");
            var sy = Regex.Match(section, @"YScale: ([\d.]+)");
            var curve = Regex.Match(section, @"Acceleration Curve[^\n]*\n((?:\s+\{[^\n]*\n)+)");
            var segments = Regex.Matches(curve.Groups[1].Value, @"\{([^,]+), ([\d.]+), ([-\d.]+)\}");
            double gain = segments.Count > 0
                ? double.Parse(segments[0].Groups[2].Value, System.Globalization.CultureInfo.InvariantCulture)
                : 1;
            if (segments.Count > 0)
                linear = segments.Count == 1;
            if (sx.Success && sy.Success)
            {
                gx = double.Parse(sx.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture) * gain;
                gy = double.Parse(sy.Groups[1].Value, System.Globalization.CultureInfo.InvariantCulture) * gain;
            }
        }

        return new(width, height, gx, gy, linear);
    }
}

/// <summary>Polls tablet input information.</summary>
internal sealed class InfoPoller : IDisposable
{
    private readonly CancellationTokenSource stop = new();

    private readonly Thread thread;

    internal InfoPoller(JobObject job, string adb, string serial, Action<TabletInfo> changed)
    {
        thread = new Thread(() =>
        {
            TabletInfo? previous = null;
            while (!stop.IsCancellationRequested)
            {
                try
                {
                    var info = TabletInfo.Query(job, adb, serial);
                    if (info != previous && !stop.IsCancellationRequested)
                    {
                        previous = info;
                        changed(info);
                    }
                }
                catch (Exception)
                {
                }

                if (stop.Token.WaitHandle.WaitOne(3000))
                    break;
            }
        })
        {
            IsBackground = true,
            Name = "Tablet info"
       
   };
        thread.Start();
    }

    public void Dispose()
    {
        stop.Cancel();
        thread.Join();
        stop.Dispose();
    }
}
