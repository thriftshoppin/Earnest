using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Text;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32;
using System.Windows.Forms;

static class Program {
    [STAThread] static void Main() {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        try { Application.Run(new MainWindow()); }
        catch (Exception e) { MessageBox.Show(e.Message, "StageJack", MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }
}

// Named reverb spaces. Values come from measured behavior of the reference reverb (decay, tone, width, level, pre-delay), not from copied audio.
// EDIT THIS TABLE to tune a space. T30 = seconds for the tail to fall 30 dB; Tone 0 (dark) - 100 (bright); Width 0-100; Wet = Reverb amount 0-100; Pre = pre-delay ms (keep 0-5).
sealed class ReverbSpace {
    public readonly string Name; public readonly float T30; public readonly int Tone, Width, Wet, Pre;
    public ReverbSpace(string name, float t30, int tone, int width, int wet, int pre) { Name = name; T30 = t30; Tone = tone; Width = width; Wet = wet; Pre = pre; }
    public static readonly ReverbSpace[] All = {
        new ReverbSpace("Campus",     0.55f, 80,  70, 25, 2),   // brightest
        new ReverbSpace("Rhythm",     0.35f, 60,  60, 15, 0),   // quieter
        new ReverbSpace("Classroom",  0.18f, 55,  50, 15, 0),   // shortest, quieter
        new ReverbSpace("Dorm",       0.45f, 25,  80, 35, 3),   // dark, louder
        new ReverbSpace("Union",      0.90f, 20,  90, 40, 4),   // longest, dark, louder
        new ReverbSpace("Innovation", 0.70f, 45,  85, 38, 2)    // louder
    };
    // Engine tail length is RT60 = 0.3 * 24^(size/100) seconds, and RT60 is about 2 x T30
    public static int SizeFor(float t30) {
        double s = 100.0 * Math.Log(2.0 * t30 / 0.3) / Math.Log(24.0);
        return (int)Math.Max(0, Math.Min(100, Math.Round(s)));
    }
}

sealed class MainWindow : Form {
    const int WM_SETTINGCHANGE = 0x001A, WM_THEMECHANGED = 0x031A, WM_DWMCOLORIZATIONCOLORCHANGED = 0x0320;
    const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19;
    [DllImport("dwmapi.dll", EntryPoint = "DwmSetWindowAttribute")]
    static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);
    readonly Color accent = Theme.Accent, bg = Color.FromArgb(11, 13, 13), card = Color.FromArgb(23, 27, 26), muted = Color.FromArgb(160, 170, 166), white = Color.FromArgb(238, 242, 240);
    readonly Dictionary<string, StageSlider> sliders = new Dictionary<string, StageSlider>();
    static readonly string[] bands = { "31 Hz", "62 Hz", "125 Hz", "250 Hz", "500 Hz", "1 kHz", "2 kHz", "4 kHz", "8 kHz", "16 kHz" };
    readonly EarnestEngine engine = new EarnestEngine();
    readonly string savePath;
    readonly Timer saveTimer, pollTimer, pingTimer;
    readonly Label status; NotifyIcon trayIcon;
    readonly PrivateFontCollection fonts = new PrivateFontCollection();
    Font regular, strong, display, small;
    ComboBox inBox, outBox, analysisBox, spaceBox; bool applyingSpace; Button startBtn, bypassBtn;
    static readonly string[] spaceSliders = { "Reverb", "Reverb size", "Reverb tone", "Reverb pre-delay", "Reverb width" };
    EqView eqView; CheckBox advChk; Timer viewTimer; HoloDeck deck;
    readonly SpectrumAnalyzer analyzer = new SpectrumAnalyzer(128, AudioEngine.Rate); readonly float[] fftLeft = new float[SpectrumAnalyzer.Size], fftRight = new float[SpectrumAnalyzer.Size];
    bool ready, wantRun, waiting; bool stageEnabled = true, spaceEnabled = true, eqEnabled = true; int tries, autoFails; DateTime lastStart = DateTime.MinValue; string wantIn, wantOut, wantAnalysis;

    public MainWindow() {
        Text = "StageJack // Earnest"; StartPosition = FormStartPosition.CenterScreen; FormBorderStyle = FormBorderStyle.FixedSingle; ClientSize = new Size(1040, 680); MaximizeBox = false; MinimizeBox = true;
        MinimumSize = Size; MaximumSize = Size; BackColor = bg; ForeColor = white; Font = new Font("Segoe UI", 9);
        try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }
        trayIcon = new NotifyIcon { Icon = Icon ?? SystemIcons.Application, Text = "StageJack", Visible = false };
        ContextMenuStrip trayMenu = new ContextMenuStrip();
        trayMenu.Items.Add("Open StageJack", null, delegate { RestoreFromTray(); });
        trayMenu.Items.Add("Exit", null, delegate { Close(); });
        trayIcon.ContextMenuStrip = trayMenu;
        trayIcon.DoubleClick += delegate { RestoreFromTray(); };
        Resize += delegate { if (WindowState == FormWindowState.Minimized) MinimizeToTray(); };
        string dir = AppDomain.CurrentDomain.BaseDirectory; savePath = Path.Combine(dir, "earnest-settings.ini");
        try {
            fonts.AddFontFile(Path.Combine(dir, "Rajdhani-Regular.ttf")); fonts.AddFontFile(Path.Combine(dir, "Rajdhani-SemiBold.ttf"));
            regular = new Font(fonts.Families[0], 14); strong = new Font(fonts.Families[1], 15, FontStyle.Bold); display = new Font(fonts.Families[1], 27, FontStyle.Bold); small = new Font(fonts.Families[0], 10);
        } catch { regular = new Font("Segoe UI", 11); strong = new Font("Segoe UI Semibold", 11, FontStyle.Bold); display = new Font("Segoe UI Semibold", 19, FontStyle.Bold); small = new Font("Segoe UI", 8); }

        inBox = MakeCombo(0); outBox = MakeCombo(0); analysisBox = MakeCombo(0); spaceBox = MakeCombo(0);
        spaceBox.Items.Add("Union Stairs (Earnest)"); spaceBox.SelectedIndex = 0;
        advChk = new CheckBox();
        status = new Label { Text = "●  SYSTEM IDLE", ForeColor = muted };
        startBtn = MakeButton("START", 1, 1); bypassBtn = MakeButton("BYPASS: OFF", 1, 1);
        RegisterSlider("Reverb", 0, 100, 20); RegisterSlider("Stage width", 0, 100, 50); RegisterSlider("Stage depth", 0, 100, 0); RegisterSlider("Stage height", 0, 100, 50); RegisterSlider("Output level", -12, 6, 0);
        RegisterSlider("Reverb size", 0, 100, 75); RegisterSlider("Reverb tone", 0, 100, 60); RegisterSlider("Reverb pre-delay", 0, 60, 30); RegisterSlider("Reverb clarity", 0, 100, 50); RegisterSlider("Reverb width", 0, 100, 100); RegisterSlider("Smoothness", 0, 100, 60);
        foreach (string control in new [] { "Reverb", "Reverb size", "Reverb tone", "Reverb clarity", "Smoothness" }) { sliders[control].Maximum = 250; sliders[control].Value = 100; }
        sliders["Reverb size"].Minimum = 10;
        RegisterSlider("Decay", 10, 250, 100);
        RegisterSlider("Low", -12, 12, 0); RegisterSlider("Mid", -12, 12, 0); RegisterSlider("High", -12, 12, 0);
        foreach (string band in bands) RegisterSlider(band, -12, 12, 0);
        eqView = new EqView { Visible = false, Enabled = false, Size = new Size(1, 1), Font = small };
        eqView.NodeDrag += delegate(string name, int v) { StageSlider sl; if (sliders.TryGetValue(name, out sl)) sl.Value = v; };
        deck = new HoloDeck(this) { Dock = DockStyle.Fill }; Controls.Add(deck); deck.Controls.Add(eqView); deck.PositionEqView();
        var advancedMix = new Button { Text="ADVANCED MIX", Left=Width-210, Top=76, Width=155, Height=28, BackColor=Color.FromArgb(31,48,45), ForeColor=Color.White, FlatStyle=FlatStyle.Flat };
        AdvancedMix advancedWindow = null;
        foreach (var item in sliders) {
            StageSlider control = item.Value;
            control.ValueChanged += delegate { if (advancedWindow != null && !advancedWindow.IsDisposed) advancedWindow.SyncEngineControl(control.Name, control.Value); };
        }
        advancedMix.Click += delegate {
            if (advancedWindow == null || advancedWindow.IsDisposed) {
                advancedWindow = new AdvancedMix(key => sliders[key].Value, (key, value) => sliders[key].Value = value, null,
                    () => engine.RoomPath, path => { engine.SelectRoom(path); saveTimer.Stop(); saveTimer.Start(); });
                advancedWindow.Show(this);
            } else advancedWindow.BringToFront();
        };
        Controls.Add(advancedMix); advancedMix.BringToFront();

        saveTimer = new Timer { Interval = 500 }; saveTimer.Tick += delegate { saveTimer.Stop(); Save(); };
        pollTimer = new Timer { Interval = 500 }; pollTimer.Tick += delegate { Poll(); }; pollTimer.Start();
        viewTimer = new Timer { Interval = 33 }; viewTimer.Tick += delegate { UpdateSpectrum(); }; viewTimer.Start();
        pingTimer = new Timer { Interval = 3000 }; pingTimer.Tick += delegate { Ping(); };
        spaceBox.SelectedIndexChanged += delegate { if (ready) { PushParams(); deck.Invalidate(); } };
        advChk.CheckedChanged += delegate { ApplyAdvanced(); if (ready) { PushParams(); saveTimer.Stop(); saveTimer.Start(); } };

        string savedIn = null, savedOut = null, savedAnalysis = null;
        LoadSaved(out savedIn, out savedOut, out savedAnalysis); wantRun = false; savedIn = savedIn ?? "Speakers (Razer Kraken V3 X)"; savedOut = savedOut ?? "Speakers (7.1 Surround Sound)"; Populate(savedIn, savedOut, savedAnalysis);
        wantIn = savedIn ?? SelName(inBox); wantOut = savedOut ?? SelName(outBox);
        inBox.SelectedIndexChanged += delegate { if (ready) { wantIn = SelName(inBox); Restart(); Resolve(); saveTimer.Stop(); saveTimer.Start(); deck.Invalidate(); } };
        outBox.SelectedIndexChanged += delegate { if (ready) { wantOut = SelName(outBox); Restart(); Resolve(); saveTimer.Stop(); saveTimer.Start(); deck.Invalidate(); } };
        analysisBox.SelectedIndexChanged += delegate { if (ready) { wantAnalysis = SelectedAnalysisEndpointId(); engine.SetAnalysisEndpoint(wantAnalysis); saveTimer.Stop(); saveTimer.Start(); deck.Invalidate(); } };
        wantAnalysis = SelectedAnalysisEndpointId();
        ready = true; PushParams();
        // Keep the analyzer's Windows playback loopback alive independently of
        // StageJack's microphone processing route.
        engine.SetAnalysisEndpoint(wantAnalysis);
        if (Missing()) BeginWait(); else if (wantRun) Start();
        if (Array.IndexOf(Environment.GetCommandLineArgs(), "--start-earnest") >= 0)
            Shown += delegate { if (!engine.Running && !waiting) Toggle(); };
        FormClosing += delegate { saveTimer.Stop(); pollTimer.Stop(); viewTimer.Stop(); pingTimer.Stop(); engine.Shutdown(); Save(); trayIcon.Visible = false; if (trayIcon.ContextMenuStrip != null) trayIcon.ContextMenuStrip.Dispose(); trayIcon.Dispose(); };
    }

