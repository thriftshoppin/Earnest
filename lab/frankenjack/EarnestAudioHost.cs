// Earnest's headless Windows audio router.  It owns the virtual-loopback to
// physical-output path; the Python CLI only supplies room profiles and lifecycle.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Threading;
using NAudio.CoreAudioApi;
using NAudio.Wave;
using NAudio.Dsp;

internal enum ERole { Console = 0, Multimedia = 1, Communications = 2 }

[ComImport, Guid("F8679F50-850A-41CF-9C72-430F290290C8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IPolicyConfig
{
    int GetMixFormat(string deviceId, IntPtr format);
    int GetDeviceFormat(string deviceId, int defaultFormat, IntPtr format);
    int ResetDeviceFormat(string deviceId);
    int SetDeviceFormat(string deviceId, IntPtr endpointFormat, IntPtr mixFormat);
    int GetProcessingPeriod(string deviceId, int defaultPeriod, IntPtr defaultPeriodPtr, IntPtr minimumPeriodPtr);
    int SetProcessingPeriod(string deviceId, IntPtr period);
    int GetShareMode(string deviceId, IntPtr mode);
    int SetShareMode(string deviceId, IntPtr mode);
    int GetPropertyValue(string deviceId, int storage, IntPtr value);
    int SetPropertyValue(string deviceId, int storage, IntPtr value);
    int SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string deviceId, ERole role);
    int SetEndpointVisibility(string deviceId, int visible);
}

[ComImport, Guid("870AF99C-171D-4F9E-AF0D-E63DF40C2BC9")]
internal class PolicyConfigClient { }

internal sealed class RouteProfile
{
    internal float Dry = 0.78f;
    internal float Wet = 0.55f;
    internal float Rt60 = 1.2f;

    internal static RouteProfile Load(string path)
    {
        var profile = new RouteProfile();
        if (String.IsNullOrWhiteSpace(path) || !File.Exists(path)) return profile;
        var text = File.ReadAllText(path);
        var dry = Regex.Match(text, "\\\"dry_mix\\\"\\s*:\\s*([0-9.]+)");
        var wet = Regex.Match(text, "\\\"wet_mix\\\"\\s*:\\s*([0-9.]+)");
        if (dry.Success) profile.Dry = Clamp(Parse(dry.Groups[1].Value, profile.Dry), 0f, 1f);
        if (wet.Success) profile.Wet = Clamp(Parse(wet.Groups[1].Value, profile.Wet), 0f, 1f);
        var match = Regex.Match(text, "\\\"rt60_s\\\"\\s*:\\s*\\[([^]]+)\\]");
        if (match.Success)
        {
            var values = Regex.Matches(match.Groups[1].Value, "[0-9]+(?:\\.[0-9]+)?")
                .Cast<Match>().Select(m => Parse(m.Value, 0f)).Where(v => v > 0.02f && v < 30f).ToArray();
            if (values.Length > 0)
            {
                Array.Sort(values);
                profile.Rt60 = values[values.Length / 2];
            }
        }
        return profile;
    }

    private static float Parse(string value, float fallback)
    {
        float result;
        return Single.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out result) ? result : fallback;
    }

    private static float Clamp(float value, float low, float high) { return Math.Max(low, Math.Min(high, value)); }
}

// A compact eight-line feedback-delay network.  It maps the solved profile's
// median RT60 into feedback gain while the profile retains the full octave-band
// RT60 series for a later multiband-convolution stage.
internal sealed class RoomFdn
{
    private static readonly int[] BaseLengths = { 1423, 1543, 1741, 1867, 2017, 2237, 2411, 2591 };
    private readonly float[][] _lines;
    private readonly int[] _index;
    private readonly float _gain, _dry, _wet;

    internal RoomFdn(int sampleRate, RouteProfile profile)
    {
        _lines = new float[BaseLengths.Length][];
        _index = new int[BaseLengths.Length];
        var scale = Math.Max(0.5, Math.Min(2.0, sampleRate / 48000.0));
        double averageDelay = BaseLengths.Average() * scale / sampleRate;
        _gain = (float)Math.Min(0.985, Math.Pow(0.001, averageDelay / Math.Max(profile.Rt60, 0.05f)));
        _dry = profile.Dry;
        _wet = profile.Wet;
        for (int i = 0; i < _lines.Length; i++)
            _lines[i] = new float[Math.Max(64, (int)Math.Round(BaseLengths[i] * scale))];
    }

