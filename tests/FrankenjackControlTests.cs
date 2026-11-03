// Construct the controls without showing a window or starting audio.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

internal static class FrankenjackControlTests {
    static int failures;
    static void Check(bool value,string message) { Console.WriteLine((value ? "PASS " : "FAIL ")+message); if(!value)failures++; }
    static TrackBar Find(Form form,string name) {
        foreach(Control c in form.Controls) if(c is TrackBar && c.Name==name) return (TrackBar)c;
        throw new Exception("Missing trackbar: "+name);
    }
    static void Move(TrackBar bar,int value) {
        bar.Value=value;
        typeof(TrackBar).GetMethod("OnScroll",BindingFlags.Instance|BindingFlags.NonPublic).Invoke(bar,new object[]{EventArgs.Empty});
    }
    [STAThread] static int Main() {
        string path=Path.Combine(Path.GetTempPath(),"earnest-controls-"+Guid.NewGuid().ToString("N")+".txt");
        var values=new Dictionary<string,int>();
        Func<string,int> read = key => key=="Reverb size"?100:key=="Decay"?100:key=="Reverb"?100:0;
        Action<string,int> write = (key,value) => values[key]=value;
        try {
            using(var panel=new AdvancedMix(read,write,path,()=>"chosen.room.json",room=>{})) {
                Check(panel.Controls.Find("ChooseRoom",false).Length==1,"room selection is available");
                Check(panel.Controls.Find("SelectedRoom",false)[0].Text.Contains("chosen.room.json"),"selected room is displayed");
                Check(File.ReadAllText(path)=="0,0,100,10","safe initial mix state");
                Move(Find(panel,"DIRECT / DRY"),35);
                Move(Find(panel,"CENTER REINFORCEMENT"),20);
                Check(File.ReadAllText(path)=="35,20,100,10","dry and center update bridge file");
                Move(Find(panel,"ROOM CROSSFADE"),350);
                Check(File.ReadAllText(path+".crossfade")=="350","room crossfade updates bridge file");
                Move(Find(panel,"Reverb"),80);
                Move(Find(panel,"Reverb tone"),120);
                Move(Find(panel,"Decay"),150);
                Move(Find(panel,"DIRECT EQ 1 kHz"),6);
                Move(Find(panel,"1 kHz"),6);
                Check(values["Reverb"]==80,"wet control maps to existing engine slider");
                Check(File.ReadAllText(path+".directeq")=="0,0,0,6,0,0,0","direct EQ writes a separate band control");
                Check(values["Decay"]==150,"decay time has an independent control");
                Check(values["Reverb tone"]==120,"absorption maps to existing engine slider");
                Check(values["1 kHz"]==6,"wet EQ maps to existing engine slider");
                panel.SyncEngineControl("Reverb",42);
                Check(Find(panel,"Reverb").Value==42,"main-to-advanced slider synchronization");
                Check(values["Reverb"]==80,"synchronization does not re-trigger control callback");
            }
        } finally { if(File.Exists(path))File.Delete(path); if(File.Exists(path+".directeq"))File.Delete(path+".directeq"); if(File.Exists(path+".crossfade"))File.Delete(path+".crossfade"); }
        return failures==0 ? 0 : 1;
    }
}
