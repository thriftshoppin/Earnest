// Loopback spectrum monitor reused from the original StageJack AudioEngine.
using System;
using NAudio.Wave;
using NAudio.CoreAudioApi;

internal sealed class StageJackMonitor : IDisposable {
    const int InputTapLength=8192;
    readonly float[] outputTapL=new float[InputTapLength], outputTapR=new float[InputTapLength];
    readonly object outputTapLock=new object();
    int outputTapWrite, outputTapLastTick, outputTapCount; bool outputHasData;
    float[] clipSamples; int clipFrames, clipRate; bool clipActive;
    public bool ClipLimitReached { get; private set; }
    WasapiLoopbackCapture systemLoopback; MMDeviceEnumerator analysisEnumerator; MMDevice systemLoopbackDevice;
    string analysisEndpointId; bool analysisConfigured;
    internal string MonitorError;
    public void BeginClip(int seconds) {
        if (seconds < 1 || seconds > 300) throw new ArgumentOutOfRangeException("seconds");
        lock(outputTapLock) {
            if (systemLoopback == null) throw new InvalidOperationException("Select an active analysis playback device first.");
            if (systemLoopback.WaveFormat.Channels > 2) throw new InvalidOperationException("Demo capture currently supports mono or stereo analysis devices.");
            clipRate=systemLoopback.WaveFormat.SampleRate;
            clipSamples=new float[clipRate * seconds * 2]; clipFrames=0; clipActive=true; ClipLimitReached=false;
        }
    }
    public int FinishClip(string path) {
        float[] samples; int frames, rate;
        lock(outputTapLock) { clipActive=false; samples=clipSamples; frames=clipFrames; rate=clipRate; clipSamples=null; }
        if (samples==null || frames==0) throw new InvalidOperationException("No audio frames arrived; check the analysis device and playback.");
        using (var writer=new WaveFileWriter(path,WaveFormat.CreateIeeeFloatWaveFormat(rate,2))) writer.WriteSamples(samples,0,frames*2);
        return frames;
    }
    public void CopyRecentOutput(float[] left,float[] right) {
        if(left==null || right==null || left.Length!=right.Length) return;
        lock(outputTapLock) {
            int age=unchecked(Environment.TickCount-outputTapLastTick);
            if(!outputHasData || age>500) { Array.Clear(left,0,left.Length); Array.Clear(right,0,right.Length); outputTapCount=0; outputHasData=false; return; }
            CopyRecent(outputTapL,outputTapR,outputTapWrite,outputTapCount,left,right);
        }
    }
    static void CopyRecent(float[] ringL, float[] ringR, int write, int available, float[] left, float[] right) {
        if (left == null || right == null || left.Length != right.Length) return;
        available = Math.Min(available, InputTapLength);
        int count = Math.Min(left.Length, available);
        int pad = left.Length - count;
        for (int i = 0; i < pad; i++) { left[i] = 0f; right[i] = 0f; }
        int start = (write - count + InputTapLength) & (InputTapLength - 1);
        for (int i = 0; i < count; i++) {
            int at = (start + i) & (InputTapLength - 1);
            left[pad + i] = ringL[at];
            right[pad + i] = ringR[at];
        }
    }

    void TapSystemOutput(object sender, WaveInEventArgs e) {
        WasapiLoopbackCapture capture = sender as WasapiLoopbackCapture;
        if (capture == null || e.BytesRecorded <= 0) return;
        WaveFormat format = capture.WaveFormat;
        int block = format.BlockAlign;
        int channels = Math.Max(1, format.Channels);
        int sampleBytes = Math.Max(1, format.BitsPerSample / 8);
        if (block <= 0 || e.BytesRecorded < block) return;
        var ext = format as WaveFormatExtensible;
        bool isFloat = format.BitsPerSample == 32 && (format.Encoding == WaveFormatEncoding.IeeeFloat || (ext != null && ext.SubFormat == new Guid("00000003-0000-0010-8000-00aa00389b71")));
        int frames = e.BytesRecorded / block;
        lock (outputTapLock) {
            int w = outputTapWrite;
            for (int i = 0; i < frames; i++) {
                int frame = i * block;
                float l = ReadLoopbackSample(e.Buffer, frame, format.BitsPerSample, isFloat);
                float r = channels > 1 ? ReadLoopbackSample(e.Buffer, frame + sampleBytes, format.BitsPerSample, isFloat) : l;
                outputTapL[w] = ClampSample(l); outputTapR[w] = ClampSample(r);
                if(clipActive && format.SampleRate==clipRate && clipFrames*2 < clipSamples.Length) {
                    clipSamples[clipFrames*2]=ClampSample(l); clipSamples[clipFrames*2+1]=ClampSample(r); clipFrames++;
                    if(clipFrames*2==clipSamples.Length) { clipActive=false; ClipLimitReached=true; }
                }
                w = (w + 1) & (InputTapLength - 1);
            }
            outputTapCount = Math.Min(InputTapLength, outputTapCount + frames);
            outputTapWrite = w;
            outputTapLastTick = Environment.TickCount;
            outputHasData = true;
        }
    }

