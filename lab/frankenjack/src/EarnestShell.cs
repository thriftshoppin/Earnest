// StageJack interface support for the Earnest-only build. No StageJack DSP.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Globalization;
using System.Threading;
using NAudio.CoreAudioApi;

public sealed class Device { public int Id; public string Name, EndpointId; public override string ToString() { return Name; } }
public static class Mme {
    static List<Device> List(DataFlow flow) {
        var result = new List<Device>();
        using (var e = new MMDeviceEnumerator()) foreach (var d in e.EnumerateAudioEndPoints(flow, DeviceState.Active))
            result.Add(new Device { Id = result.Count, Name = d.FriendlyName, EndpointId = d.ID });
        return result;
    }
    public static List<Device> Inputs() { return List(DataFlow.Capture); }
    public static List<Device> Outputs() { return List(DataFlow.Render); }
}
public static class AudioEngine { public const int Rate = 48000; }
public static class Dsp { public static readonly float[] Freqs = {31,62,125,250,500,1000,2000,4000,8000,16000}; }
public static class EqModel {
    public const float LowHz=150, MidHz=1000, HighHz=5000;
    public static float FreqAt(int i,int n) { return (float)(20*Math.Pow(1000,i/(double)(n-1))); }
    public static float[] Curve(int n,float fs,float low,float mid,float high,float height,bool advanced,float[] bands) { return new float[n]; }
}
public sealed class EarnestControls {
    readonly EarnestEngine owner; bool bypass;
    public EarnestControls(EarnestEngine owner) { this.owner = owner; }
    public bool Bypass { get { return bypass; } set { bypass=value; owner.SetBypass(value); } }
    public void Set(float reverb,float width,float depth,float height,float level,float size,float tone,float pre,float clarity,float rw,float smooth,float low,float mid,float high,bool advanced,float[] eq) {
        owner.SetControls((int)reverb, (int)size, (int)tone, (int)clarity, (int)smooth);
        owner.SetReflectionEq(eq);
    }
}
public sealed class EarnestEngine {
    readonly object gate = new object(); readonly System.Threading.Timer timer;
    readonly string root, room, profile, host, gainFile, eqFile; Process bridge; bool active, building; int generation;
    int wet=100, tail=100, absorption=100, scatter=100, diffusion=100; bool bypass; string input, output, error;
    readonly float[] wetEq = new float[7];
    public readonly EarnestControls Dsp;
    public EarnestEngine() {
        root = Environment.GetEnvironmentVariable("EARNEST_HOME");
        if (String.IsNullOrEmpty(root)) root=Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"..","..","earnest"));
        room=Path.Combine(root,"inbox","rooms","Union-Stairs.room.json");
        host=Path.Combine(root,"earnest","audio","native","EarnestAudioHost-eq.exe");
        profile=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Earnest","stagejack","room.erir");
        gainFile=Path.Combine(Path.GetDirectoryName(profile),"wet-gain.txt");
        eqFile=Path.Combine(Path.GetDirectoryName(profile),"reflection-eq.txt");
        Dsp=new EarnestControls(this); timer=new System.Threading.Timer(delegate { Build(); },null,Timeout.Infinite,Timeout.Infinite);
    }
    public bool Running { get { lock(gate) return active && (building || (bridge != null && !bridge.HasExited)); } }
    public bool Building { get { lock(gate) return building; } }
    public string Error { get { lock(gate) return error; } }
    public void Start(int inId,int outId,string ignored) {
        var rows=Mme.Outputs();
        if (inId<0 || inId>=rows.Count || outId<0 || outId>=rows.Count) { lock(gate) error="Endpoint is unavailable; rescan"; return; }
        lock(gate) { input=rows[inId].EndpointId; output=rows[outId].EndpointId; active=true; error=null; }
        Schedule();
    }
    public void SetControls(int w,int t,int a,int s,int d) {
        t=Math.Max(10,t);
        bool roomChanged;
        lock(gate) { if(wet==w && tail==t && absorption==a && scatter==s && diffusion==d) return; roomChanged=tail!=t || absorption!=a || scatter!=s || diffusion!=d; wet=w; tail=t; absorption=a; scatter=s; diffusion=d; WriteGain(); }
        if(roomChanged) Schedule();
    }
    void WriteGain() {
        Directory.CreateDirectory(Path.GetDirectoryName(gainFile));
        File.WriteAllText(gainFile, ((bypass ? 0f : wet/100f)).ToString("0.000", CultureInfo.InvariantCulture));
    }
    public void SetBypass(bool value) { lock(gate) { bypass=value; WriteGain(); } }
    public void SetReflectionEq(float[] values) {
        bool changed=false;
        lock(gate) {
            for(int i=0;i<7;i++) { float value=Math.Max(-12,Math.Min(12,values[i+2])); if(wetEq[i]!=value) { wetEq[i]=value; changed=true; } }
            if(changed) WriteEq();
        }
    }
    void WriteEq() {
        Directory.CreateDirectory(Path.GetDirectoryName(eqFile));
        string[] values=new string[7]; for(int i=0;i<7;i++) values[i]=wetEq[i].ToString("0.00",CultureInfo.InvariantCulture);
        File.WriteAllText(eqFile,String.Join(",",values));
    }
    public void Schedule() { lock(gate) { if(!active) return; generation++; timer.Change(900,Timeout.Infinite); } }
    static string Q(string s) { return "\"" + s.Replace("\"", "") + "\""; }
    void Build() {
        int id,w,t,a,s,d; string source,dest;
        lock(gate) { if(!active || building) { if(active) timer.Change(1000,Timeout.Infinite); return; } building=true; id=generation; w=100; t=tail; a=absorption; s=scatter; d=diffusion; source=input; dest=output; }
        string temp=Path.Combine(Path.GetDirectoryName(profile),"room-"+id+".erir");
        try {
            Directory.CreateDirectory(Path.GetDirectoryName(profile));
            if(!File.Exists(room) || !File.Exists(host)) throw new Exception("Earnest room or audio host not found in " + root);
            var psi=new ProcessStartInfo("python", "-u -m earnest.audio.stagejack "+Q(room)+" "+Q(temp)+" --wet "+w+" --tail "+t+" --absorption "+a+" --scattering "+s+" --diffusion "+d);
            psi.WorkingDirectory=root; psi.UseShellExecute=false; psi.CreateNoWindow=true; psi.RedirectStandardOutput=true; psi.RedirectStandardError=true;
            using(var p=Process.Start(psi)) { string stdout=p.StandardOutput.ReadToEnd(); string stderr=p.StandardError.ReadToEnd(); p.WaitForExit(); if(p.ExitCode!=0) throw new Exception("Room compilation failed: " + stderr + stdout); }
            lock(gate) {
                if (!active || id!=generation) return;
                if (bridge!=null && !bridge.HasExited) { bridge.Kill(); bridge.WaitForExit(); }
                WriteGain(); WriteEq();
                var run=new ProcessStartInfo(host,"--bridge --input "+Q(source)+" --output "+Q(dest)+" --ir-profile "+Q(temp)+" --gain-file "+Q(gainFile)+" --wet-eq-file "+Q(eqFile)+" --mix-file "+Q(Path.Combine(Path.GetDirectoryName(profile),"advanced-mix.txt"))+" --output-limit 1");
                run.WorkingDirectory=Path.GetDirectoryName(host); run.UseShellExecute=false; run.CreateNoWindow=false;
                bridge=Process.Start(run); error=null;
            }
        } catch(Exception ex) { lock(gate) { error=ex.Message; active=false; } }
        finally { lock(gate) { building=false; if(active && id!=generation) timer.Change(900,Timeout.Infinite); } }
    }
    public void Stop() { lock(gate) { active=false; generation++; timer.Change(Timeout.Infinite,Timeout.Infinite); if(bridge!=null && !bridge.HasExited) { bridge.Kill(); bridge.WaitForExit(); } bridge=null; } }
    public void Shutdown() { Stop(); timer.Dispose(); }
    public void SetAnalysisEndpoint(string ignored) { }
    public void CopyRecentOutput(float[] l,float[] r) { Array.Clear(l,0,l.Length); Array.Clear(r,0,r.Length); }
    public void CopyRecentInput(float[] l,float[] r) { Array.Clear(l,0,l.Length); Array.Clear(r,0,r.Length); }
}
