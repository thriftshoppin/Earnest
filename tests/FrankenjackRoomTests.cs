using System;
using System.IO;
using System.Reflection;

internal static class FrankenjackRoomTests {
    static int Main() {
        string file=Path.Combine(Path.GetTempPath(),"earnest-room-"+Guid.NewGuid().ToString("N")+".json");
        var engine=new EarnestEngine();
        try {
            var bands=new float[10]; var flat=EqModel.Curve(301,48000,0,0,0,50,false,bands);
            foreach(float point in flat) if(Math.Abs(point)>.0001) return 6;
            bands[5]=6; var boosted=EqModel.Curve(301,48000,0,0,0,50,false,bands);
            int closest=0; for(int i=1;i<301;i++) if(Math.Abs(EqModel.FreqAt(i,301)-1000)<Math.Abs(EqModel.FreqAt(closest,301)-1000)) closest=i;
            if(Math.Abs(boosted[closest]-6)>.03) return 7;
            Console.WriteLine("PASS graph follows the Earnest filter response");
            var read=typeof(StageJackMonitor).GetMethod("ReadLoopbackSample",BindingFlags.Static|BindingFlags.NonPublic);
            float pcm=(float)read.Invoke(null,new object[]{BitConverter.GetBytes((short)16384),0,16,false});
            float ieee=(float)read.Invoke(null,new object[]{BitConverter.GetBytes(-0.25f),0,32,true});
            if(Math.Abs(pcm-.5f)>.00001 || Math.Abs(ieee+.25f)>.00001) return 4;
            var silent=new StageJackMonitor();
            float[] l={1,1}, r={1,1}; silent.CopyRecentOutput(l,r); silent.Dispose();
            if(l[0]!=0 || r[0]!=0) return 5;
            Console.WriteLine("PASS original monitor decodes samples and clears unavailable input");
            File.WriteAllText(file,"{}");
            engine.SelectRoom(file);
            if (engine.RoomPath!=Path.GetFullPath(file) || engine.Running || engine.Building) return 1;
            try { engine.SelectRoom(file+".missing"); return 2; }
            catch (FileNotFoundException) { }
            if (engine.RoomPath!=Path.GetFullPath(file)) return 3;
            Console.WriteLine("PASS room selection and missing-file rejection without starting audio");
            return 0;
        } finally { engine.Shutdown(); if(File.Exists(file)) File.Delete(file); }
    }
}
