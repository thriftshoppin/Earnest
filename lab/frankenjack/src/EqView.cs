using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

// ---------- Spectrum analyzer: FFT of the real output, mapped to log-spaced columns ----------
public sealed class SpectrumAnalyzer {
    public const int Size = 2048;
    public float FloorDb = -96f, CeilDb = -22f;     // display range (after the +3 dB/octave tilt); open enough to show real program material
    public readonly float[] Level;                  // 0..1 per column, smoothed
    readonly int cols; readonly float fs;
    readonly float[] win = new float[Size], reL = new float[Size], imL = new float[Size], reR = new float[Size], imR = new float[Size], db = new float[Size / 2 + 1];
    readonly float[] cosT = new float[Size / 2], sinT = new float[Size / 2]; readonly int[] rev = new int[Size];

    public SpectrumAnalyzer(int columns, float rate) {
        cols = columns; fs = rate; Level = new float[columns];
        for (int i = 0; i < Size; i++) win[i] = (float)(0.5 - 0.5 * Math.Cos(2 * Math.PI * i / (Size - 1)));
        for (int i = 0; i < Size / 2; i++) { cosT[i] = (float)Math.Cos(2 * Math.PI * i / Size); sinT[i] = (float)Math.Sin(2 * Math.PI * i / Size); }
        int bits = 0; while ((1 << bits) < Size) bits++;
        for (int i = 0; i < Size; i++) { int r = 0; for (int b = 0; b < bits; b++) if ((i & (1 << b)) != 0) r |= 1 << (bits - 1 - b); rev[i] = r; }
    }

    void Fft(float[] re, float[] im) {
        for (int i = 0; i < Size; i++) { int j = rev[i]; if (j > i) { float t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; } }
        for (int len = 2; len <= Size; len <<= 1) {
            int half = len >> 1, step = Size / len;
            for (int i = 0; i < Size; i += len) {
                for (int k = 0; k < half; k++) {
                    float wr = cosT[k * step], wi = -sinT[k * step]; int a = i + k, b = a + half;
                    float tr = re[b] * wr - im[b] * wi, ti = re[b] * wi + im[b] * wr;
                    re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
                }
            }
        }
    }

    // samples: Size mono samples (-1..1). silent = true lets the display fall to zero.
    public void Analyze(float[] samples, bool silent) {
        Analyze(samples, samples, silent);
    }

    // Analyze both channels independently, then combine their power. A mono downmix can
    // cancel nearly to silence on wide or phase-inverted stereo material.
    public void Analyze(float[] left, float[] right, bool silent) {
        int half = Size / 2;
        if (!silent) {
            for (int i = 0; i < Size; i++) { reL[i] = left[i] * win[i]; imL[i] = 0f; reR[i] = right[i] * win[i]; imR[i] = 0f; }
            Fft(reL, imL); Fft(reR, imR);
            for (int i = 0; i <= half; i++) {
                float magL = reL[i] * reL[i] + imL[i] * imL[i];
                float magR = reR[i] * reR[i] + imR[i] * imR[i];
                float mag = (float)Math.Sqrt((magL + magR) * 0.5f) * (4f / Size);
                float v = 20f * (float)Math.Log10(mag + 1e-9f);
                if (i > 0) { double f = i * fs / Size; v += 3f * (float)(Math.Log(f / 1000.0) / Math.Log(2.0)); }   // pink-noise tilt
                db[i] = v;
            }
        }
        for (int c = 0; c < cols; c++) {
            float n = 0f;
            if (!silent) {
                double fLo = 20.0 * Math.Pow(1000.0, c / (double)cols), fHi = 20.0 * Math.Pow(1000.0, (c + 1) / (double)cols);
                double bLo = fLo * Size / fs, bHi = fHi * Size / fs; float v;
                if (bHi - bLo < 1.0) {
                    double bc = (bLo + bHi) * 0.5; int i0 = Math.Min((int)bc, half - 1); float fr = (float)(bc - i0);
                    v = db[i0] * (1f - fr) + db[i0 + 1] * fr;
                } else {
                    int i0 = (int)Math.Ceiling(bLo), i1 = Math.Min((int)Math.Floor(bHi), half); v = -200f;
                    for (int i = i0; i <= i1; i++) if (db[i] > v) v = db[i];
                }
                n = (v - FloorDb) / (CeilDb - FloorDb); if (n < 0f) n = 0f; if (n > 1f) n = 1f;
            }
            Level[c] += (n > Level[c] ? 0.60f : 0.14f) * (n - Level[c]);
            if (Level[c] < 0.001f) Level[c] = 0f;
        }
    }
}