    void MinimizeToTray() { if (trayIcon == null) return; trayIcon.Visible = true; ShowInTaskbar = false; Hide(); }
    void RestoreFromTray() { if (trayIcon != null) trayIcon.Visible = false; ShowInTaskbar = true; WindowState = FormWindowState.Normal; Show(); Activate(); BringToFront(); }

    protected override void OnHandleCreated(EventArgs e) {
        base.OnHandleCreated(e); SyncNativeTitleBar();
    }
    protected override void WndProc(ref Message m) {
        base.WndProc(ref m);
        if (m.Msg == WM_SETTINGCHANGE || m.Msg == WM_THEMECHANGED || m.Msg == WM_DWMCOLORIZATIONCOLORCHANGED) SyncNativeTitleBar();
    }
    void SyncNativeTitleBar() {
        if (!IsHandleCreated || Environment.OSVersion.Platform != PlatformID.Win32NT) return;
        int light = 1;
        try {
            using (RegistryKey k = Registry.CurrentUser.OpenSubKey("Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize")) {
                object mode = k == null ? null : k.GetValue("AppsUseLightTheme");
                if (mode == null && k != null) mode = k.GetValue("SystemUsesLightTheme");
                if (mode != null) light = Convert.ToInt32(mode);
            }
            int dark = light == 0 ? 1 : 0;
            int hr = DwmSetWindowAttribute(Handle, DWMWA_USE_IMMERSIVE_DARK_MODE, ref dark, sizeof(int));
            if (hr != 0) DwmSetWindowAttribute(Handle, DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, ref dark, sizeof(int));
        } catch { }
    }

