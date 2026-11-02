using System.Diagnostics;
using System.Runtime.InteropServices;

/// <summary>Manages processes in a Windows job object.</summary>
internal sealed class JobObject : IDisposable
{
    [StructLayout(LayoutKind.Sequential)]
    private struct Basic
    {
        public long A;

        public long B;

        public uint Flags;

        public nuint Min;

        public nuint Max;

        public uint Active;

        public nuint Affinity;

        public uint Priority;

        public uint Schedule;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct Limits
    {
        public Basic Basic;

        public ulong I1;

        public ulong I2;

        public ulong I3;

        public ulong I4;

        public ulong I5;

        public ulong I6;

        public nuint P1;

        public nuint P2;

        public nuint P3;

        public nuint P4;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
    private static extern nint CreateJobObjectW(nint attributes, string? name);

    [DllImport("kernel32.dll")]
    private static extern bool SetInformationJobObject(nint job, int kind, ref Limits limits, uint size);

    [DllImport("kernel32.dll")]
    private static extern bool AssignProcessToJobObject(nint job, nint process);

    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(nint handle);

    private readonly nint handle;

    internal JobObject()
    {
        handle = CreateJobObjectW(0, null);
        var l = new Limits();
        l.Basic.Flags = 0x2000;
        if (handle == 0 || !SetInformationJobObject(handle, 9, ref l, (uint)Marshal.SizeOf<Limits>()))
            throw new System.ComponentModel.Win32Exception();
    }

    internal Process Start(string exe, params string[] args)
    {
        var p = new Process
        {
            StartInfo = new ProcessStartInfo(exe)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                RedirectStandardInput = true
            }
       
   };
        foreach (string arg in args)
            p.StartInfo.ArgumentList.Add(arg);
        p.Start();
        if (!AssignProcessToJobObject(handle, p.Handle))
        {
            p.Kill();
            p.Dispose();
            throw new System.ComponentModel.Win32Exception();
        }

        p.StandardInput.Close();
        return p;
    }

    internal string Run(string exe, int timeout, params string[] args)
    {
        using var p = Start(exe, args);
        var output = p.StandardOutput.ReadToEndAsync();
        var error = p.StandardError.ReadToEndAsync();
        if (!p.WaitForExit(timeout))
        {
            p.Kill();
            throw new TimeoutException(exe);
        }

        string result = output.GetAwaiter().GetResult();
        string err = error.GetAwaiter().GetResult();
        if (p.ExitCode != 0)
            throw new InvalidOperationException(string.IsNullOrWhiteSpace(err) ? result : err);
        return result;
    }

    public void Dispose()
    {
        if (handle != 0)
            CloseHandle(handle);
    }
}