    internal void Process(float left, float right, out float outputLeft, out float outputRight)
    {
        float v0 = _lines[0][_index[0]], v1 = _lines[1][_index[1]];
        float v2 = _lines[2][_index[2]], v3 = _lines[3][_index[3]];
        float v4 = _lines[4][_index[4]], v5 = _lines[5][_index[5]];
        float v6 = _lines[6][_index[6]], v7 = _lines[7][_index[7]];
        float input = (left + right) * 0.5f;
        // Normalized Hadamard feedback matrix keeps the late field diffuse.
        float a = 0.35355339f;
        float h0 = (v0+v1+v2+v3+v4+v5+v6+v7)*a, h1 = (v0-v1+v2-v3+v4-v5+v6-v7)*a;
        float h2 = (v0+v1-v2-v3+v4+v5-v6-v7)*a, h3 = (v0-v1-v2+v3+v4-v5-v6+v7)*a;
        float h4 = (v0+v1+v2+v3-v4-v5-v6-v7)*a, h5 = (v0-v1+v2-v3-v4+v5-v6+v7)*a;
        float h6 = (v0+v1-v2-v3-v4-v5+v6+v7)*a, h7 = (v0-v1-v2+v3-v4+v5+v6-v7)*a;
        _lines[0][_index[0]] = input * 0.20f + h0 * _gain; _index[0] = (_index[0] + 1) % _lines[0].Length;
        _lines[1][_index[1]] = input * 0.20f + h1 * _gain; _index[1] = (_index[1] + 1) % _lines[1].Length;
        _lines[2][_index[2]] = input * 0.20f + h2 * _gain; _index[2] = (_index[2] + 1) % _lines[2].Length;
        _lines[3][_index[3]] = input * 0.20f + h3 * _gain; _index[3] = (_index[3] + 1) % _lines[3].Length;
        _lines[4][_index[4]] = input * 0.20f + h4 * _gain; _index[4] = (_index[4] + 1) % _lines[4].Length;
        _lines[5][_index[5]] = input * 0.20f + h5 * _gain; _index[5] = (_index[5] + 1) % _lines[5].Length;
        _lines[6][_index[6]] = input * 0.20f + h6 * _gain; _index[6] = (_index[6] + 1) % _lines[6].Length;
        _lines[7][_index[7]] = input * 0.20f + h7 * _gain; _index[7] = (_index[7] + 1) % _lines[7].Length;
        float wetLeft = (v0 + v2 - v3 + v5 - v6) * 0.18f;
        float wetRight = (v1 - v2 + v4 - v5 + v7) * 0.18f;
        outputLeft = left * _dry + wetLeft * _wet;
        outputRight = right * _dry + wetRight * _wet;
    }
}

internal sealed class RoomWaveProvider : IWaveProvider
{
    private readonly BufferedWaveProvider _source;
    private readonly RoomFdn _room;
    private float[] _floatBuffer = new float[0];
    public WaveFormat WaveFormat { get { return _source.WaveFormat; } }

    internal RoomWaveProvider(BufferedWaveProvider source, RouteProfile profile)
    {
        _source = source;
        _room = new RoomFdn(source.WaveFormat.SampleRate, profile);
    }

    public int Read(byte[] buffer, int offset, int count)
    {
        int read = _source.Read(buffer, offset, count);
        if (read <= 0 || WaveFormat.Channels < 2) return read;
        if (WaveFormat.Encoding == WaveFormatEncoding.IeeeFloat && WaveFormat.BitsPerSample == 32)
        {
            int samples = read / 4;
            Ensure(samples);
            Buffer.BlockCopy(buffer, offset, _floatBuffer, 0, samples * 4);
            for (int i = 0; i + 1 < samples; i += WaveFormat.Channels)
            {
                float l, r;
                _room.Process(_floatBuffer[i], _floatBuffer[i + 1], out l, out r);
                _floatBuffer[i] = l; _floatBuffer[i + 1] = r;
            }
            Buffer.BlockCopy(_floatBuffer, 0, buffer, offset, samples * 4);
        }
        else if (WaveFormat.Encoding == WaveFormatEncoding.Pcm && WaveFormat.BitsPerSample == 16)
        {
            for (int i = offset; i + 3 < offset + read; i += WaveFormat.BlockAlign)
            {
                float left = BitConverter.ToInt16(buffer, i) / 32768f;
                float right = BitConverter.ToInt16(buffer, i + 2) / 32768f;
                float l, r; _room.Process(left, right, out l, out r);
                Write16(buffer, i, l); Write16(buffer, i + 2, r);
            }
        }
        return read;
    }

    private void Ensure(int count) { if (_floatBuffer.Length < count) _floatBuffer = new float[count]; }
    private static void Write16(byte[] buffer, int offset, float value)
    {
        short sample = (short)Math.Max(Int16.MinValue, Math.Min(Int16.MaxValue, Math.Round(value * 32767f)));
        buffer[offset] = (byte)(sample & 0xff); buffer[offset + 1] = (byte)((sample >> 8) & 0xff);
    }
}