// ---------- Visual EQ: live spectrum, EQ curve, draggable nodes ----------
public sealed class EqView : Control {
    public event Action<string, int> NodeDrag;      // (slider name, new dB value)
    const float DbRange = 15f;                      // vertical half-range of the curve
    float[] spec, curve; string[] names; float[] hz, nodeDb; bool[] major; bool outputMonitor = true;
    int drag = -1, hover = -1; string selectedName = "Low";

    public EqView() {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        BackColor = Color.FromArgb(14, 17, 17); TabStop = false;
    }

    public void SetSpectrum(float[] levels, bool fromOutput) { spec = levels; outputMonitor = fromOutput; Invalidate(); }
    public void SetCurve(float[] c) { curve = c; Invalidate(); }
    public void SetNodes(string[] n, float[] f, float[] d, bool[] m) {
        names = n; hz = f; nodeDb = d; major = m;
        if (names == null || names.Length == 0) selectedName = null;
        else if (Array.IndexOf(names, selectedName) < 0) selectedName = names[0];
        Invalidate();
    }

    const int Pad = 8;
    float XOf(float f) { double t = Math.Log(f / 20.0) / Math.Log(1000.0); return Pad + (float)(t * (Width - 2 * Pad)); }
    float PlotTop { get { return 34f; } }
    float PlotBottom { get { return Math.Max(PlotTop + 1f, Height - 22f); } }
    float YOf(float d) { float half = Math.Max(1f, (PlotBottom - PlotTop) * 0.5f - 2f); return (PlotTop + PlotBottom) * 0.5f - d / DbRange * half; }
    float DbOf(float y) { float half = Math.Max(1f, (PlotBottom - PlotTop) * 0.5f - 2f); return ((PlotTop + PlotBottom) * 0.5f - y) / half * DbRange; }
    Rectangle BandChipBounds(int index) {
        int gap = 5, margin = 7, y = 5, h = 23, statusSpace = 88, usable = Math.Max(3, Width - margin * 2 - gap * 2 - statusSpace), w = usable / 3;
        return new Rectangle(margin + index * (w + gap), y, w, h);
    }

