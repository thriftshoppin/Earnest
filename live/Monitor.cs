// Read-only WASAPI loopback meter. Does not create a playback stream.
using System;
using System.Globalization;
using System.Linq;
using System.Threading;
using NAudio.CoreAudioApi;
using NAudio.Dsp;
using NAudio.Wave;

class Monitor {
  static readonly object Gate = new object();
  static double sumL, sumR, peakL, peakR, sumCross, sumM, sumS;
  static long count;
  static readonly int N = 2048;
  static float[] history = new float[N];
  static int pos, filled;
  static volatile bool failed;
  static string F(double n) { return n.ToString("0.000000", CultureInfo.InvariantCulture); }
  static void Main(string[] args) {
    try {
      string match=args.Length>0?args[0]:"Speakers (Razer Kraken V3 X)";
      using(var en=new MMDeviceEnumerator()) {
        var devices=en.EnumerateAudioEndPoints(DataFlow.Render,DeviceState.Active);
        var d=devices.FirstOrDefault(x=>x.ID==match || String.Equals(x.FriendlyName,match,StringComparison.OrdinalIgnoreCase));
        if(d==null) throw new Exception("Playback endpoint not found: "+match);
        using(var capture=new WasapiLoopbackCapture(d)) {
          var fmt=capture.WaveFormat;
          var ext=fmt as WaveFormatExtensible;
          bool fl=fmt.Encoding==WaveFormatEncoding.IeeeFloat || (ext!=null && ext.SubFormat==new Guid("00000003-0000-0010-8000-00aa00389b71"));
          if(!fl || fmt.BitsPerSample!=32 || fmt.Channels<2) throw new Exception("Monitor requires 32-bit float stereo or multichannel loopback; endpoint reports "+fmt);
          capture.DataAvailable += (sender,e)=> {
            lock(Gate) {
              int stride=fmt.Channels*4;
              for(int i=0;i+stride<=e.BytesRecorded;i+=stride) {
                float l=BitConverter.ToSingle(e.Buffer,i),r=BitConverter.ToSingle(e.Buffer,i+4);
                if(float.IsNaN(l)||float.IsInfinity(l)||float.IsNaN(r)||float.IsInfinity(r)) continue;
                sumL+=l*l;sumR+=r*r;sumCross+=l*r;peakL=Math.Max(peakL,Math.Abs(l));peakR=Math.Max(peakR,Math.Abs(r));
                double m=(l+r)*0.5,s=(l-r)*0.5;sumM+=m*m;sumS+=s*s;count++;
                history[pos]=(float)m;pos=(pos+1)%N;if(filled<N)filled++;
              }
            }
          };
          capture.RecordingStopped += (sender,e)=> { if(e.Exception!=null) Console.Error.WriteLine(e.Exception.Message); failed=true; };
          capture.StartRecording();
          while(!failed) {
            Thread.Sleep(125);
            double l,r,pl,pr,corr,mid,side;long n;var fft=new Complex[N];int have;
            lock(Gate) {
              n=count; l=n>0?Math.Sqrt(sumL/n):0; r=n>0?Math.Sqrt(sumR/n):0;pl=peakL;pr=peakR;
              corr=(sumL>1e-20&&sumR>1e-20)?sumCross/Math.Sqrt(sumL*sumR):0;
              mid=n>0?Math.Sqrt(sumM/n):0; side=n>0?Math.Sqrt(sumS/n):0;
              have=filled;
              if(have==N) for(int i=0;i<N;i++) fft[i].X=(float)(history[(pos+i)%N]*(0.5-0.5*Math.Cos(2*Math.PI*i/(N-1))));
              sumL=sumR=sumCross=peakL=peakR=sumM=sumS=0;count=0;
            }
            double[] bands=new double[7];double[] hz={125,250,500,1000,2000,4000,8000};
            if(have==N) {
              FastFourierTransform.FFT(true,11,fft);
              for(int i=1;i<N/2;i++) {
                double f=(double)i*fmt.SampleRate/N;
                for(int b=0;b<7;b++) if(f>=hz[b]/Math.Sqrt(2)&&f<hz[b]*Math.Sqrt(2)) bands[b]+=fft[i].X*fft[i].X+fft[i].Y*fft[i].Y;
              }
            }
            Console.WriteLine("{\"rms\":["+F(l)+","+F(r)+"],\"peak\":["+F(pl)+","+F(pr)+"],\"correlation\":"+F(corr)+",\"mid\":"+F(mid)+",\"side\":"+F(side)+",\"bands\":["+String.Join(",",bands.Select(x=>F(Math.Sqrt(x))))+"],\"frames\":"+n+",\"sample_rate\":"+fmt.SampleRate+",\"channels\":"+fmt.Channels+"}");
          }
        }
      }
    } catch(Exception ex) { Console.Error.WriteLine(ex.Message);Environment.ExitCode=1; }
  }
}
