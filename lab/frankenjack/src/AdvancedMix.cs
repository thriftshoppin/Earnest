using System;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Windows.Forms;

// Separate direct and center control for the Earnest-only bridge.
public sealed class AdvancedMix : Form {
    readonly TrackBar dry = new TrackBar(), center = new TrackBar(), master = new TrackBar(), ceiling = new TrackBar();
    readonly Label dryValue = new Label(), centerValue = new Label(), masterValue = new Label(), ceilingValue = new Label();
    readonly string path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Earnest", "stagejack", "advanced-mix.txt");
    public AdvancedMix() {
        Text = "Earnest | Advanced mix"; Width = 540; Height = 380; FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false;
        BackColor = Color.FromArgb(19,25,25); ForeColor = Color.White; StartPosition = FormStartPosition.CenterParent;
        AddRow("DIRECT / DRY", dry, dryValue, 0, 200, 0, 20);
        AddRow("CENTER REINFORCEMENT", center, centerValue, 0, 200, 0, 90);
        AddRow("MASTER GAIN", master, masterValue, 0, 250, 100, 160);
        AddRow("PEAK CEILING", ceiling, ceilingValue, 1, 100, 10, 230);
        var note = new Label { Text = "Center boosts shared L/R content, including instruments. Wet uses the existing Reverb control. Increase ceiling yourself if needed.", Left = 18, Top = 310, Width = 490, Height = 32, ForeColor = Color.LightGray };
        Controls.Add(note);
        LoadSaved(); Write();
    }
    void AddRow(string title, TrackBar bar, Label value, int min, int max, int initial, int y) {
        Controls.Add(new Label { Text = title, Left = 18, Top = y, Width = 290, Height = 22 });
        value.SetBounds(450,y,65,22); Controls.Add(value);
        bar.Minimum=min; bar.Maximum=max; bar.Value=initial; bar.TickStyle=TickStyle.None; bar.SetBounds(14,y+22,495,36);
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
