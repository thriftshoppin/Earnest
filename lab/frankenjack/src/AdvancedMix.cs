using System;
using System.Drawing;
using System.Globalization;
using System.Collections.Generic;
using System.IO;
using System.Windows.Forms;

// Separate direct and center control for the Earnest-only bridge.
public sealed class AdvancedMix : Form {
    readonly TrackBar dry = new TrackBar(), center = new TrackBar(), master = new TrackBar(), ceiling = new TrackBar();
    readonly Label dryValue = new Label(), centerValue = new Label(), masterValue = new Label(), ceilingValue = new Label();
    readonly string path;
    readonly Dictionary<string, TrackBar> engineBars = new Dictionary<string, TrackBar>();
    readonly Dictionary<string, Label> engineValues = new Dictionary<string, Label>();
    public AdvancedMix(Func<string,int> readControl, Action<string,int> setControl, string controlPath = null) {
        path = controlPath ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Earnest", "stagejack", "advanced-mix.txt");
        Text = "Earnest | Advanced mix and room controls"; Width = 570; Height = 720; FormBorderStyle = FormBorderStyle.Sizable; AutoScroll = true;
        BackColor = Color.FromArgb(19,25,25); ForeColor = Color.White; StartPosition = FormStartPosition.CenterParent;
        AddRow("DIRECT / DRY", dry, dryValue, 0, 200, 0, 20);
        AddRow("CENTER REINFORCEMENT", center, centerValue, 0, 200, 0, 90);
        AddRow("MASTER GAIN", master, masterValue, 0, 250, 100, 160);
        AddRow("PEAK CEILING", ceiling, ceilingValue, 1, 100, 10, 230);
        var note = new Label { Text = "Center boosts shared L/R, not vocals alone. Ceiling is a hard clamp. Enable ROOM and EQ on the main panel; shape changes restart the bridge.", Left = 18, Top = 305, Width = 490, Height = 42, ForeColor = Color.LightGray };
        Controls.Add(note);
        int y = 355;
        string[] keys = { "Reverb", "Reverb size", "Decay", "Reverb tone", "Reverb clarity", "Smoothness", "125 Hz", "250 Hz", "500 Hz", "1 kHz", "2 kHz", "4 kHz", "8 kHz" };
        string[] labels = { "WET FIELD GAIN", "TAIL LENGTH SCALE", "DECAY TIME SCALE", "ABSORPTION SCALE", "SCATTERING SCALE", "DIFFUSE ENERGY SCALE", "WET EQ 125 Hz", "WET EQ 250 Hz", "WET EQ 500 Hz", "WET EQ 1 kHz", "WET EQ 2 kHz", "WET EQ 4 kHz", "WET EQ 8 kHz" };
        for (int i = 0; i < keys.Length; i++) {
            string key = keys[i]; int min = i < 6 ? (i == 1 || i == 2 ? 10 : 0) : -12, max = i < 6 ? 250 : 12;
            AddEngineRow(labels[i], key, readControl(key), min, max, y, setControl); y += 70;
        }
        AutoScrollMinSize = new Size(0, y + 15);
        LoadSaved(); Write();
    }
    void AddEngineRow(string title, string key, int initial, int min, int max, int y, Action<string,int> setControl) {
        var caption = new Label { Text = title, Left = 18, Top = y, Width = 300, Height = 22 }; Controls.Add(caption);
        var value = new Label { Left=450, Top=y, Width=65, Height=22 }; Controls.Add(value);
        var bar = new TrackBar { Minimum=min, Maximum=max, Value=Math.Max(min,Math.Min(max,initial)), TickStyle=TickStyle.None };
        bar.Name=key; engineBars[key]=bar; engineValues[key]=value;
        bar.SetBounds(14,y+22,495,36); value.Text = bar.Value + (min < 0 ? " dB" : "%");
        bar.Scroll += delegate { value.Text = bar.Value + (min < 0 ? " dB" : "%"); setControl(key,bar.Value); };
        Controls.Add(bar);
    }
    public void SyncEngineControl(string key, int value) {
        TrackBar bar; Label label;
        if (engineBars.TryGetValue(key, out bar) && engineValues.TryGetValue(key, out label)) {
            bar.Value = Math.Max(bar.Minimum, Math.Min(bar.Maximum, value));
            label.Text = bar.Value + (bar.Minimum < 0 ? " dB" : "%");
        }
    }
    void AddRow(string title, TrackBar bar, Label value, int min, int max, int initial, int y) {
        Controls.Add(new Label { Text = title, Left = 18, Top = y, Width = 290, Height = 22 });
        value.SetBounds(450,y,65,22); Controls.Add(value);
        bar.Name=title; bar.Minimum=min; bar.Maximum=max; bar.Value=initial; bar.TickStyle=TickStyle.None; bar.SetBounds(14,y+22,495,36);
        bar.Scroll += delegate { Write(); }; Controls.Add(bar);
    }
    void LoadSaved() {
        try { var s=File.ReadAllText(path).Split(','); if(s.Length!=4)return; int d,c,m,l; if(int.TryParse(s[0],out d)&&int.TryParse(s[1],out c)&&int.TryParse(s[2],out m)&&int.TryParse(s[3],out l)) { dry.Value=Math.Max(0,Math.Min(200,d)); center.Value=Math.Max(0,Math.Min(200,c)); master.Value=Math.Max(0,Math.Min(250,m)); ceiling.Value=Math.Max(1,Math.Min(100,l)); } } catch(IOException) {} catch(UnauthorizedAccessException) {}
    }
    void Write() {
        dryValue.Text=dry.Value+"%"; centerValue.Text=center.Value+"%"; masterValue.Text=master.Value+"%"; ceilingValue.Text=ceiling.Value+"%";
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        File.WriteAllText(path, String.Format(CultureInfo.InvariantCulture,"{0},{1},{2},{3}",dry.Value,center.Value,master.Value,ceiling.Value));
    }
}