    static float ReadLoopbackSample(byte[] data, int offset, int bits, bool isFloat) {
        if (isFloat) return BitConverter.ToSingle(data, offset);
        if (bits == 8) return (data[offset] - 128) / 128f;
        if (bits == 16) return BitConverter.ToInt16(data, offset) / 32768f;
        if (bits == 24) {
            int raw = data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16);
            if ((raw & 0x800000) != 0) raw |= unchecked((int)0xff000000);
            return raw / 8388608f;
        }
        if (bits == 32) return BitConverter.ToInt32(data, offset) / 2147483648f;
        return 0f;
    }

    static float ClampSample(float value) {
        if (float.IsNaN(value) || float.IsInfinity(value)) return 0f;
        return value > 1f ? 1f : (value < -1f ? -1f : value);
    }

    void StartSystemLoopback(string endpointId) {
        StopSystemLoopback();
        lock (outputTapLock) {
            outputTapCount = 0; outputTapWrite = 0; outputHasData = false; outputTapLastTick = 0;
            Array.Clear(outputTapL, 0, outputTapL.Length); Array.Clear(outputTapR, 0, outputTapR.Length);
        }
        MMDevice device = null;
        WasapiLoopbackCapture capture = null;
        try {
            if (analysisEnumerator == null) analysisEnumerator = new MMDeviceEnumerator();
            device = string.IsNullOrEmpty(endpointId)
                ? analysisEnumerator.GetDefaultAudioEndpoint(DataFlow.Render, Role.Multimedia)
                : analysisEnumerator.GetDevice(endpointId);
            capture = new WasapiLoopbackCapture(device);
            capture.DataAvailable += TapSystemOutput;
            capture.RecordingStopped += delegate(object sender, StoppedEventArgs e) {
                if (e.Exception != null) MonitorError = e.Exception.Message;
            };
            systemLoopbackDevice = device;
            systemLoopback = capture;
            analysisEndpointId = endpointId;
            analysisConfigured = true;
            capture.StartRecording();
            MonitorError = null;
        } catch (Exception e) {
            MonitorError = e.Message;
            try { if (capture != null) capture.Dispose(); } catch { }
            try { if (device != null) device.Dispose(); } catch { }
            systemLoopback = null; systemLoopbackDevice = null;
            analysisEndpointId = endpointId;
            analysisConfigured = true;
        }
    }

    void StopSystemLoopback() {
        lock(outputTapLock) { clipActive=false; }
        WasapiLoopbackCapture capture = systemLoopback;
        MMDevice device = systemLoopbackDevice;
        systemLoopback = null;
        systemLoopbackDevice = null;
        if (capture != null) {
            capture.DataAvailable -= TapSystemOutput;
            try { capture.StopRecording(); } catch { }
            try { capture.Dispose(); } catch { }
        }
        try { if (device != null) device.Dispose(); } catch { }
    }

    public void SetAnalysisEndpoint(string endpointId) {
        if(analysisConfigured && string.Equals(analysisEndpointId,endpointId,StringComparison.OrdinalIgnoreCase) && systemLoopback!=null) return;
        StartSystemLoopback(endpointId);
    }
    public void Dispose() { StopSystemLoopback(); try { if(analysisEnumerator!=null) analysisEnumerator.Dispose(); } catch {} analysisEnumerator=null; }
}
