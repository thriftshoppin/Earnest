using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

public static class Theme {
    public static readonly Color Accent = Color.FromArgb(255, 46, 136);
    public static readonly Color AccentDim = Color.FromArgb(40, 255, 46, 136);
}

public class StageSlider : Control {
    int minimum = 0, maximum = 100, value = 50; bool dragging = false;
    public event EventHandler ValueChanged;
    public int Minimum { get { return minimum; } set { minimum = value; Invalidate(); } }
    public int Maximum { get { return maximum; } set { maximum = value; Invalidate(); } }
    public int Value {
        get { return value; }
        set {
            int n = Math.Max(minimum, Math.Min(maximum, value));
            if (n != this.value) { this.value = n; Invalidate(); if (ValueChanged != null) ValueChanged(this, EventArgs.Empty); }
        }
    }
    public StageSlider() {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.UserPaint | ControlStyles.ResizeRedraw, true);
        Height = 38; Cursor = Cursors.Hand; BackColor = Color.FromArgb(27, 30, 30);
    }
    protected override void OnPaint(PaintEventArgs e) {
        base.OnPaint(e); e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        int left = 14, right = Width - 14, y = Height / 2;
        float t = maximum == minimum ? 0 : (float)(value - minimum) / (maximum - minimum);
        int x = left + (int)((right - left) * t);
        using (var track = new Pen(Color.FromArgb(48, 67, 72), 3)) e.Graphics.DrawLine(track, left, y, right, y);
        using (var fill = new Pen(Color.FromArgb(Theme.Accent.R, Theme.Accent.G, Theme.Accent.B), 3)) e.Graphics.DrawLine(fill, left, y, x, y);
        using (var ticks = new Pen(Color.FromArgb(65, 91, 96), 1)) for (int i = 0; i <= 20; i++) { int tx = left + (right - left) * i / 20; int th = i % 5 == 0 ? 5 : 2; e.Graphics.DrawLine(ticks, tx, y - th - 4, tx, y - 4); }
        using (var shadow = new SolidBrush(Theme.AccentDim)) e.Graphics.FillEllipse(shadow, x - 13, y - 13, 26, 26);
        using (var knob = new SolidBrush(Color.FromArgb(20, 35, 40))) e.Graphics.FillEllipse(knob, x - 8, y - 8, 16, 16);
        using (var edge = new Pen(Theme.Accent, 2)) e.Graphics.DrawEllipse(edge, x - 7, y - 7, 14, 14);
        using (var core = new SolidBrush(Theme.Accent)) e.Graphics.FillEllipse(core, x - 2, y - 2, 4, 4);
    }
    int Position(int x) {
        int l = 14, r = Width - 14;
        float t = Math.Max(0, Math.Min(1, (float)(x - l) / (r - l)));
        return minimum + (int)Math.Round(t * (maximum - minimum));
    }
    protected override void OnMouseDown(MouseEventArgs e) { base.OnMouseDown(e); dragging = true; Capture = true; Value = Position(e.X); }
    protected override void OnMouseMove(MouseEventArgs e) { base.OnMouseMove(e); if (dragging) Value = Position(e.X); }
    protected override void OnMouseUp(MouseEventArgs e) { base.OnMouseUp(e); dragging = false; Capture = false; }
    protected override void OnMouseEnter(EventArgs e) { base.OnMouseEnter(e); Focus(); }
    protected override void OnMouseWheel(MouseEventArgs e) { base.OnMouseWheel(e); Value += Math.Sign(e.Delta); }
}