// Seven smoothed peaking filters affect the reflected return only.
internal sealed class ReflectionEq
{
    static readonly double[] Frequencies = {125,250,500,1000,2000,4000,8000};
    readonly double[] current = new double[7], b0 = new double[7], b1 = new double[7], b2 = new double[7], a1 = new double[7], a2 = new double[7];
    readonly double[,] z1, z2;
    readonly int rate;
    internal volatile float[] Target = new float[7];
    internal ReflectionEq(int channels, int rate) { this.rate=rate; z1=new double[channels,7]; z2=new double[channels,7]; for(int i=0;i<7;i++) b0[i]=1; }
    internal void Update() {
        var target=Target;
        for(int i=0;i<7;i++) {
            current[i] += 0.15 * (target[i]-current[i]);
            double A=Math.Pow(10,current[i]/40.0), omega=2*Math.PI*Frequencies[i]/rate;
            double alpha=Math.Sin(omega)/(2*1.41421356237), cos=Math.Cos(omega), norm=1+alpha/A;
            b0[i]=(1+alpha*A)/norm; b1[i]=-2*cos/norm; b2[i]=(1-alpha*A)/norm;
            a1[i]=-2*cos/norm; a2[i]=(1-alpha/A)/norm;
        }
    }
    internal float Process(int channel,float value) {
        double x=value;
        for(int i=0;i<7;i++) {
            double y=b0[i]*x+z1[channel,i];
            z1[channel,i]=b1[i]*x-a1[i]*y+z2[channel,i]; z2[channel,i]=b2[i]*x-a2[i]*y;
            x=y;
        }
        return (float)x;
    }
}

// Uniform partitioned overlap-add convolution. One filter per input channel;
// channels remain separate so downstream surround processing can use them.
internal sealed class ConvolutionProvider : IWaveProvider
{
    const int Block = 512, Size = 1024, LogSize = 10;
    readonly BufferedWaveProvider source;
    readonly int channels, partitions;
    readonly Complex[][][] filters, history;
    readonly Complex[] scratch = new Complex[Size], sum = new Complex[Size];
    readonly float[][] input, output, overlap;
    internal readonly ReflectionEq Eq, DirectEq;
    readonly float[] directFrame, mixedFrame;
    byte[] bytes = new byte[0];
    float[] samples = new float[0];
    int position, ring;
    internal volatile float TargetGain = 1f;
    internal float OutputLimit = 1f;
    internal volatile float TargetDry = 0f, TargetCenter = 0f, TargetMaster = 1f, TargetCeiling = 0.1f, TargetWidth = 1f;
    float currentDry = 0f, currentCenter = 0f, currentMaster = 1f, currentCeiling = 0.1f, currentWidth = 1f;
    readonly float[][] directDelay;
    int directPos;
    float currentGain = 1f;
    public WaveFormat WaveFormat { get { return source.WaveFormat; } }

    internal ConvolutionProvider(BufferedWaveProvider source, string path)
    {
        this.source = source;
        using (var reader = new BinaryReader(File.OpenRead(path)))
        {
            if (new string(reader.ReadChars(4)) != "ERIR" || reader.ReadInt32() != 1)
                throw new InvalidDataException("Invalid convolution profile");
            int rate = reader.ReadInt32(); channels = reader.ReadInt32(); int length = reader.ReadInt32();
            if (rate != WaveFormat.SampleRate || channels != WaveFormat.Channels || length < 1 || length > rate * 20)
                throw new InvalidDataException("Room profile does not match endpoint sample rate/channels or is too long");
            Eq = new ReflectionEq(channels, rate);
            DirectEq = new ReflectionEq(channels, rate);
            directFrame = new float[channels];
            mixedFrame = new float[channels];
            // Align the direct signal with the 85 ms lookahead and convolution block.
            int delayFrames = (int)Math.Round(rate * 0.085) + Block;
            directDelay = new float[channels][];
            for (int c = 0; c < channels; c++) directDelay[c] = new float[delayFrames];
            partitions = (length + Block - 1) / Block;
            filters = new Complex[channels][][]; history = new Complex[channels][][];
            input = new float[channels][]; output = new float[channels][]; overlap = new float[channels][];
            for (int c = 0; c < channels; c++)
            {
                filters[c] = new Complex[partitions][]; history[c] = new Complex[partitions][];
                input[c] = new float[Block]; output[c] = new float[Block]; overlap[c] = new float[Block];
                for (int p = 0; p < partitions; p++)
                {
                    var h = new Complex[Size];
                    for (int i = 0; i < Block && p * Block + i < length; i++) h[i].X = reader.ReadSingle();
                    FastFourierTransform.FFT(true, LogSize, h);
                    for (int i = 0; i < Size; i++) { h[i].X *= Size; h[i].Y *= Size; }
                    filters[c][p] = h; history[c][p] = new Complex[Size];
                }
            }
            if (reader.BaseStream.Position != reader.BaseStream.Length) throw new InvalidDataException("Unexpected room profile data");
        }
    }

