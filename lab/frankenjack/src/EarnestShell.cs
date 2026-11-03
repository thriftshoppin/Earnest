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
    // Match the seven peaking filters used by the Earnest host, not StageJack's
    // different ten-band and shelf filter chain.
    public static float[] Curve(int n,float fs,float low,float mid,float high,float height,bool advanced,float[] bands) {
        var result=new float[n];
        for(int i=0;i<n;i++) {
            double w=2*Math.PI*FreqAt(i,n)/fs, cr=Math.Cos(w), ci=-Math.Sin(w), c2r=Math.Cos(2*w), c2i=-Math.Sin(2*w), db=0;
            for(int j=2;j<=8;j++) {
                double A=Math.Pow(10,bands[j]/40), w0=2*Math.PI*Dsp.Freqs[j]/fs, alpha=Math.Sin(w0)/(2*Math.Sqrt(2));
                double b0=1+alpha*A, b1=-2*Math.Cos(w0), b2=1-alpha*A, a0=1+alpha/A, a1=b1, a2=1-alpha/A;
                double nr=b0+b1*cr+b2*c2r, ni=b1*ci+b2*c2i, dr=a0+a1*cr+a2*c2r, di=a1*ci+a2*c2i;
                db+=10*Math.Log10((nr*nr+ni*ni)/(dr*dr+di*di));
            }
            result[i]=(float)db;
        }
        return result;
    }
}
public sealed class EarnestControls {
    readonly EarnestEngine owner; bool bypass;
    public EarnestControls(EarnestEngine owner) { this.owner = owner; }
    public bool Bypass { get { return bypass; } set { bypass=value; owner.SetBypass(value); } }
    public void Set(float reverb,float width,float depth,float height,float level,float size,float tone,float pre,float clarity,float rw,float smooth,float low,float mid,float high,bool advanced,float decay,float[] eq) {
        owner.SetControls((int)reverb, (int)size, (int)tone, (int)clarity, (int)smooth, (int)decay);
        owner.SetReflectionEq(eq);
        owner.SetWidth((int)width);
    }
}
public sealed class EarnestEngine {
    readonly object gate = new object(); readonly System.Threading.Timer timer;
    readonly string root, profile, host, gainFile, eqFile, widthFile, profileUpdateFile; string room; Process bridge; bool active, building; int generation;
    int wet=100, tail=100, absorption=100, scatter=100, diffusion=100, decay=100, width=50; bool bypass; string input, output, error, activeInput, activeOutput;
    readonly float[] wetEq = new float[7];
    readonly StageJackMonitor monitor = new StageJackMonitor();
    public readonly EarnestControls Dsp;
    public EarnestEngine() {
        root = Environment.GetEnvironmentVariable("EARNEST_HOME");
        if (String.IsNullOrEmpty(root)) root=Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"..","..","earnest"));
        room=Path.Combine(root,"inbox","rooms","Union-Stairs.room.json");
        host=Path.Combine(root,"earnest","audio","native","EarnestAudioHost-eq.exe");
        profile=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Earnest","stagejack","room.erir");
        gainFile=Path.Combine(Path.GetDirectoryName(profile),"wet-gain.txt");
        eqFile=Path.Combine(Path.GetDirectoryName(profile),"reflection-eq.txt");
        widthFile=Path.Combine(Path.GetDirectoryName(profile),"stage-width.txt");
        profileUpdateFile=Path.Combine(Path.GetDirectoryName(profile),"profile-update.txt");
        Dsp=new EarnestControls(this); timer=new System.Threading.Timer(delegate { Build(); },null,Timeout.Infinite,Timeout.Infinite);
    }
    public bool Running { get { lock(gate) return active && (building || (bridge != null && !bridge.HasExited)); } }
    public bool Building { get { lock(gate) return building; } }
    public string Error { get { lock(gate) return error; } }
    public string RoomPath { get { lock(gate) return room; } }
    public void SelectRoom(string path) {
        string selected=Path.GetFullPath(path);
        if (!File.Exists(selected)) throw new FileNotFoundException("Room file not found", selected);
        lock(gate) { room=selected; error=null; }
        Schedule();
    }
    public void Start(int inId,int outId,string ignored) {
        var rows=Mme.Outputs();
        if (inId<0 || inId>=rows.Count || outId<0 || outId>=rows.Count) { lock(gate) error="Endpoint is unavailable; rescan"; return; }
        lock(gate) { input=rows[inId].EndpointId; output=rows[outId].EndpointId; active=true; error=null; }
        Schedule();
    }
    public void SetControls(int w,int t,int a,int s,int d,int decayValue) {
        t=Math.Max(10,t); decayValue=Math.Max(10,Math.Min(250,decayValue));
        bool roomChanged;
        lock(gate) { if(wet==w && tail==t && absorption==a && scatter==s && diffusion==d && decay==decayValue) return; roomChanged=tail!=t || absorption!=a || scatter!=s || diffusion!=d || decay!=decayValue; wet=w; tail=t; absorption=a; scatter=s; diffusion=d; decay=decayValue; WriteGain(); }
        if(roomChanged) Schedule();
    }
    void WriteGain() {
        Directory.CreateDirectory(Path.GetDirectoryName(gainFile));
        File.WriteAllText(gainFile, ((bypass ? 0f : wet/100f)).ToString("0.000", CultureInfo.InvariantCulture));
    }
    public void SetWidth(int value) {
        lock(gate) { value=Math.Max(0,Math.Min(100,value)); if(width==value)return; width=value; WriteWidth(); }
    }
    void WriteWidth() {
        Directory.CreateDirectory(Path.GetDirectoryName(widthFile));
        File.WriteAllText(widthFile,(width/50f).ToString("0.000",CultureInfo.InvariantCulture));
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
        int id,w,t,a,s,d,dec; string source,dest,roomFile;
        lock(gate) { if(!active || building) { if(active) timer.Change(1000,Timeout.Infinite); return; } building=true; id=generation; w=100; t=tail; a=absorption; s=scatter; d=diffusion; dec=decay; source=input; dest=output; roomFile=room; }
        string temp=Path.Combine(Path.GetDirectoryName(profile),"room-"+id+".erir");
        try {
            Directory.CreateDirectory(Path.GetDirectoryName(profile));
            if(!File.Exists(roomFile) || !File.Exists(host)) throw new Exception("Earnest room or audio host not found in " + root);
            var psi=new ProcessStartInfo("python", "-u -m earnest.audio.stagejack "+Q(roomFile)+" "+Q(temp)+" --wet "+w+" --tail "+t+" --decay "+dec+" --absorption "+a+" --scattering "+s+" --diffusion "+d);
            psi.WorkingDirectory=root; psi.UseShellExecute=false; psi.CreateNoWindow=true; psi.RedirectStandardOutput=true; psi.RedirectStandardError=true;
            using(var p=Process.Start(psi)) { string stdout=p.StandardOutput.ReadToEnd(); string stderr=p.StandardError.ReadToEnd(); p.WaitForExit(); if(p.ExitCode!=0) throw new Exception("Room compilation failed: " + stderr + stdout); }
            lock(gate) {
                if (!active || id!=generation) return;
                if (bridge!=null && !bridge.HasExited && source==activeInput && dest==activeOutput) {
                    string updateTemp=profileUpdateFile+"."+id+".tmp";
                    File.WriteAllText(updateTemp,temp);
                    if(File.Exists(profileUpdateFile)) File.Replace(updateTemp,profileUpdateFile,null);
                    else File.Move(updateTemp,profileUpdateFile);
                    error=null;
                    return;
                }
                if (bridge!=null && !bridge.HasExited) { bridge.Kill(); bridge.WaitForExit(); }
                WriteGain(); WriteEq(); WriteWidth();
                if(File.Exists(profileUpdateFile)) File.Delete(profileUpdateFile);
                var run=new ProcessStartInfo(host,"--bridge --input "+Q(source)+" --output "+Q(dest)+" --ir-profile "+Q(temp)+" --profile-update-file "+Q(profileUpdateFile)+" --gain-file "+Q(gainFile)+" --wet-eq-file "+Q(eqFile)+" --mix-file "+Q(Path.Combine(Path.GetDirectoryName(profile),"advanced-mix.txt"))+" --direct-eq-file "+Q(Path.Combine(Path.GetDirectoryName(profile),"direct-eq.txt"))+" --width-file "+Q(widthFile)+" --output-limit 1");
                run.WorkingDirectory=Path.GetDirectoryName(host); run.UseShellExecute=false; run.CreateNoWindow=false;
                bridge=Process.Start(run); activeInput=source; activeOutput=dest; error=null;
            }
        } catch(Exception ex) { lock(gate) { if(active && id==generation) { error=ex.Message; active=bridge!=null && !bridge.HasExited; } } }
        finally { lock(gate) { building=false; if(active && id!=generation) timer.Change(900,Timeout.Infinite); } }
    }
    public void Stop() { lock(gate) { active=false; generation++; timer.Change(Timeout.Infinite,Timeout.Infinite); if(bridge!=null && !bridge.HasExited) { bridge.Kill(); bridge.WaitForExit(); } bridge=null; } }
    public void Shutdown() { Stop(); timer.Dispose(); monitor.Dispose(); }
    public string MonitorError { get { return monitor.MonitorError; } }
    public void SetAnalysisEndpoint(string endpoint) { monitor.SetAnalysisEndpoint(endpoint); }
    public void CopyRecentOutput(float[] l,float[] r) { monitor.CopyRecentOutput(l,r); }
    public void CopyRecentInput(float[] l,float[] r) { Array.Clear(l,0,l.Length); Array.Clear(r,0,r.Length); }
}
