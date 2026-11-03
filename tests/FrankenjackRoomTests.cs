using System;
using System.IO;

internal static class FrankenjackRoomTests {
    static int Main() {
        string file=Path.Combine(Path.GetTempPath(),"earnest-room-"+Guid.NewGuid().ToString("N")+".json");
        var engine=new EarnestEngine();
        try {
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