    void ProcessBlock()
    {
        Eq.Update();
        DirectEq.Update();
        for (int c = 0; c < channels; c++)
        {
            Array.Clear(scratch, 0, Size);
            for (int i = 0; i < Block; i++) scratch[i].X = input[c][i];
            FastFourierTransform.FFT(true, LogSize, scratch);
            Array.Copy(scratch, history[c][ring], Size);
            Array.Clear(sum, 0, Size);
            for (int p = 0; p < partitions; p++)
            {
                var x = history[c][(ring - p + partitions) % partitions]; var h = filters[c][p];
                for (int i = 0; i < Size; i++)
                {
                    sum[i].X += x[i].X * h[i].X - x[i].Y * h[i].Y;
                    sum[i].Y += x[i].X * h[i].Y + x[i].Y * h[i].X;
                }
            }
            FastFourierTransform.FFT(false, LogSize, sum);
            for (int i = 0; i < Block; i++) { output[c][i] = sum[i].X + overlap[c][i]; overlap[c][i] = sum[i + Block].X; }
        }
        ring = (ring + 1) % partitions;
    }

    public int Read(byte[] buffer, int offset, int count)
    {
        if (bytes.Length < count) bytes = new byte[count];
        int read = source.Read(bytes, 0, count), n = read / 4;
        if (samples.Length < n) samples = new float[n];
        Buffer.BlockCopy(bytes, 0, samples, 0, n * 4);
        for (int frame = 0; frame + channels <= n; frame += channels)
        {
            currentGain += 0.002f * (TargetGain - currentGain);
            currentDry += 0.002f * (TargetDry - currentDry);
            currentCenter += 0.002f * (TargetCenter - currentCenter);
            currentMaster += 0.002f * (TargetMaster - currentMaster);
            currentCeiling += 0.002f * (TargetCeiling - currentCeiling);
            currentWidth += 0.002f * (TargetWidth - currentWidth);
            // Center is an additive, equally distributed mid signal; side is preserved.
            for (int c = 0; c < channels; c++) directFrame[c] = DirectEq.Process(c, directDelay[c][directPos]);
            float mid = channels == 2 ? 0.5f * (directFrame[0] + directFrame[1]) : 0f;
            for (int c = 0; c < channels; c++)
            {
                float incoming = samples[frame + c];
                input[c][position] = incoming;
                float direct = directFrame[c];
                directDelay[c][directPos] = incoming;
                mixedFrame[c] = (Eq.Process(c, output[c][position]) * currentGain + direct * currentDry + mid * currentCenter) * currentMaster;
            }
            // Only stereo has a defined mid/side mapping; preserve other channel layouts.
            if (channels == 2) {
                float stageMid = .5f * (mixedFrame[0] + mixedFrame[1]);
                float stageSide = .5f * (mixedFrame[0] - mixedFrame[1]) * currentWidth;
                mixedFrame[0] = stageMid + stageSide; mixedFrame[1] = stageMid - stageSide;
            }
            float limit = Math.Min(OutputLimit, currentCeiling);
            for (int c = 0; c < channels; c++) samples[frame+c] = Math.Max(-limit, Math.Min(limit, mixedFrame[c]));
            if (++directPos == directDelay[0].Length) directPos = 0;
            if (++position == Block) { position = 0; ProcessBlock(); }
        }
        Buffer.BlockCopy(samples, 0, buffer, offset, n * 4);
        return read;
    }
}