    void RegisterSlider(string name, int min, int max, int value) {
        StageSlider slider = new StageSlider { Minimum = min, Maximum = max, Value = value, Name = name, Visible = false, Size = new Size(1, 1) };
        sliders[name] = slider;
        slider.ValueChanged += delegate { if (!applyingSpace && spaceBox != null && spaceBox.SelectedIndex != 0 && Array.IndexOf(spaceSliders, name) >= 0) spaceBox.SelectedIndex = 0; if (ready) { PushParams(); saveTimer.Stop(); saveTimer.Start(); } if (deck != null) deck.Invalidate(); };
    }
    Button MakeButton(string text, int w, int h) {
        Button b = new Button { Text = text, FlatStyle = FlatStyle.Flat, ForeColor = accent, BackColor = Color.FromArgb(18, 31, 36), Font = strong, Size = new Size(w, h), TabStop = false, Cursor = Cursors.Hand };
        b.FlatAppearance.BorderColor = Color.FromArgb(85, accent); b.FlatAppearance.MouseOverBackColor = Color.FromArgb(28, 48, 55); b.FlatAppearance.BorderSize = 1; return b;
    }
    ComboBox MakeCombo(int y) {
        return new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, FlatStyle = FlatStyle.Flat, BackColor = Color.FromArgb(17, 23, 26), ForeColor = white, Font = regular, Width = 820, Location = new Point(18, y), Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right, TabStop = false };
    }

    void PushParams() {
        float[] eq = new float[bands.Length];
        for (int i = 0; i < eq.Length; i++) eq[i] = eqEnabled ? sliders[bands[i]].Value : 0;
        float width = stageEnabled ? sliders["Stage width"].Value : 50;
        float depth = stageEnabled ? sliders["Stage depth"].Value : 0;
        float height = stageEnabled ? sliders["Stage height"].Value : 50;
        float level = stageEnabled ? sliders["Output level"].Value : 0;
        float reverb = spaceEnabled ? sliders["Reverb"].Value : 0;
        float size = spaceEnabled ? sliders["Reverb size"].Value : 0;
        float tone = spaceEnabled ? sliders["Reverb tone"].Value : 0;
        float pre = spaceEnabled ? sliders["Reverb pre-delay"].Value : 0;
        float clarity = spaceEnabled ? sliders["Reverb clarity"].Value : 0;
        float reverbWidth = spaceEnabled ? sliders["Reverb width"].Value : 0;
        float smooth = spaceEnabled ? sliders["Smoothness"].Value : 0;
        float low = eqEnabled ? sliders["Low"].Value : 0;
        float mid = eqEnabled ? sliders["Mid"].Value : 0;
        float high = eqEnabled ? sliders["High"].Value : 0;
        engine.Dsp.Set(reverb, width, depth, height, level, size, tone, pre, clarity, reverbWidth, smooth, low, mid, high, eqEnabled && advChk.Checked, sliders["Decay"].Value, eq);
        RefreshEq();
    }
    bool SectionEnabled(int section) { return section == 0 ? stageEnabled : section == 1 ? spaceEnabled : eqEnabled; }
    void ToggleSection(int section) {
        if (section == 0) stageEnabled = !stageEnabled;
        else if (section == 1) spaceEnabled = !spaceEnabled;
        else eqEnabled = !eqEnabled;
        PushParams(); saveTimer.Stop(); saveTimer.Start(); if (deck != null) deck.Invalidate();
    }
    void ApplyAdvanced() {
        if (deck != null) deck.Invalidate();
    }
    // redraw the EQ curve and nodes from the current slider values
    void RefreshEq() {
        if (eqView == null) return;
        float[] bv = new float[bands.Length];
        for (int i = 0; i < bv.Length; i++) bv[i] = eqEnabled ? sliders[bands[i]].Value : 0;
        bool adv = eqEnabled && advChk.Checked;
        int stageHeight = stageEnabled ? sliders["Stage height"].Value : 50;
        float low = eqEnabled ? sliders["Low"].Value : 0, mid = eqEnabled ? sliders["Mid"].Value : 0, high = eqEnabled ? sliders["High"].Value : 0;
        eqView.SetCurve(EqModel.Curve(160, AudioEngine.Rate, low, mid, high, stageHeight, adv, bv));
        int n = adv ? 3 + bands.Length : 3;
        string[] names = new string[n]; float[] hz = new float[n], db = new float[n]; bool[] major = new bool[n];
        names[0] = "Low"; hz[0] = EqModel.LowHz; names[1] = "Mid"; hz[1] = EqModel.MidHz; names[2] = "High"; hz[2] = EqModel.HighHz;
        for (int i = 0; i < 3; i++) { db[i] = eqEnabled ? sliders[names[i]].Value : 0; major[i] = true; }
        if (adv) for (int i = 0; i < bands.Length; i++) { names[3 + i] = bands[i]; hz[3 + i] = Dsp.Freqs[i]; db[3 + i] = bv[i]; }
        eqView.SetNodes(names, hz, db, major);
    }
    void UpdateSpectrum() {
        if (eqView == null || deck == null || WindowState == FormWindowState.Minimized) return;
        bool live = engine.Running;
        engine.CopyRecentOutput(fftLeft, fftRight);
        float peak = Peak(fftLeft, fftRight);
        bool outputMonitor = true;
        // Always prefer the independently selected Windows render endpoint. The
        // processing thread may be stopped, restarting, or unavailable on a
        // surround/virtual route while the true device mix remains active.
        if (peak < 0.00001f && live) {
            engine.CopyRecentInput(fftLeft, fftRight); outputMonitor = false;
            peak = Peak(fftLeft, fftRight);
        }
        analyzer.Analyze(fftLeft, fftRight, peak < 0.00001f);
        eqView.SetSpectrum(analyzer.Level, outputMonitor);
    }
    static float Peak(float[] left, float[] right) {
        float peak = 0f;
        for (int i = 0; i < left.Length; i++) {
            float a = Math.Abs(left[i]), b = Math.Abs(right[i]);
            if (a > peak) peak = a; if (b > peak) peak = b;
        }
        return peak;
    }
    void ApplySpace(ReverbSpace sp) {
        applyingSpace = true;
        try {
            sliders["Reverb"].Value = sp.Wet; sliders["Reverb size"].Value = ReverbSpace.SizeFor(sp.T30); sliders["Reverb tone"].Value = sp.Tone;
            sliders["Reverb width"].Value = sp.Width; sliders["Reverb pre-delay"].Value = sp.Pre;
        } finally { applyingSpace = false; }
        PushParams();
    }
    void ResetAll() {
        applyingSpace = true;
        sliders["Reverb"].Value = 100; sliders["Stage width"].Value = 50; sliders["Stage depth"].Value = 0; sliders["Stage height"].Value = 50; sliders["Output level"].Value = 0;
        sliders["Reverb size"].Value = 100; sliders["Reverb tone"].Value = 100; sliders["Reverb pre-delay"].Value = 30; sliders["Reverb clarity"].Value = 100; sliders["Reverb width"].Value = 100; sliders["Smoothness"].Value = 100;
        sliders["Decay"].Value = 100;
        sliders["Low"].Value = 0; sliders["Mid"].Value = 0; sliders["High"].Value = 0;
        foreach (string b in bands) sliders[b].Value = 0;
        applyingSpace = false; spaceBox.SelectedIndex = 0; PushParams();
    }

    // ----- devices -----
    string SelName(ComboBox b) { Device d = b.SelectedItem as Device; return d == null ? null : d.Name; }
    string SelectedAnalysisEndpointId() { Device d = analysisBox == null ? null : analysisBox.SelectedItem as Device; return d == null || d.Id < 0 ? null : d.EndpointId; }
    static bool Has(string s, string part) { return s.IndexOf(part, StringComparison.OrdinalIgnoreCase) >= 0; }
    static bool IsVirtual(string n) { return Has(n, "cable") || Has(n, "virtual") || Has(n, "voicemeeter") || Has(n, "vb-audio"); }
    static string Key(string n) { int a = n.IndexOf('('); return a < 0 ? "" : n.Substring(a).ToLowerInvariant(); }

    void Populate(string wantIn, string wantOut) { Populate(wantIn, wantOut, wantAnalysis); }
    void Populate(string wantIn, string wantOut, string analysisEndpointId) {
        bool was = ready; ready = false;
        inBox.Items.Clear(); outBox.Items.Clear();
        foreach (Device d in Mme.Outputs()) inBox.Items.Add(d);
        foreach (Device d in Mme.Outputs()) outBox.Items.Add(d);
        inBox.SelectedIndex = Pick(inBox, wantIn, true);
        outBox.SelectedIndex = Pick(outBox, wantOut, false);
        analysisBox.Items.Clear();
        analysisBox.Items.Add(new Device { Id = -1, Name = "Windows Default Output", EndpointId = null });
        foreach (Device d in Mme.Outputs()) analysisBox.Items.Add(d);
        analysisBox.SelectedIndex = PickAnalysis(analysisBox, analysisEndpointId);
        wantAnalysis = SelectedAnalysisEndpointId();
        ready = was;
    }
    int PickAnalysis(ComboBox box, string endpointId) {
        if (endpointId != null) for (int i = 1; i < box.Items.Count; i++) if (((Device)box.Items[i]).EndpointId == endpointId) return i;
        return box.Items.Count > 0 ? 0 : -1;
    }
    int Pick(ComboBox box, string want, bool virt) {
        if (box.Items.Count == 0) return -1;
        if (want != null) for (int i = 0; i < box.Items.Count; i++) if (((Device)box.Items[i]).Name == want) return i;
        for (int i = 0; i < box.Items.Count; i++) { string n = ((Device)box.Items[i]).Name; if (virt ? Has(n, "cable output") : !IsVirtual(n)) return i; }
        for (int i = 0; i < box.Items.Count; i++) { string n = ((Device)box.Items[i]).Name; if (virt ? IsVirtual(n) : true) return i; }
        return 0;
    }

    // ----- engine control -----
    void Toggle() {
        if (engine.Running || waiting) { wantRun = false; waiting = false; pingTimer.Stop(); engine.Stop(); }
        else { wantRun = true; autoFails = 0; if (Missing()) BeginWait(); else Start(); }
        saveTimer.Stop(); saveTimer.Start(); Poll();
    }

    // ----- device "pings": recheck every few seconds (not continuously) until the saved devices show up -----
    static bool Present(ComboBox b, string name) { if (name == null) return false; foreach (object o in b.Items) if (((Device)o).Name == name) return true; return false; }
    static bool HasName(List<Device> l, string name) { if (name == null) return false; foreach (Device d in l) if (d.Name == name) return true; return false; }
    bool Missing() { return !Present(inBox, wantIn) || !Present(outBox, wantOut); }
    void BeginWait() { waiting = true; tries = 0; pingTimer.Interval = 3000; pingTimer.Start(); }
    void Resolve() { if (waiting && !Missing()) { waiting = false; pingTimer.Stop(); if (wantRun) Start(); } }
    void Ping() {
        if (!waiting) { pingTimer.Stop(); return; }
        tries++;
        if (HasName(Mme.Outputs(), wantIn) && HasName(Mme.Outputs(), wantOut)) {
            Populate(wantIn, wantOut); Resolve();
            return;
        }
        if (tries == 20) pingTimer.Interval = 10000;   // after ~1 minute, ping less often
    }
    void Restart() { if (engine.Running) Start(); }
    void Start() {
        Device di = inBox.SelectedItem as Device, dout = outBox.SelectedItem as Device;
        if (di == null || dout == null) { SetStatus("●  PICK AN INPUT AND OUTPUT", Color.OrangeRed); wantRun = false; return; }
        string k = Key(di.Name);
        if (di.Name == dout.Name || (k.Length > 0 && k == Key(dout.Name) && (Has(k, "virtual") || Has(k, "cable")))) { SetStatus("●  INPUT AND OUTPUT CAN'T BE THE SAME CABLE", Color.OrangeRed); wantRun = false; return; }
        lastStart = DateTime.UtcNow; engine.Start(di.Id, dout.Id, wantAnalysis);
    }
    void SetStatus(string text, Color c) { status.Text = text; status.ForeColor = c; if (deck != null) deck.Invalidate(); }
    void Poll() {
        string err = engine.Error;
        if (engine.Running) {
            SetStatus(err != null ? "●  ROOM CHANGE FAILED; PREVIOUS BRIDGE RUNNING: " + err : engine.Building ? "●  BUILDING EARNEST ROOM" : engine.Dsp.Bypass ? "●  RETURN MUTED" : "●  EARNEST RETURN RUNNING / EXPERIMENTAL", err != null ? Color.OrangeRed : accent); startBtn.Text = "STOP";
            if ((DateTime.UtcNow - lastStart).TotalSeconds > 10) autoFails = 0;
        }
        else if (waiting) {
            startBtn.Text = "STOP";
            SetStatus("●  WAITING FOR  " + (wantOut ?? "OUTPUT").ToUpperInvariant() + "  /  RECHECKING", Color.FromArgb(255, 176, 0));
        }
        else {
            startBtn.Text = "▶   START PROCESSING";
            if (err != null) {
                wantRun = false; SetStatus("●  " + err.ToUpperInvariant(), Color.OrangeRed);
            }
            else if (status.ForeColor != Color.OrangeRed) SetStatus("●  SYSTEM IDLE", muted);
        }
    }

    // ----- settings -----
    void LoadSaved(out string inName, out string outName, out string analysisEndpointId) {
        inName = null; outName = null; analysisEndpointId = null;
        if (!File.Exists(savePath)) return;
        applyingSpace = true;
        try {
            foreach (string line in File.ReadAllLines(savePath)) {
                int e = line.IndexOf('='); if (e <= 0) continue;
                string k = line.Substring(0, e), v = line.Substring(e + 1);
                if (k == "Input") inName = v; else if (k == "Output") outName = v; else if (k == "Analysis") analysisEndpointId = v == "default" ? null : v; else if (k == "Running") wantRun = v == "1";
                else if (k == "Advanced") advChk.Checked = v == "1";
                else if (k == "StageEnabled") stageEnabled = v != "0";
                else if (k == "SpaceEnabled") spaceEnabled = v != "0";
                else if (k == "EqEnabled") eqEnabled = v != "0";
                else if (k == "Room" && File.Exists(v)) engine.SelectRoom(v);
                else if (k == "Space") { int si; if (int.TryParse(v, out si) && si >= 0 && si < spaceBox.Items.Count) spaceBox.SelectedIndex = si; }
                else if (sliders.ContainsKey(k)) { int n; if (int.TryParse(v, out n)) sliders[k].Value = n; }
            }
        } catch { }
        applyingSpace = false;
    }
    void Save() {
        try {
            List<string> lines = new List<string>();
            foreach (KeyValuePair<string, StageSlider> kv in sliders) lines.Add(kv.Key + "=" + kv.Value.Value);
            if ((wantIn ?? SelName(inBox)) != null) lines.Add("Input=" + (wantIn ?? SelName(inBox)));
            if ((wantOut ?? SelName(outBox)) != null) lines.Add("Output=" + (wantOut ?? SelName(outBox)));
            lines.Add("Analysis=" + (wantAnalysis ?? "default"));
            lines.Add("Room=" + engine.RoomPath);
            lines.Add("Advanced=" + (advChk.Checked ? "1" : "0"));
            lines.Add("StageEnabled=" + (stageEnabled ? "1" : "0"));
            lines.Add("SpaceEnabled=" + (spaceEnabled ? "1" : "0"));
            lines.Add("EqEnabled=" + (eqEnabled ? "1" : "0"));
            lines.Add("Space=" + spaceBox.SelectedIndex);
            lines.Add("Running=" + (engine.Running || wantRun || waiting ? "1" : "0"));
            File.WriteAllLines(savePath, lines.ToArray());
        } catch { }
    }

    // One fixed-size widget surface. Existing controls remain the data model; this class only
    // presents them and routes pointer input back to their established handlers.
    sealed class HoloDeck : Control {
        readonly MainWindow app;
        int draggingBand = -1, dropdownOffset;
        string dragging, dropdown;
        Rectangle dropRect;
        readonly string[] stageSliders = { "Stage width", "Stage depth", "Stage height", "Output level" };
        readonly string[] spaceSliders = { "Reverb", "Reverb size", "Reverb tone", "Reverb pre-delay", "Reverb clarity", "Reverb width", "Smoothness" };
        public HoloDeck(MainWindow owner) {
            app = owner;
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
            BackColor = Color.FromArgb(9, 11, 11); Cursor = Cursors.Default; TabStop = true;
        }
        Color A { get { return app.accent; } }
        Color ElectricBlue { get { return Color.FromArgb(0, 190, 255); } }
        Color Hot { get { return Color.FromArgb(255, 46, 136); } }
        Color Ink { get { return Color.FromArgb(9, 11, 11); } }
        Color TextColor { get { return Color.FromArgb(232, 234, 231); } }
        protected override void OnPaint(PaintEventArgs e) {
            base.OnPaint(e); Graphics g = e.Graphics; g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
            g.Clear(Ink); DrawAtmosphere(g); DrawHeader(g); DrawWidget(g); if (dropdown != null) DrawDropdown(g);
        }
        protected override void OnResize(EventArgs e) { base.OnResize(e); PositionEqView(); Invalidate(); }
        public void PositionEqView() {
            if (app.eqView == null) return;
            app.eqView.Bounds = EqGraphBounds;
            app.eqView.Visible = true;
            if (app.eqView.Parent == this) app.eqView.BringToFront();
        }
        void DrawAtmosphere(Graphics g) {
            // The backdrop grid stays deliberately faint so it reads as texture, not content.
            using (Pen grid = new Pen(Color.FromArgb(5, 112, 132, 126), 1)) {
                for (int x = 0; x < Width; x += 56) g.DrawLine(grid, x, 0, x, Height);
                for (int y = 0; y < Height; y += 56) g.DrawLine(grid, 0, y, Width, y);
            }
            using (Pen frame = new Pen(Color.FromArgb(105, 105, 101), 1)) {
                Point[] p = { new Point(16, 20), new Point(Width - 34, 20), new Point(Width - 16, 38), new Point(Width - 16, Height - 20), new Point(34, Height - 20), new Point(16, Height - 38), new Point(16, 20) };
                g.DrawLines(frame, p);
            }
            using (Pen p = new Pen(A, 2)) g.DrawLine(p, 16, 20, 92, 20);
            using (Pen p = new Pen(Hot, 2)) g.DrawLine(p, Width - 94, Height - 20, Width - 34, Height - 20);
        }
        void DrawHeader(Graphics g) {
            DrawText(g, "STAGEJACK", app.display, TextColor, 38, 28);
            using (Pen p = new Pen(Hot, 2)) g.DrawLine(p, 40, 61, 112, 61);
            DrawText(g, "SPATIAL AUDIO  /  PERSONAL SIGNAL MATRIX", app.small, Color.FromArgb(144, 148, 143), 42, 66);
            Rectangle state = new Rectangle(Width - 318, 28, 202, 38);
            DrawFrame(g, state, app.status.ForeColor);
            DrawText(g, Clip(app.status.Text, 30), app.small, app.status.ForeColor, state.X + 9, state.Y + 11);
            DrawButton(g, new Rectangle(Width - 103, 28, 70, 38), "RESET", true);
        }
        void DrawWidget(Graphics g) {
            Rectangle area = Workspace;
            DrawFrame(g, area, Color.FromArgb(93, 88, 83));
            DrawRoute(g, RouteBounds);
            Rectangle[] panels = PanelBounds;
            DrawPanel(g, panels[0], 0, "01  /  SPATIAL STAGE", "POSITION  /  WIDTH  /  OUTPUT");
            DrawPanel(g, panels[1], 1, "02  /  REFLECTION FIELD", "ROOM RESPONSE  /  TONE");
            DrawPanel(g, panels[2], 2, "03  /  SPECTRAL SHAPER", "LIVE ANALYSIS  /  EQUALIZATION");
            DrawStage(g, panels[0]); DrawSpace(g, panels[1]); DrawEq(g, panels[2]);
        }
        void DrawPanel(Graphics g, Rectangle r, int section, string title, string sub) {
            bool enabled = app.SectionEnabled(section);
            using (SolidBrush fill = new SolidBrush(Color.FromArgb(190, 17, 19, 19))) g.FillRectangle(fill, r);
            DrawFrame(g, r, Color.FromArgb(76, 91, 86));
            DrawText(g, title, app.strong, TextColor, r.X + 13, r.Y + 9);
            DrawText(g, enabled ? sub : "OFF  /  VALUES STORED", app.small, enabled ? Color.FromArgb(116, 127, 121) : Color.FromArgb(138, 144, 141), r.X + 14, r.Y + 29);
            DrawPowerButton(g, PowerBounds(section), enabled);
            if (section == 2) DrawAnalysisPicker(g, AnalysisPickerBounds);
            using (Pen p = new Pen(Color.FromArgb(54, A), 1)) g.DrawLine(p, r.X + 13, r.Y + 43, r.Right - 13, r.Y + 43);
        }
        void DrawPowerButton(Graphics g, Rectangle r, bool enabled) {
            Color c = enabled ? ElectricBlue : Color.FromArgb(113, 119, 116);
            using (SolidBrush fill = new SolidBrush(Color.FromArgb(enabled ? 24 : 12, c))) g.FillRectangle(fill, r);
            DrawFrame(g, r, c);
            using (Pen p = new Pen(c, 1.8f)) {
                p.StartCap = System.Drawing.Drawing2D.LineCap.Round; p.EndCap = System.Drawing.Drawing2D.LineCap.Round;
                g.DrawArc(p, r.X + 6, r.Y + 6, r.Width - 12, r.Height - 12, 45, 290);
                g.DrawLine(p, r.X + r.Width / 2, r.Y + 4, r.X + r.Width / 2, r.Y + r.Height / 2 + 1);
            }
        }
        void DrawAnalysisPicker(Graphics g, Rectangle r) {
            using (SolidBrush fill = new SolidBrush(Color.FromArgb(24, 0, 190, 255))) g.FillRectangle(fill, r);
            DrawFrame(g, r, ElectricBlue);
            DrawText(g, "ANALYSIS NOT WIRED", app.small, ElectricBlue, r.X + 7, r.Y + 2);
            Device d = app.analysisBox.SelectedItem as Device;
            string selected = d == null ? "NO DEVICE" : (d.Id < 0 ? "SYSTEM DEFAULT" : d.Name);
            DrawText(g, Clip(selected, Math.Max(7, (r.Width - 22) / 6)), app.small, TextColor, r.X + 7, r.Y + 16);
            DrawTextRight(g, "▾", app.small, ElectricBlue, r.Right - 6, r.Y + 16);
        }
        void DrawRoute(Graphics g, Rectangle r) {
            using (SolidBrush fill = new SolidBrush(Color.FromArgb(195, 18, 20, 20))) g.FillRectangle(fill, r);
            DrawFrame(g, r, Color.FromArgb(91, 89, 82));
            Rectangle[] q = RouteControls;
            DrawDevice(g, q[0], "PLAYBACK TAP", app.inBox, "input");
            DrawDevice(g, q[1], "AUDIO OUTPUT", app.outBox, "output");
            DrawButton(g, q[2], app.engine.Running || app.waiting ? "STOP" : "START", true);
            DrawButton(g, q[3], app.engine.Dsp.Bypass ? "BYPASS: ON" : "BYPASS: OFF", false);
            DrawButton(g, q[4], "RESCAN", false);
        }
        void DrawDevice(Graphics g, Rectangle r, string label, ComboBox box, string id) {
            using (SolidBrush fill = new SolidBrush(Color.FromArgb(25, A))) g.FillRectangle(fill, r);
            DrawFrame(g, r, Color.FromArgb(85, Hot));
            DrawText(g, label, app.small, ElectricBlue, r.X + 10, r.Y + 5);
            string selected = box.SelectedItem == null ? "NO DEVICE FOUND" : ((Device)box.SelectedItem).Name;
            DrawText(g, Clip(selected, Math.Max(12, (r.Width - 94) / 7)), app.strong, TextColor, r.X + 10, r.Y + 22);
            DrawTextRight(g, "▾", app.small, ElectricBlue, r.Right - 9, r.Y + 25);
            if (dropdown == id) dropRect = new Rectangle(r.X, r.Bottom, r.Width, 30 * Math.Min(8, box.Items.Count));
        }
        void DrawStage(Graphics g, Rectangle r) {
            int x = r.X + 12, w = r.Width - 24, y = r.Y + 49;
            Rectangle[] sliders = new Rectangle[stageSliders.Length];
            for (int i = 0; i < stageSliders.Length; i++) {
                sliders[i] = new Rectangle(x, y + i * 53, w, 48); DrawSlider(g, stageSliders[i], sliders[i]);
            }
            Rectangle field = new Rectangle(x, y + stageSliders.Length * 53 + 4, w, Math.Max(42, r.Bottom - (y + stageSliders.Length * 53 + 14)));
            DrawText(g, "STEREO FIELD  /  MID–SIDE", app.small, Color.FromArgb(115, 153, 162), field.X + 2, field.Y - 1);
            DrawField(g, new Rectangle(field.X, field.Y + 14, field.Width, Math.Max(25, field.Height - 14)), app.sliders["Stage width"].Value, app.sliders["Stage depth"].Value, app.sliders["Stage height"].Value);
        }
        void DrawSpace(Graphics g, Rectangle r) {
            Rectangle preset = SpacePresetBounds;
            DrawFrame(g, preset, Color.FromArgb(90, 87, 81));
            DrawText(g, "SPACE PRESET", app.small, Color.FromArgb(113, 151, 161), preset.X + 10, preset.Y + 3);
            string selected = app.spaceBox.SelectedItem == null ? "CUSTOM" : app.spaceBox.SelectedItem.ToString().ToUpperInvariant();
            DrawText(g, Clip(selected + "   ▾", Math.Max(12, (preset.Width - 20) / 8)), app.strong, TextColor, preset.X + 10, preset.Y + 17);
            Rectangle[] cards = SpaceSliderBounds;
            for (int i = 0; i < spaceSliders.Length; i++) DrawSlider(g, spaceSliders[i], cards[i]);
        }
        void DrawEq(Graphics g, Rectangle r) {
            Rectangle advanced = AdvancedBounds;
            DrawButton(g, advanced, "REFLECTION EQ  /  125-8K", true);
            for (int i = 0; i < BandBounds.Length; i++) DrawBand(g, i, BandBounds[i]);
        }
        void DrawSlider(Graphics g, string name, Rectangle r) {
            DrawFrame(g, r, Color.FromArgb(61, 78, 74));
            StageSlider s = app.sliders[name]; int inset = r.Width < 150 ? 8 : 11;
            bool available = name == "Stage width" || name == "Reverb" || name == "Reverb size" || name == "Reverb tone" || name == "Reverb clarity" || name == "Smoothness";
            if (!available) { DrawText(g, Clip(SliderLabel(name) + " / NOT WIRED", Math.Max(7, (r.Width - 20) / 7)), app.small, Color.FromArgb(110, 120, 115), r.X + inset, r.Y + 5); return; }
            string unit = "%";
            int labelLimit = Math.Max(7, (r.Width - 65) / 7);
            DrawText(g, Clip(SliderLabel(name), labelLimit), app.small, Color.FromArgb(217, 217, 209), r.X + inset, r.Y + 5);
            DrawTextRight(g, s.Value.ToString() + unit, app.small, A, r.Right - inset, r.Y + 5);
            int lx = r.X + 13, rx = r.Right - 13, ty = r.Bottom - 13;
            int knob = lx + (int)((rx - lx) * (s.Value - s.Minimum) / (float)(s.Maximum - s.Minimum));
            using (Pen p = new Pen(Color.FromArgb(54, 73, 73), 2)) g.DrawLine(p, lx, ty, rx, ty);
            using (Pen p = new Pen(Color.FromArgb(95, A), 2)) g.DrawLine(p, lx, ty, knob, ty);
            using (Pen tick = new Pen(Color.FromArgb(48, 99, 102), 1)) for (int i = 0; i <= 16; i++) { int x = lx + (rx - lx) * i / 16; g.DrawLine(tick, x, ty - 3, x, ty + 3); }
            using (SolidBrush glow = new SolidBrush(Color.FromArgb(38, Hot))) using (SolidBrush core = new SolidBrush(Hot)) { g.FillEllipse(glow, knob - 10, ty - 10, 20, 20); g.FillEllipse(core, knob - 3, ty - 3, 6, 6); }
        }
        void DrawField(Graphics g, Rectangle r, int width, int depth, int height) {
            DrawFrame(g, r, Color.FromArgb(50, A)); int center = r.X + r.Width / 2, spread = (int)(r.Width * (width / 100.0) * .42);
            using (Pen p = new Pen(Color.FromArgb(78, A), 1)) { g.DrawLine(p, center, r.Y + 3, center - spread, r.Bottom - 3); g.DrawLine(p, center, r.Y + 3, center + spread, r.Bottom - 3); g.DrawLine(p, r.X + 4, r.Bottom - 4, r.Right - 4, r.Bottom - 4); }
            DrawText(g, "WIDTH " + width + "     DEPTH " + depth + "     HEIGHT " + height, app.small, Color.FromArgb(125, 170, 180), r.X + 8, r.Y + 6);
        }
        void DrawBand(Graphics g, int index, Rectangle r) {
            if (index < 2 || index > 8) { DrawFrame(g, r, Color.FromArgb(48, A)); DrawCentered(g, bands[index], app.small, Color.FromArgb(95, 100, 100), r.X + r.Width / 2, r.Y + 9); DrawCentered(g, "N/A", app.small, Color.FromArgb(95, 100, 100), r.X + r.Width / 2, r.Y + r.Height / 2); return; }
            DrawFrame(g, r, Color.FromArgb(48, A)); int val = app.sliders[bands[index]].Value;
            DrawCentered(g, bands[index], app.small, Color.FromArgb(151, 182, 188), r.X + r.Width / 2, r.Y + 9);
            int mid = r.Y + r.Height / 2, h = Math.Abs(val) * 2;
            using (Pen p = new Pen(Color.FromArgb(55, 93, 102), 1)) g.DrawLine(p, r.X + r.Width / 2, r.Y + 24, r.X + r.Width / 2, r.Bottom - 8);
            using (SolidBrush b = new SolidBrush(A)) g.FillRectangle(b, r.X + 4, val >= 0 ? mid - h : mid, r.Width - 8, Math.Max(2, h));
            DrawCentered(g, val.ToString("+0;-0;0"), app.small, TextColor, r.X + r.Width / 2, r.Bottom - 11);
        }
        void DrawDropdown(Graphics g) {
            ComboBox box = DropdownBox(dropdown);
            if (box == null || box.Items.Count == 0) return;
            int n = Math.Min(8, box.Items.Count); dropRect.Height = n * 30;
            using (SolidBrush b = new SolidBrush(Color.FromArgb(246, 12, 18, 19))) g.FillRectangle(b, dropRect);
            DrawFrame(g, dropRect, A);
            int first = Math.Max(0, Math.Min(dropdownOffset, box.Items.Count - n));
            for (int i = 0; i < n; i++) {
                int item = first + i; Rectangle rr = new Rectangle(dropRect.X + 1, dropRect.Y + i * 30, dropRect.Width - 2, 30);
                if (item == box.SelectedIndex) using (SolidBrush hi = new SolidBrush(Color.FromArgb(32, A))) g.FillRectangle(hi, rr);
                string label = box.Items[item] is Device ? ((Device)box.Items[item]).Name : box.Items[item].ToString();
                DrawText(g, Clip(label, Math.Max(16, dropRect.Width / 8)), app.small, item == box.SelectedIndex ? A : TextColor, rr.X + 10, rr.Y + 8);
            }
        }
        ComboBox DropdownBox(string id) {
            if (id == "input") return app.inBox;
            if (id == "output") return app.outBox;
            if (id == "analysis") return app.analysisBox;
            return app.spaceBox;
        }
        void DrawFrame(Graphics g, Rectangle r, Color color) {
            if (r.Width < 8 || r.Height < 8) return;
            using (Pen p = new Pen(color, 1)) { int c = Math.Min(10, Math.Min(r.Width / 4, r.Height / 4)); Point[] pts = { new Point(r.X + c, r.Y), new Point(r.Right - c, r.Y), new Point(r.Right, r.Y + c), new Point(r.Right, r.Bottom - c), new Point(r.Right - c, r.Bottom), new Point(r.X + c, r.Bottom), new Point(r.X, r.Bottom - c), new Point(r.X, r.Y + c), new Point(r.X + c, r.Y) }; g.DrawLines(p, pts); }
        }
        void DrawButton(Graphics g, Rectangle r, string label, bool primary) {
            Color c = primary ? Color.FromArgb(40, 255, 46, 136) : Color.FromArgb(22, 29, 29);
            using (SolidBrush b = new SolidBrush(c)) g.FillRectangle(b, r);
            DrawFrame(g, r, primary ? Hot : Color.FromArgb(77, 88, 84));
            DrawCentered(g, Clip(label.ToUpperInvariant(), Math.Max(5, r.Width / 8)), app.small, primary ? TextColor : Color.FromArgb(196, 197, 190), r.X + r.Width / 2, r.Y + r.Height / 2);
        }
        void DrawText(Graphics g, string s, Font f, Color c, int x, int y) { using (SolidBrush b = new SolidBrush(c)) g.DrawString(s, f, b, x, y); }
        void DrawCentered(Graphics g, string s, Font f, Color c, int x, int y) { SizeF z = g.MeasureString(s, f); DrawText(g, s, f, c, x - (int)z.Width / 2, y - (int)z.Height / 2); }
        void DrawTextRight(Graphics g, string s, Font f, Color c, int x, int y) { SizeF z = g.MeasureString(s, f); DrawText(g, s, f, c, x - (int)z.Width, y); }
        string Clip(string s, int max) { if (s == null) return ""; if (max < 4) max = 4; return s.Length <= max ? s : s.Substring(0, max - 1) + "…"; }
        string SliderLabel(string name) {
            if (name == "Reverb") return "WET LEVEL";
            if (name == "Reverb size") return "TAIL";
            if (name == "Reverb tone") return "ABSORPTION";
            if (name == "Reverb pre-delay") return "PRE-DELAY";
            if (name == "Reverb clarity") return "SCATTER";
            if (name == "Reverb width" || name == "Stage width") return "WIDTH";
            if (name == "Stage depth") return "DEPTH";
            if (name == "Stage height") return "HEIGHT";
            if (name == "Output level") return "OUTPUT";
            if (name == "Smoothness") return "DIFFUSION";
            return name.ToUpperInvariant();
        }
        Rectangle Workspace { get { return new Rectangle(24, 112, Math.Max(0, Width - 48), Math.Max(0, Height - 136)); } }
        Rectangle RouteBounds { get { Rectangle a = Workspace; return new Rectangle(a.X + 8, a.Y + 8, a.Width - 16, 88); } }
        Rectangle[] PanelBounds {
            get {
                Rectangle a = Workspace; int x = a.X + 8, y = a.Y + 110, w = a.Width - 16, h = a.Height - 118, gap = 12;
                int usable = w - gap * 2, stage = usable * 25 / 100, space = usable * 31 / 100, eq = usable - stage - space;
                return new Rectangle[] { new Rectangle(x, y, stage, h), new Rectangle(x + stage + gap, y, space, h), new Rectangle(x + stage + gap + space + gap, y, eq, h) };
            }
        }
        Rectangle PowerBounds(int section) { Rectangle r = PanelBounds[section]; return new Rectangle(r.Right - 39, r.Y + 7, 27, 27); }
        Rectangle[] RouteControls {
            get {
                Rectangle a = RouteBounds; int y = a.Y + 17, h = 54, x = a.X + 12, deviceW = 282, gap = 8;
                Rectangle input = new Rectangle(x, y, deviceW, h); x += deviceW + gap;
                Rectangle output = new Rectangle(x, y, deviceW, h); x += deviceW + 14;
                Rectangle start = new Rectangle(x, y, 100, h); x += 108;
                Rectangle bypass = new Rectangle(x, y, 94, h); x += 102;
                Rectangle rescan = new Rectangle(x, y, Math.Max(70, a.Right - 12 - x), h);
                return new Rectangle[] { input, output, start, bypass, rescan };
            }
        }
        Rectangle SpacePresetBounds { get { Rectangle r = PanelBounds[1]; return new Rectangle(r.X + 12, r.Y + 49, r.Width - 24, 38); } }
        Rectangle AnalysisPickerBounds { get { Rectangle r = PanelBounds[2]; return new Rectangle(r.Right - 157, r.Y + 5, 111, 36); } }
        Rectangle[] SpaceSliderBounds {
            get {
                Rectangle r = PanelBounds[1]; int x = r.X + 12, y = r.Y + 96, gapX = 8, gapY = 8, w = (r.Width - 24 - gapX) / 2, h = 64;
                Rectangle[] q = new Rectangle[spaceSliders.Length];
                for (int i = 0; i < q.Length; i++) q[i] = new Rectangle(x + (i % 2) * (w + gapX), y + (i / 2) * (h + gapY), w, h);
                return q;
            }
        }
        Rectangle EqGraphBounds { get { Rectangle r = PanelBounds[2]; return new Rectangle(r.X + 12, r.Y + 49, r.Width - 24, 215); } }
        Rectangle AdvancedBounds { get { Rectangle r = PanelBounds[2]; return new Rectangle(r.X + 12, r.Y + 276, r.Width - 24, 30); } }
        Rectangle[] BandBounds {
            get {
                Rectangle r = PanelBounds[2]; int x = r.X + 12, y = r.Y + 314, gap = 3, usable = r.Width - 24, w = (usable - gap * 9) / 10, h = r.Bottom - 12 - y;
                if (h < 40) h = 40;
                Rectangle[] q = new Rectangle[bands.Length];
                for (int i = 0; i < q.Length; i++) q[i] = new Rectangle(x + i * (w + gap), y, w, h);
                return q;
            }
        }
        Rectangle SliderBounds(string name) {
            int i = Array.IndexOf(stageSliders, name); if (i >= 0) { Rectangle r = PanelBounds[0]; return new Rectangle(r.X + 12, r.Y + 49 + i * 53, r.Width - 24, 48); }
            i = Array.IndexOf(spaceSliders, name); if (i >= 0) return SpaceSliderBounds[i];
            return Rectangle.Empty;
        }
        protected override void OnMouseDown(MouseEventArgs e) {
            base.OnMouseDown(e); Focus(); Point p = e.Location;
            if (dropdown != null) {
                ComboBox box = DropdownBox(dropdown);
                if (dropRect.Contains(p)) { int i = (p.Y - dropRect.Y) / 30 + dropdownOffset; if (i >= 0 && i < box.Items.Count) box.SelectedIndex = i; }
                dropdown = null; app.eqView.Visible = true; Invalidate(); return;
            }
            if (p.X > Width - 115 && p.Y < 82) { app.ResetAll(); Invalidate(); return; }
            if (AnalysisPickerBounds.Contains(p)) return;
            Rectangle[] route = RouteControls;
            if (route[0].Contains(p)) { dropdown = "input"; dropdownOffset = 0; dropRect = new Rectangle(route[0].X, route[0].Bottom, route[0].Width, 30); Invalidate(); return; }
            if (route[1].Contains(p)) { dropdown = "output"; dropdownOffset = 0; dropRect = new Rectangle(route[1].X, route[1].Bottom, route[1].Width, 30); Invalidate(); return; }
            if (route[2].Contains(p)) { app.Toggle(); Invalidate(); return; }
            if (route[3].Contains(p)) { app.engine.Dsp.Bypass = !app.engine.Dsp.Bypass; app.bypassBtn.Text = app.engine.Dsp.Bypass ? "BYPASS / ON" : "BYPASS / OFF"; Invalidate(); return; }
            if (route[4].Contains(p)) { app.Populate(app.wantIn ?? app.SelName(app.inBox), app.wantOut ?? app.SelName(app.outBox)); app.Resolve(); Invalidate(); return; }
            if (PowerBounds(0).Contains(p)) { app.ToggleSection(0); return; }
            if (PowerBounds(1).Contains(p)) { app.ToggleSection(1); return; }
            if (SpacePresetBounds.Contains(p)) { Rectangle r = SpacePresetBounds; dropdown = "space"; dropdownOffset = 0; dropRect = new Rectangle(r.X, r.Bottom, r.Width, 30); Invalidate(); return; }
            Rectangle[] bandsNow = BandBounds;
            for (int i = 2; i <= 8; i++) if (bandsNow[i].Contains(p)) { draggingBand = i; SetBand(p, bandsNow[i], i); return; }
            string hit = FindSlider(p); if (hit != null) { dragging = hit; SetSlider(p.X, hit); Invalidate(); }
        }
        string FindSlider(Point p) {
            if (SliderBounds("Stage width").Contains(p)) return "Stage width";
            foreach (string name in spaceSliders) if ((name == "Reverb" || name == "Reverb size" || name == "Reverb tone" || name == "Reverb clarity" || name == "Smoothness") && SliderBounds(name).Contains(p)) return name;
            return null;
        }
        void SetSlider(int x, string name) { Rectangle r = SliderBounds(name); StageSlider s = app.sliders[name]; int left = r.X + 13, right = r.Right - 13; float t = Math.Max(0, Math.Min(1, (x - left) / (float)Math.Max(1, right - left))); s.Value = s.Minimum + (int)Math.Round(t * (s.Maximum - s.Minimum)); }
        void SetBand(Point p, Rectangle band, int index) { int top = band.Y + 18, bottom = band.Bottom - 12; float t = Math.Max(0, Math.Min(1, 1f - (p.Y - top) / (float)Math.Max(1, bottom - top))); app.sliders[bands[index]].Value = (int)Math.Round(-12 + t * 24); Invalidate(); }
        protected override void OnMouseMove(MouseEventArgs e) {
            base.OnMouseMove(e); Point p = e.Location;
            if (dragging != null) SetSlider(p.X, dragging);
            if (draggingBand >= 0) SetBand(p, BandBounds[draggingBand], draggingBand);
        }
        protected override void OnMouseWheel(MouseEventArgs e) {
            base.OnMouseWheel(e);
            if (dropdown == null) return;
            ComboBox box = DropdownBox(dropdown);
            int visible = Math.Min(8, box.Items.Count), max = Math.Max(0, box.Items.Count - visible);
            dropdownOffset = Math.Max(0, Math.Min(max, dropdownOffset + (e.Delta < 0 ? 1 : -1)));
            Invalidate();
        }
        protected override void OnMouseUp(MouseEventArgs e) { base.OnMouseUp(e); dragging = null; draggingBand = -1; }
        protected override void OnKeyDown(KeyEventArgs e) { base.OnKeyDown(e); if (dropdown != null && (e.KeyCode == Keys.Escape || e.KeyCode == Keys.Enter)) { dropdown = null; app.eqView.Visible = true; Invalidate(); } }
    }
}
