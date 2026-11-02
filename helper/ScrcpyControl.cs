using System.Buffers.Binary;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net.Sockets;
using System.Text;

/// <summary>Manages the scrcpy control connection.</summary>
internal sealed class ScrcpyControl
{
    private const string ServerPath = "/data/local/tmp/scrcpy-server-tablink.jar";

    private readonly JobObject job;

    private readonly string adb;

    private readonly string serial;

    private readonly string server;

    private readonly string version;

    private readonly Action<string> clipboard;

    private readonly Action dead;

    private readonly BlockingCollection<Packet> queue = new();

    private TcpClient? socket;

    private Process? process;

    private int port;

    private long sequence = 1;

    private volatile bool alive;

    private volatile bool stopping;

    private int deadReported;

    private Thread? sender;

    private sealed record Packet(byte[] Data, bool Mouse = false, int Buttons = 0, int X = 0, int Y = 0, bool Merge = false);

    internal bool Alive => alive;

    internal ScrcpyControl(JobObject job, string adb, string serial, string server, string version, Action<string> clipboard, Action dead)
    {
        this.job = job;
        this.adb = adb;
        this.serial = serial;
        this.server = server;
        this.version = version;
        this.clipboard = clipboard;
        this.dead = dead;
    }

    private string Adb(int timeout, params string[] args) => job.Run(adb, timeout, ["-s", serial, ..args]);

    internal void Start()
    {
        Adb(30000, "push", server, ServerPath);
        int scid = Random.Shared.Next();
        string id = scid.ToString("x8");
        port = int.Parse(Adb(15000, "forward", "tcp:0", "localabstract:scrcpy_" + id).Trim());
        process = job.Start(adb, "-s", serial, "shell", "CLASSPATH=" + ServerPath, "app_process", "/", "com.genymobile.scrcpy.Server", version, "scid=" + id, "log_level=warn", "video=false", "audio=false", "control=true", "tunnel_forward=true", "clipboard_autosync=true", "power_on=false", "cleanup=false");
        _ = process.StandardOutput.ReadToEndAsync();
        _ = process.StandardError.ReadToEndAsync();
        var deadline = DateTime.UtcNow.AddSeconds(10);
        while (true)
        {
            TcpClient? candidate = null;
            try
            {
                candidate = new TcpClient();
                candidate.ConnectAsync("127.0.0.1", port).WaitAsync(TimeSpan.FromSeconds(2)).GetAwaiter().GetResult();
                candidate.ReceiveTimeout = 2000;
                if (candidate.GetStream().ReadByte() == 0)
                {
                    socket = candidate;
                    break;
                }
            }
            catch (Exception)
            {
            }

            candidate?.Dispose();
            if (DateTime.UtcNow > deadline || process.HasExited)
                throw new InvalidOperationException("scrcpy server failed to start");
            Thread.Sleep(200);
        }

        socket.ReceiveTimeout = 0;
        socket.NoDelay = true;
        ReadExact(socket.GetStream(), 64);
        alive = true;
        sender = new Thread(SendLoop)
        {
            IsBackground = true,
            Name = "Control sender"
       
   };
        sender.Start();
        new Thread(ReadLoop)
        {
            IsBackground = true,
            Name = "Control reader"
        }.Start();
        Create(2, "Multi Control Mouse", Descriptors.Mouse);
        Create(1, "Multi Control Keyboard", Descriptors.Keyboard);
    }

    private static byte[] ReadExact(Stream stream, int count)
    {
        var b = new byte[count];
        stream.ReadExactly(b);
        return b;
    }

    private void ReadLoop()
    {
        try
        {
            var s = socket!.GetStream();
            while (true)
            {
                int type = s.ReadByte();
                if (type < 0)
                    break;
                if (type == 0)
                {
                    int n = checked((int)BinaryPrimitives.ReadUInt32BigEndian(ReadExact(s, 4)));
                    if (n > 16 * 1024 * 1024)
                        throw new InvalidDataException();
                    clipboard(Encoding.UTF8.GetString(ReadExact(s, n)));
                }
                else if (type == 1)
                    ReadExact(s, 8);
                else if (type == 2)
                {
                    var h = ReadExact(s, 4);
                    ReadExact(s, BinaryPrimitives.ReadUInt16BigEndian(h.AsSpan(2)));
                }
                else
                    break;
            }
        }
        catch (Exception)
        {
        }

        alive = false;
        if (!stopping && Interlocked.Exchange(ref deadReported, 1) == 0)
            dead();
    }