// Construct replacement filters on the control thread; the audio thread feeds
// both with the same input and blends them without reopening either endpoint.
internal sealed class SwitchingConvolver : IWaveProvider
{
    sealed class Slot {
        internal readonly BufferedWaveProvider Buffer;
        internal readonly ConvolutionProvider Convolver;
        internal Slot(WaveFormat format, string path) {
            Buffer = new BufferedWaveProvider(format);
            Buffer.BufferDuration = TimeSpan.FromSeconds(1);
            Convolver = new ConvolutionProvider(Buffer, path);
        }
    }
    readonly BufferedWaveProvider source;
    Slot current, next, pending;
    int warmFrames, fadePosition;
    readonly int warmLength, fadeLength;
    byte[] incoming = new byte[0], left = new byte[0], right = new byte[0];
    float[] oldSamples = new float[0], newSamples = new float[0];
    internal volatile float TargetGain=1f, TargetDry=0f, TargetCenter=0f, TargetMaster=1f, TargetCeiling=.1f, TargetWidth=1f;
    internal float OutputLimit=1f;
    internal readonly ReflectionEq Eq, DirectEq;
    public WaveFormat WaveFormat { get { return source.WaveFormat; } }
    internal SwitchingConvolver(BufferedWaveProvider source, string path, int fadeMilliseconds=150) {
        this.source=source;
        current=new Slot(WaveFormat,path);
        Eq=new ReflectionEq(WaveFormat.Channels,WaveFormat.SampleRate);
        DirectEq=new ReflectionEq(WaveFormat.Channels,WaveFormat.SampleRate);
        warmLength=(int)(WaveFormat.SampleRate*.12); // prime the direct delay and early reflections
        fadeLength=Math.Max(1,(int)(WaveFormat.SampleRate * fadeMilliseconds / 1000.0));
    }
    internal void RequestProfile(string path) {
        var prepared=new Slot(WaveFormat,path); // invalid profiles leave the current room intact
        Interlocked.Exchange(ref pending,prepared);
    }
    void Apply(Slot slot) {
        var p=slot.Convolver;
        p.TargetGain=TargetGain; p.TargetDry=TargetDry; p.TargetCenter=TargetCenter;
        p.TargetMaster=TargetMaster; p.TargetCeiling=TargetCeiling; p.TargetWidth=TargetWidth; p.OutputLimit=OutputLimit;
        p.Eq.Target=Eq.Target; p.DirectEq.Target=DirectEq.Target;
    }
    public int Read(byte[] buffer,int offset,int count) {
        int frameBytes=WaveFormat.Channels*4;
        if (incoming.Length<count) incoming=new byte[count];
        int read=source.Read(incoming,0,count), done=0;
        while(done<read) {
            int bytes=Math.Min(read-done,512*frameBytes);
            bytes-=bytes%frameBytes;
            if(bytes==0) break;
            int n=bytes/4;
            if(left.Length<bytes) { left=new byte[bytes]; right=new byte[bytes]; oldSamples=new float[n]; newSamples=new float[n]; }
            if(next==null) {
                next=Interlocked.Exchange(ref pending,null);
                if(next!=null) { warmFrames=0; fadePosition=0; }
            }
            Apply(current); current.Buffer.AddSamples(incoming,done,bytes); current.Convolver.Read(left,0,bytes);
            if(next==null) Buffer.BlockCopy(left,0,buffer,offset+done,bytes);
            else {
                Apply(next); next.Buffer.AddSamples(incoming,done,bytes); next.Convolver.Read(right,0,bytes);
                Buffer.BlockCopy(left,0,oldSamples,0,bytes); Buffer.BlockCopy(right,0,newSamples,0,bytes);
                for(int i=0;i<n;i+=WaveFormat.Channels) {
                    float weight=0f;
                    if(warmFrames<warmLength) warmFrames++;
                    else { weight=Math.Min(1f,fadePosition/(float)fadeLength); fadePosition++; }
                    for(int c=0;c<WaveFormat.Channels;c++) oldSamples[i+c]+=weight*(newSamples[i+c]-oldSamples[i+c]);
                }
                Buffer.BlockCopy(oldSamples,0,buffer,offset+done,bytes);
                if(fadePosition>=fadeLength) { current=next; next=null; }
            }
            done+=bytes;
        }
        return done;
    }
}

internal static class Program
{
    private static volatile bool _stopping;
    private static IEnumerable<MMDevice> RenderDevices(MMDeviceEnumerator devices)
    {
        return devices.EnumerateAudioEndPoints(DataFlow.Render, DeviceState.Active);
    }

    private static MMDevice Find(MMDeviceEnumerator devices, string selector)
    {
        return Find(devices, selector, DataFlow.Render);
    }

    private static MMDevice Find(MMDeviceEnumerator devices, string selector, DataFlow flow)
    {
        var all = devices.EnumerateAudioEndPoints(flow, DeviceState.Active).ToArray();
        var exact = all.FirstOrDefault(d => String.Equals(d.ID, selector, StringComparison.OrdinalIgnoreCase));
        if (exact != null) return exact;
        var matches = all.Where(d => d.FriendlyName.IndexOf(selector, StringComparison.OrdinalIgnoreCase) >= 0).ToArray();
        if (matches.Length == 1) return matches[0];
        if (matches.Length == 0) throw new ArgumentException("No active render endpoint matches: " + selector);
        throw new ArgumentException("More than one render endpoint matches: " + selector);
    }

