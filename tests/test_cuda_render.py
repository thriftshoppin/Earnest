import unittest
import numpy as np
from earnest.cli import _room_template
from earnest.engine.room import RoomSpec
from earnest.engine.solve import solve_room
from earnest.engine.render import render_room, _partition_audio

try:
    import cupy as cp
    GPU_AVAILABLE = cp.cuda.runtime.getDeviceCount() > 0
except Exception:
    GPU_AVAILABLE = False

class CudaRenderTests(unittest.TestCase):
    def test_backend_validation(self):
        room=RoomSpec.from_dict(_room_template())
        solution=solve_room(room,fs=24000,max_order=0)
        audio=np.zeros((32,len(room.sources)))
        with self.assertRaisesRegex(ValueError,'backend'):
            render_room(room,solution,audio,fs=24000,backend='invalid')
        with self.assertRaisesRegex(ValueError,'nonnegative'):
            render_room(room,solution,audio,fs=24000,cuda_device=-1)
        with self.assertRaisesRegex(ValueError,'CUDA backend unavailable'):
            render_room(room,solution,audio,fs=24000,backend='cuda',cuda_device=99999)

    @unittest.skipUnless(GPU_AVAILABLE,'CUDA is not available')
    def test_gpu_matches_cpu_partition_and_room_render(self):
        room=RoomSpec.from_dict(_room_template())
        solution=solve_room(room,fs=24000,max_order=1)
        rng=np.random.default_rng(140)
        audio=rng.normal(0,.05,(512,len(room.sources)))
        cpu_bands,cpu_res=_partition_audio(audio[:,0],24000)
        gpu_bands,gpu_res=_partition_audio(cp.asarray(audio[:,0]),24000,cp)
        for cpu,gpu in zip(cpu_bands,gpu_bands):
            np.testing.assert_allclose(cpu,cp.asnumpy(gpu),rtol=1e-9,atol=1e-11)
        np.testing.assert_allclose(cpu_res,cp.asnumpy(gpu_res),rtol=1e-9,atol=1e-11)
        cpu=render_room(room,solution,audio,fs=24000,direct_gain=.8,reflection_gain_db=(1,2,3,0,-1,-2,-3))
        gpu=render_room(room,solution,audio,fs=24000,direct_gain=.8,reflection_gain_db=(1,2,3,0,-1,-2,-3),backend='cuda')
        self.assertEqual(gpu['compute_backend'],'cuda')
        for receiver in cpu['receiver_outputs']:
            for key in ('audio','direct_audio'):
                np.testing.assert_allclose(cpu['receiver_outputs'][receiver][key],gpu['receiver_outputs'][receiver][key],rtol=1e-8,atol=1e-10)

if __name__=='__main__': unittest.main()