    private void SendLoop()
    {
        try
        {
            Packet? pending = null;
            while (pending != null || queue.TryTake(out pending, Timeout.Infinite))
            {
                Packet current = pending!;
                pending = null;
                if (current.Mouse && current.Merge)
                {
                    int x = current.X, y = current.Y;
                    while (queue.TryTake(out var next))
                    {
                        if (!next.Mouse || !next.Merge || next.Buttons != current.Buttons)
                        {
                            pending = next;
                            break;
                        }

                        x = Math.Clamp(x + next.X, -32767, 32767);
                        y = Math.Clamp(y + next.Y, -32767, 32767);
                    }

                    current = MakeMouse(x, y, current.Buttons, 0, 0, true);
                }

                socket!.GetStream().Write(current.Data);
            }
        }
        catch (Exception)
        {
            alive = false;
            if (!stopping && Interlocked.Exchange(ref deadReported, 1) == 0)
                dead();
        }
    }

    private void Enqueue(byte[] data)
    {
        if (!queue.IsAddingCompleted)
            queue.TryAdd(new(data));
    }

    private static byte[] Header(int type, int id, int size)
    {
        var b = new byte[5 + size];
        b[0] = (byte)type;
        BinaryPrimitives.WriteUInt16BigEndian(b.AsSpan(1), (ushort)id);
        BinaryPrimitives.WriteUInt16BigEndian(b.AsSpan(3), (ushort)size);
        return b;
    }

    private void Create(int id, string name, byte[] desc)
    {
        byte[] n = Encoding.UTF8.GetBytes(name);
        var b = new byte[10 + n.Length + desc.Length];
        b[0] = 12;
        BinaryPrimitives.WriteUInt16BigEndian(b.AsSpan(1), (ushort)id);
        b[7] = (byte)n.Length;
        n.CopyTo(b, 8);
        BinaryPrimitives.WriteUInt16BigEndian(b.AsSpan(8 + n.Length), (ushort)desc.Length);
        desc.CopyTo(b, 10 + n.Length);
        Enqueue(b);
    }

    private static Packet MakeMouse(int x, int y, int buttons, int wheel, int hwheel, bool merge)
    {
        x = Math.Clamp(x, -32767, 32767);
        y = Math.Clamp(y, -32767, 32767);
        var b = Header(13, 2, 7);
        b[5] = (byte)(buttons & 31);
        BinaryPrimitives.WriteInt16LittleEndian(b.AsSpan(6), (short)x);
        BinaryPrimitives.WriteInt16LittleEndian(b.AsSpan(8), (short)y);
        b[10] = unchecked((byte)(sbyte)Math.Clamp(wheel, -127, 127));
        b[11] = unchecked((byte)(sbyte)Math.Clamp(hwheel, -127, 127));
        return new(b, true, buttons, x, y, merge);
    }

    private int lastButtons;

    internal void Mouse(int x = 0, int y = 0, int buttons = 0, int wheel = 0, int hwheel = 0, bool barrier = false)
    {
        bool merge = !barrier && buttons == lastButtons && wheel == 0 && hwheel == 0;
        lastButtons = buttons;
        if (!queue.IsAddingCompleted)
            queue.TryAdd(MakeMouse(x, y, buttons, wheel, hwheel, merge));
    }

    internal void Keyboard(int modifiers, IEnumerable<int> keys)
    {
        var b = Header(13, 1, 8);
        b[5] = (byte)modifiers;
        int i = 7;
        foreach (int key in keys.Take(6))
            b[i++] = (byte)key;
        Enqueue(b);
    }

    internal void SetClipboard(string text)
    {
        byte[] raw = Encoding.UTF8.GetBytes(text);
        int n = Math.Min(raw.Length, (1 << 18) - 14);
        byte[] b = new byte[14 + n];
        b[0] = 9;
        BinaryPrimitives.WriteInt64BigEndian(b.AsSpan(1), Interlocked.Increment(ref sequence));
        BinaryPrimitives.WriteInt32BigEndian(b.AsSpan(10), n);
        Array.Copy(raw, 0, b, 14, n);
        Enqueue(b);
    }

    internal void Stop()
    {
        stopping = true;
        alive = false;
        if (socket != null)
        {
            Keyboard(0, []);
            Mouse(barrier: true);
            Enqueue([14, 0, 2]);
            Enqueue([14, 0, 1]);
            queue.CompleteAdding();
            if (sender != null && !sender.Join(1000))
                socket.Close();
            socket.Close();
            socket = null;
        }

        if (process != null)
        {
            try
            {
                if (!process.HasExited)
                    process.Kill();
            }
            catch (InvalidOperationException)
            {
            }

            process.Dispose();
            process = null;
        }

        if (port != 0)
        {
            try
            {
                Adb(15000, "forward", "--remove", "tcp:" + port);
            }
            catch (Exception)
            {
            }

            port = 0;
        }
    }
}