    private static string Argument(string[] args, string name)
    {
        for (int i = 0; i + 1 < args.Length; i++) if (args[i].Equals(name, StringComparison.OrdinalIgnoreCase)) return args[i + 1];
        return null;
    }

    private static void SetDefault(MMDevice device)
    {
        var policy = (IPolicyConfig)new PolicyConfigClient();
        try
        {
            foreach (ERole role in Enum.GetValues(typeof(ERole)))
            {
                int hr = policy.SetDefaultEndpoint(device.ID, role);
                if (hr != 0) Marshal.ThrowExceptionForHR(hr);
            }
        }
        finally { Marshal.FinalReleaseComObject(policy); }
    }

    private static int Main(string[] args)
    {
        try
        {
            string check = Argument(args, "--check-ir");
            if (check != null) { CheckConvolution(check); return 0; }
            using (var devices = new MMDeviceEnumerator())
            {
                if (args.Contains("--devices"))
                {
                    foreach (var device in RenderDevices(devices)) Console.WriteLine(device.ID + "\t" + device.FriendlyName);
                    return 0;
                }
                if (args.Contains("--capture-devices"))
                {
                    foreach (var device in devices.EnumerateAudioEndPoints(DataFlow.Capture, DeviceState.Active))
                        Console.WriteLine(device.ID + "\t" + device.FriendlyName);
                    return 0;
                }
                if (args.Contains("--meters"))
                {
                    foreach (DataFlow flow in new [] { DataFlow.Render, DataFlow.Capture })
                        foreach (var device in devices.EnumerateAudioEndPoints(flow, DeviceState.Active))
                            Console.WriteLine(flow + "\t" + device.FriendlyName + "\t" + device.AudioMeterInformation.MasterPeakValue.ToString("F6", CultureInfo.InvariantCulture));
                    return 0;
                }
                if (args.Contains("--formats"))
                {
                    foreach (var device in RenderDevices(devices))
                    {
                        var f = device.AudioClient.MixFormat;
                        var ext = f as WaveFormatExtensible;
                        Console.WriteLine(device.FriendlyName + "\t" + f.SampleRate + " Hz\t" + f.Channels + " channels\t" + f.BitsPerSample + " bit\t" + f.Encoding + (ext == null ? "" : "\t" + ext.SubFormat));
                    }
                    return 0;
                }
                if (args.Contains("--default-id"))
                {
                    Console.WriteLine(devices.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia).ID);
                    return 0;
                }
                string setDefault = Argument(args, "--set-default");
                if (setDefault != null)
                {
                    var endpoint = Find(devices, setDefault); SetDefault(endpoint);
                    Console.WriteLine("DEFAULT SET\t" + endpoint.ID + "\t" + endpoint.FriendlyName);
                    return 0;
                }
                if (!args.Contains("--route") && !args.Contains("--bridge")) throw new ArgumentException("Use --devices, --formats, --default-id, --set-default, --route, or --bridge.");
                bool captureInput = args.Contains("--capture-input");
                var input = Find(devices, Required(args, "--input"), captureInput ? DataFlow.Capture : DataFlow.Render);
                var output = Find(devices, Required(args, "--output"));
                if (input.ID == output.ID) throw new ArgumentException("Input and output must be different endpoints to avoid feedback.");
                var profile = RouteProfile.Load(Argument(args, "--profile"));
                using (var capture = captureInput ? new WasapiCapture(input) : new WasapiLoopbackCapture(input))
                using (var player = new WasapiOut(output, AudioClientShareMode.Shared, true, 40))
                {
                    var format = capture.WaveFormat;
                    if (args.Contains("--bridge"))
                    {
                        var ext = format as WaveFormatExtensible;
                        bool isFloat = format.Encoding == WaveFormatEncoding.IeeeFloat ||
                            (ext != null && ext.SubFormat == new Guid("00000003-0000-0010-8000-00aa00389b71"));
                        if (!isFloat || format.BitsPerSample != 32)
                            throw new NotSupportedException("Bridge requires 32-bit float input; endpoint reports " + format);
                        var buffer = new BufferedWaveProvider(format);
                        buffer.BufferDuration = TimeSpan.FromMilliseconds(250);
                        buffer.DiscardOnBufferOverflow = true;
                        capture.DataAvailable += (sender, eventArgs) => buffer.AddSamples(eventArgs.Buffer, 0, eventArgs.BytesRecorded);
                        capture.RecordingStopped += (sender, eventArgs) => { if (eventArgs.Exception != null) Console.Error.WriteLine("CAPTURE STOPPED: " + eventArgs.Exception.Message); _stopping = true; };
                        player.PlaybackStopped += (sender, eventArgs) => { if (eventArgs.Exception != null) Console.Error.WriteLine("PLAYBACK STOPPED: " + eventArgs.Exception.Message); _stopping = true; };
                        var convolver = new SwitchingConvolver(buffer, Required(args, "--ir-profile"));
                        string profileUpdateFile = Argument(args, "--profile-update-file"), lastProfileUpdate = null;
                        string gainFile = Argument(args, "--gain-file");
                        string mixFile = Argument(args, "--mix-file");
                        string wetEqFile = Argument(args, "--wet-eq-file");
                        string directEqFile = Argument(args, "--direct-eq-file");
                        string widthFile = Argument(args, "--width-file");
                        string limitArg = Argument(args, "--output-limit");
                        if (limitArg != null) {
                            float limit;
                            if (!Single.TryParse(limitArg, NumberStyles.Float, CultureInfo.InvariantCulture, out limit) || limit <= 0 || limit > 1)
                                throw new ArgumentException("--output-limit must be greater than zero and at most 1");
                            convolver.OutputLimit = limit;
                        }
                        if (gainFile != null) convolver.TargetGain = 0f;
                        player.Init(convolver);
                        Console.CancelKeyPress += (sender, eventArgs) => { eventArgs.Cancel = true; _stopping = true; };
                        player.Play(); capture.StartRecording();
                        Console.WriteLine("BRIDGE READY\t" + input.FriendlyName + " -> " + output.FriendlyName + "\t" + format);
                        while (!_stopping) {
                            if (profileUpdateFile != null) try {
                                string replacement=File.ReadAllText(profileUpdateFile).Trim();
                                if (replacement.Length>0 && replacement!=lastProfileUpdate) {
                                    lastProfileUpdate=replacement;
                                    try { convolver.RequestProfile(replacement); Console.WriteLine("ROOM UPDATE PREPARED: " + replacement); }
                                    catch (Exception ex) { Console.Error.WriteLine("ROOM UPDATE FAILED: " + ex.Message); }
                                }
                            } catch (IOException) { } catch (UnauthorizedAccessException) { }
                            if (gainFile != null) try {
                                float gain;
                                if (Single.TryParse(File.ReadAllText(gainFile).Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out gain) && !Single.IsNaN(gain) && !Single.IsInfinity(gain))
                                    convolver.TargetGain = Math.Max(0f, Math.Min(2.5f, gain));
                            } catch (IOException) { } catch (UnauthorizedAccessException) { }
                            if (mixFile != null) try {
                                string[] parts = File.ReadAllText(mixFile).Trim().Split(',');
                                int dry, center, master, ceiling;
                                if (parts.Length == 4 && Int32.TryParse(parts[0], out dry) && Int32.TryParse(parts[1], out center) && Int32.TryParse(parts[2], out master) && Int32.TryParse(parts[3], out ceiling)) {
                                    convolver.TargetDry = Math.Max(0, Math.Min(200, dry)) / 100f;
                                    convolver.TargetCenter = Math.Max(0, Math.Min(200, center)) / 100f;
                                    convolver.TargetMaster = Math.Max(0, Math.Min(250, master)) / 100f;
                                    convolver.TargetCeiling = Math.Max(1, Math.Min(100, ceiling)) / 100f;
                                }
                            } catch (IOException) { } catch (UnauthorizedAccessException) { }
                            if (wetEqFile != null) try {
                                string[] entries=File.ReadAllText(wetEqFile).Trim().Split(',');
                                if (entries.Length == 7) {
                                    var values=new float[7]; bool valid=true;
                                    for(int i=0;i<7;i++) {
                                        float value;
                                        if(!Single.TryParse(entries[i],NumberStyles.Float,CultureInfo.InvariantCulture,out value) || Single.IsNaN(value) || Single.IsInfinity(value) || value < -12 || value > 12) { valid=false; break; }
                                        values[i]=value;
                                    }
                                    if(valid) convolver.Eq.Target=values;
                                }
                            } catch (IOException) { } catch (UnauthorizedAccessException) { }
                            if (widthFile != null) try {
                                float width;
                                if (Single.TryParse(File.ReadAllText(widthFile).Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out width) && !Single.IsNaN(width) && !Single.IsInfinity(width))
                                    convolver.TargetWidth = Math.Max(0f, Math.Min(2f, width));
                            } catch (IOException) { } catch (UnauthorizedAccessException) { }
                            if (directEqFile != null) try {
                                string[] entries=File.ReadAllText(directEqFile).Trim().Split(',');
                                if (entries.Length == 7) {
                                    var values=new float[7]; bool valid=true;
                                    for(int i=0;i<7;i++) {
                                        float value;
                                        if(!Single.TryParse(entries[i],NumberStyles.Float,CultureInfo.InvariantCulture,out value) || Single.IsNaN(value) || Single.IsInfinity(value)) { valid=false; break; }
                                        values[i]=Math.Max(-12,Math.Min(12,value));
                                    }
                                    if(valid) convolver.DirectEq.Target=values;
                                }
                            } catch (IOException) { } catch (UnauthorizedAccessException) { }
                            Thread.Sleep(100);
                        }
                        capture.StopRecording(); player.Stop();
                        Console.WriteLine("BRIDGE STOPPED");
                        return 0;
                    }
                    if (format.Channels != 2 || !((format.Encoding == WaveFormatEncoding.IeeeFloat && format.BitsPerSample == 32) ||
                        (format.Encoding == WaveFormatEncoding.Pcm && format.BitsPerSample == 16)))
                        throw new NotSupportedException("Room processing requires stereo 32-bit float or 16-bit PCM; endpoint reports " + format);
                    var buffered = new BufferedWaveProvider(capture.WaveFormat);
                    buffered.BufferDuration = TimeSpan.FromSeconds(2);
                    buffered.DiscardOnBufferOverflow = true;
                    capture.DataAvailable += (sender, eventArgs) => buffered.AddSamples(eventArgs.Buffer, 0, eventArgs.BytesRecorded);
                    player.Init(new RoomWaveProvider(buffered, profile));
                    Console.CancelKeyPress += (sender, eventArgs) => { eventArgs.Cancel = true; _stopping = true; };
                    player.Play(); capture.StartRecording();
                    Console.WriteLine("ROUTE READY\t" + input.FriendlyName + " -> " + output.FriendlyName);
                    Console.WriteLine("ROOM FDN\tRT60=" + profile.Rt60.ToString("0.000", CultureInfo.InvariantCulture) + "s\tDRY=" + profile.Dry.ToString("0.00", CultureInfo.InvariantCulture) + "\tWET=" + profile.Wet.ToString("0.00", CultureInfo.InvariantCulture));
                    while (!_stopping) Thread.Sleep(100);
                    capture.StopRecording(); player.Stop();
                    Console.WriteLine("ROUTE STOPPED");
                }
                return 0;
            }
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("EARNEST AUDIO ERROR: " + error.Message);
            return 2;
        }
    }

    private static void CheckConvolution(string path)
    {
        int rate, channels, length; float[][] expected;
        using (var reader = new BinaryReader(File.OpenRead(path)))
        {
            if (new string(reader.ReadChars(4)) != "ERIR" || reader.ReadInt32() != 1) throw new InvalidDataException("Invalid profile");
            rate = reader.ReadInt32(); channels = reader.ReadInt32(); length = reader.ReadInt32();
            expected = new float[channels][];
            for (int c = 0; c < channels; c++)
            {
                expected[c] = new float[length];
                for (int i = 0; i < length; i++) expected[c][i] = reader.ReadSingle();
            }
        }
        var format = WaveFormat.CreateIeeeFloatWaveFormat(rate, channels);
        var buffered = new BufferedWaveProvider(format); buffered.BufferLength = format.AverageBytesPerSecond * 2;
        var impulse = new float[512 * channels];
        for (int c = 0; c < channels; c++) impulse[c] = 0.01f;
        var data = new byte[impulse.Length * 4]; Buffer.BlockCopy(impulse, 0, data, 0, data.Length);
        buffered.AddSamples(data, 0, data.Length);
        var provider = new ConvolutionProvider(buffered, path);
        var outBytes = new byte[data.Length]; var actual = new float[impulse.Length];
        double maxError = 0; int count = length;
        for (int b = 0; b < 1 + (count + 511) / 512; b++)
        {
            provider.Read(outBytes, 0, outBytes.Length); Buffer.BlockCopy(outBytes, 0, actual, 0, outBytes.Length);
            for (int i = 0; i < 512; i++) for (int c = 0; c < channels; c++)
            {
                int index = (b - 1) * 512 + i;
                float reference = index >= 0 && index < count ? expected[c][index] * 0.01f : 0;
                maxError = Math.Max(maxError, Math.Abs(actual[i * channels + c] - reference));
            }
        }
        if (maxError > 0.00002) throw new InvalidDataException("Convolution impulse check failed: " + maxError);
        Console.WriteLine("CONVOLUTION CHECK OK\tchannels=" + channels + "\tmax_error=" + maxError);
    }

    private static string Required(string[] args, string name)
    {
        string value = Argument(args, name);
        if (String.IsNullOrWhiteSpace(value)) throw new ArgumentException(name + " is required.");
        return value;
    }
}
