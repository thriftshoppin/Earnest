// Offline checks of the native mix path. This harness does not open an audio device.
using System;
using System.IO;
using NAudio.Wave;

internal static class FrankenjackMixTests {
    static string profile;
    static int failures;
    static void Near(string name, float actual, float expected, float tolerance) {
        if (float.IsNaN(actual) || Math.Abs(actual-expected)>tolerance) {
            Console.WriteLine("FAIL {0}: {1} vs {2}",name,actual,expected); failures++;
        } else Console.WriteLine("PASS {0}: {1}",name,actual);
    }
    static float[] Run(float dry,float center,float wet,float master,float ceiling,float left,float right,float width=1f) {
        const int rate=48000, frames=16000;
        var source=new BufferedWaveProvider(WaveFormat.CreateIeeeFloatWaveFormat(rate,2));
        source.BufferDuration=TimeSpan.FromSeconds(2);
        var input=new float[frames*2];
        for (int i=0;i<frames;i++) { input[i*2]=left; input[i*2+1]=right; }
        var bytes=new byte[input.Length*4]; Buffer.BlockCopy(input,0,bytes,0,bytes.Length); source.AddSamples(bytes,0,bytes.Length);
        var provider=new ConvolutionProvider(source,profile);
        provider.TargetDry=dry; provider.TargetCenter=center; provider.TargetGain=wet; provider.TargetMaster=master; provider.TargetCeiling=ceiling; provider.TargetWidth=width;
        var result=new byte[bytes.Length]; provider.Read(result,0,result.Length);
        var output=new float[input.Length]; Buffer.BlockCopy(result,0,output,0,result.Length);
        return new float[]{output[output.Length-2],output[output.Length-1]};
    }
    static double ToneRms(bool direct, bool boostDirect) {
        const int rate=48000, frames=48000;
        var source=new BufferedWaveProvider(WaveFormat.CreateIeeeFloatWaveFormat(rate,2));
        source.BufferDuration=TimeSpan.FromSeconds(2);
        var input=new float[frames*2];
        for(int i=0;i<frames;i++) { float v=(float)(.01*Math.Sin(2*Math.PI*1000*i/rate)); input[2*i]=v; input[2*i+1]=v; }
        var bytes=new byte[input.Length*4]; Buffer.BlockCopy(input,0,bytes,0,bytes.Length); source.AddSamples(bytes,0,bytes.Length);
        var provider=new ConvolutionProvider(source,profile);
        provider.TargetDry=direct?1:0; provider.TargetGain=direct?0:1; provider.TargetMaster=1; provider.TargetCeiling=1;
        if(boostDirect) provider.DirectEq.Target=new float[]{0,0,0,6,0,0,0};
        var result=new byte[bytes.Length]; provider.Read(result,0,result.Length);
        var output=new float[input.Length]; Buffer.BlockCopy(result,0,output,0,result.Length);
        double energy=0; for(int i=frames-12000;i<frames;i++) energy+=output[2*i]*output[2*i];
        return Math.Sqrt(energy/12000);
    }
    static double FilterGainAtCenter(int band, float gainDb) {
        int[] frequencies={125,250,500,1000,2000,4000,8000}; const int rate=48000, frames=48000;
        var filter=new ReflectionEq(1,rate); var target=new float[7]; target[band]=gainDb; filter.Target=target;
        for(int i=0;i<300;i++) filter.Update();
        double inputEnergy=0, outputEnergy=0;
        for(int i=0;i<frames;i++) {
            float v=(float)(.01*Math.Sin(2*Math.PI*frequencies[band]*i/rate));
            float y=filter.Process(0,v);
            if(i>=frames-12000) { inputEnergy+=v*v; outputEnergy+=y*y; }
        }
        return Math.Sqrt(outputEnergy/inputEnergy);
    }
    static int Main() {
        profile=Path.Combine(Path.GetTempPath(),"earnest-test-"+Guid.NewGuid().ToString("N")+".erir");
        try {
            using(var writer=new BinaryWriter(File.Create(profile))) {
                writer.Write(new char[]{'E','R','I','R'}); writer.Write(1); writer.Write(48000); writer.Write(2); writer.Write(1); writer.Write(1f); writer.Write(1f);
            }
            for(int band=0;band<7;band++) {
                Near("EQ center +6 dB band " + band,(float)FilterGainAtCenter(band,6),(float)Math.Pow(10,6.0/20),.015f);
                Near("EQ center -6 dB band " + band,(float)FilterGainAtCenter(band,-6),(float)Math.Pow(10,-6.0/20),.015f);
            }
            double unityDirect=ToneRms(true,false), boostedDirect=ToneRms(true,true);
            Near("direct EQ +6 dB at center frequency",(float)(boostedDirect/unityDirect),(float)Math.Pow(10,6.0/20),.03f);
            double unityWet=ToneRms(false,false), isolatedWet=ToneRms(false,true);
            Near("direct EQ leaves wet path alone",(float)(isolatedWet/unityWet),1,.001f);
            var mono=Run(1,0,0,1,1,.04f,.02f,0);
            Near("width zero sums to mid left",mono[0],.03f,.0002f); Near("width zero sums to mid right",mono[1],.03f,.0002f);
            var widened=Run(1,0,0,1,1,.04f,.02f,2);
            Near("width two doubles side left",widened[0],.05f,.0002f); Near("width two doubles side right",widened[1],.01f,.0002f);
            var direct=Run(1,0,0,1,1,.04f,.02f);
            Near("dry left",direct[0],.04f,.0002f); Near("dry right",direct[1],.02f,.0002f);
            var centered=Run(1,1,0,1,1,.04f,.02f);
            Near("additive mid left",centered[0],.07f,.0002f); Near("additive mid right",centered[1],.05f,.0002f);
            var wet=Run(0,0,1,1,1,.04f,.02f);
            Near("unity impulse wet left",wet[0],.04f,.0002f); Near("unity impulse wet right",wet[1],.02f,.0002f);
            var gain=Run(1,0,0,2,1,.04f,.02f);
            Near("master gain left",gain[0],.08f,.0002f); Near("master gain right",gain[1],.04f,.0002f);
            var clamped=Run(1,0,0,1,.01f,.04f,-.02f);
            Near("positive ceiling",clamped[0],.01f,.0002f); Near("negative ceiling",clamped[1],-.01f,.0002f);
        } finally { if(File.Exists(profile))File.Delete(profile); }
        return failures==0 ? 0 : 1;
    }
}