    protected override void OnPaint(PaintEventArgs e) {
        base.OnPaint(e); Graphics g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
        Color acc = Theme.Accent; int w = Width, h = Height;
        using (LinearGradientBrush bgb = new LinearGradientBrush(new Rectangle(0, 0, w, h), Color.FromArgb(20, 24, 23), BackColor, LinearGradientMode.Vertical)) g.FillRectangle(bgb, 0, 0, w, h);

        // The live spectrum is the base surface. Keep the reference grid soft and secondary.
        using (Pen grid = new Pen(Color.FromArgb(20, 92, 103, 98), 1f))
        using (Pen zero = new Pen(Color.FromArgb(60, 151, 158, 151), 1f))
        using (SolidBrush txt = new SolidBrush(Color.FromArgb(135, 157, 151, 143))) {
            float[] vf = { 50f, 100f, 200f, 500f, 1000f, 2000f, 5000f, 10000f };
            for (int i = 0; i < vf.Length; i++) g.DrawLine(grid, XOf(vf[i]), PlotTop, XOf(vf[i]), PlotBottom);
            float[] hd = { -12f, -6f, 6f, 12f };
            for (int i = 0; i < hd.Length; i++) g.DrawLine(grid, 0, YOf(hd[i]), w, YOf(hd[i]));
            g.DrawLine(zero, 0, YOf(0f), w, YOf(0f));
            Font f = Font;
            g.DrawString("100", f, txt, XOf(100f) + 2, h - f.Height - 1);
            g.DrawString("1k", f, txt, XOf(1000f) + 2, h - f.Height - 1);
            g.DrawString("10k", f, txt, XOf(10000f) + 2, h - f.Height - 1);
            g.DrawString("+12", f, txt, 2, YOf(12f) - f.Height * 0.5f);
            g.DrawString("-12", f, txt, 2, YOf(-12f) - f.Height * 0.5f);
        }

        // Live analyzer fill and trace are drawn first; EQ response and nodes sit above them.
        if (spec != null && spec.Length > 1) {
            int n = spec.Length; float bottom = PlotBottom, top = PlotTop + 3;
            PointF[] pts = new PointF[n + 2];
            pts[0] = new PointF(XOf(20f), bottom);
            for (int i = 0; i < n; i++) {
                float f = (float)(20.0 * Math.Pow(1000.0, (i + 0.5) / n));
                pts[i + 1] = new PointF(XOf(f), bottom - spec[i] * (bottom - top) * .88f);
            }
            pts[n + 1] = new PointF(XOf(20000f), bottom);
            using (LinearGradientBrush fill = new LinearGradientBrush(new Rectangle(0, (int)top, w, Math.Max(1, (int)(bottom - top))), Color.FromArgb(84, acc), Color.FromArgb(8, acc), 90f))
                g.FillPolygon(fill, pts);
            using (Pen edge = new Pen(Color.FromArgb(205, acc), 1.6f)) {
                PointF[] line = new PointF[n]; for (int i = 0; i < n; i++) line[i] = pts[i + 1];
                g.DrawLines(edge, line);
            }
        }

        // EQ curve
        if (curve != null && curve.Length > 1) {
            int n = curve.Length; PointF[] line = new PointF[n];
            for (int i = 0; i < n; i++) {
                float d = Math.Max(-DbRange, Math.Min(DbRange, curve[i]));
                line[i] = new PointF(XOf(EqModel.FreqAt(i, n)), YOf(d));
            }
            using (Pen halo = new Pen(Color.FromArgb(52, acc), 6f)) { halo.LineJoin = LineJoin.Round; g.DrawLines(halo, line); }
            using (Pen p = new Pen(Color.FromArgb(245, 244, 239), 2.1f)) { p.LineJoin = LineJoin.Round; g.DrawLines(p, line); }
        }

        // EQ nodes are the controls: select a band here, or drag its handle vertically.
        if (names != null) {
            for (int i = 0; i < names.Length; i++) {
                float x = XOf(hz[i]), y = YOf(Math.Max(-DbRange, Math.Min(DbRange, nodeDb[i])));
                float r = major[i] ? 7f : 4.5f; bool active = (i == drag || i == hover || names[i] == selectedName);
                if (active) using (SolidBrush halo = new SolidBrush(Color.FromArgb(i == drag || i == hover ? 67 : 40, acc))) g.FillEllipse(halo, x - r - 7, y - r - 7, 2 * (r + 7), 2 * (r + 7));
                using (SolidBrush dot = new SolidBrush(major[i] ? acc : Color.FromArgb(200, acc))) g.FillEllipse(dot, x - r, y - r, 2 * r, 2 * r);
                using (SolidBrush core = new SolidBrush(Color.FromArgb(15, 17, 17))) g.FillEllipse(core, x - r * 0.4f, y - r * 0.4f, r * 0.8f, r * 0.8f);
                if (active && (i == drag || i == hover)) {
                    string t = names[i].ToUpperInvariant() + "  " + (nodeDb[i] > 0 ? "+" : "") + nodeDb[i].ToString("0") + " dB";
                    using (SolidBrush tb = new SolidBrush(Color.FromArgb(238, 242, 240))) g.DrawString(t, Font, tb, Math.Min(x + 10, w - 52), Math.Max(2, y - 22));
                }
            }
        }

        // Compact selector/readout controls live on the analyzer, not in a separate slider row.
        string[] primary = { "Low", "Mid", "High" };
        for (int i = 0; i < primary.Length; i++) {
            Rectangle chip = BandChipBounds(i); bool active = primary[i] == selectedName;
            Color edge = active ? acc : Color.FromArgb(65, 94, 101, 95);
            using (SolidBrush fill = new SolidBrush(Color.FromArgb(active ? 35 : 16, active ? acc : Color.FromArgb(120, 130, 126)))) g.FillRectangle(fill, chip);
            using (Pen border = new Pen(edge, 1f)) g.DrawRectangle(border, chip.X, chip.Y, chip.Width - 1, chip.Height - 1);
            string val = "0 dB";
            if (names != null) { int index = Array.IndexOf(names, primary[i]); if (index >= 0) val = (nodeDb[index] > 0 ? "+" : "") + nodeDb[index].ToString("0") + " dB"; }
            using (SolidBrush label = new SolidBrush(active ? Color.FromArgb(244, 242, 237) : Color.FromArgb(163, 170, 165)))
            using (SolidBrush value = new SolidBrush(active ? acc : Color.FromArgb(172, 179, 172))) {
                g.DrawString(primary[i].ToUpperInvariant(), Font, label, chip.X + 6, chip.Y + 4);
                SizeF size = g.MeasureString(val, Font); g.DrawString(val, Font, value, chip.Right - size.Width - 5, chip.Y + 4);
            }
        }
        bool signal = false;
        if (spec != null) for (int i = 0; i < spec.Length; i++) if (spec[i] > .035f) { signal = true; break; }
        string signalText = signal ? (outputMonitor ? "WIN MIX" : "MIC") : "NO SIGNAL";
        using (SolidBrush signalDot = new SolidBrush(signal ? Color.FromArgb(157, 211, 120) : Color.FromArgb(93, 101, 97))) g.FillEllipse(signalDot, w - 80, 12, 6, 6);
        using (SolidBrush signalBrush = new SolidBrush(signal ? Color.FromArgb(192, 205, 192) : Color.FromArgb(117, 126, 120))) g.DrawString(signalText, Font, signalBrush, w - 70, 8);
        using (Pen border = new Pen(Color.FromArgb(48, 56, 54), 1f)) g.DrawRectangle(border, 0, 0, w - 1, h - 1);
    }

    int Hit(int mx, int my) {
        if (names == null) return -1;
        int best = -1; float bestD = 18f * 18f;
        for (int i = 0; i < names.Length; i++) {
            float dx = XOf(hz[i]) - mx, dy = YOf(Math.Max(-DbRange, Math.Min(DbRange, nodeDb[i]))) - my, d = dx * dx + dy * dy;
            if (d < bestD) { bestD = d; best = i; }
        }
        return best;
    }
    int NearestNode(float x) {
        if (names == null || names.Length == 0) return -1;
        int best = 0; float distance = Math.Abs(XOf(hz[0]) - x);
        for (int i = 1; i < names.Length; i++) {
            float next = Math.Abs(XOf(hz[i]) - x);
            if (next < distance) { best = i; distance = next; }
        }
        return best;
    }
    int HitBandChip(Point p) {
        for (int i = 0; i < 3; i++) if (BandChipBounds(i).Contains(p)) return i;
        return -1;
    }
    void Emit(int i, int y) {
        int v = (int)Math.Round(DbOf(y)); if (v > 12) v = 12; if (v < -12) v = -12;
        if (NodeDrag != null) NodeDrag(names[i], v);
    }
    protected override void OnMouseDown(MouseEventArgs e) {
        base.OnMouseDown(e); if (e.Button != MouseButtons.Left) return;
        int chip = HitBandChip(e.Location);
        if (chip >= 0) { selectedName = new string[] { "Low", "Mid", "High" }[chip]; Invalidate(); return; }
        // A click between nodes grabs the closest band; dragging its handle adjusts gain.
        int i = Hit(e.X, e.Y); if (i < 0) i = NearestNode(e.X);
        if (i >= 0) { selectedName = names[i]; drag = i; Capture = true; Emit(i, e.Y); Invalidate(); }
    }
    protected override void OnMouseMove(MouseEventArgs e) {
        base.OnMouseMove(e);
        if (drag >= 0) { Emit(drag, e.Y); return; }
        int i = Hit(e.X, e.Y); if (i != hover) { hover = i; Cursor = i >= 0 ? Cursors.SizeNS : Cursors.Default; Invalidate(); }
    }
    protected override void OnMouseUp(MouseEventArgs e) { base.OnMouseUp(e); drag = -1; Capture = false; Invalidate(); }
    protected override void OnMouseLeave(EventArgs e) { base.OnMouseLeave(e); if (hover != -1) { hover = -1; Invalidate(); } }
    protected override void OnMouseDoubleClick(MouseEventArgs e) {
        base.OnMouseDoubleClick(e); int i = Hit(e.X, e.Y);
        if (i >= 0 && NodeDrag != null) { selectedName = names[i]; NodeDrag(names[i], 0); Invalidate(); }   // double-click a node to reset it
    }
}
