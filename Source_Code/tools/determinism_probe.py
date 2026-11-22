import bpy, sys, os, hashlib
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
s = bpy.context.scene
s.render.resolution_percentage = 50
s.cycles.samples = 32
eyes.move(0.6, -0.35)
def run(tag, device, denoise, dn_gpu=False):
    hs = []
    for i in range(2):
        os.environ["XR_DEVICE"] = device
        s.cycles.use_denoising = denoise
        try: s.cycles.denoising_use_gpu = dn_gpu
        except Exception: pass
        p = os.path.join(ROOT, "debug", "det_%s_%d.png" % (tag, i))
        eyes.render(p)
        hs.append(hashlib.sha256(open(p, "rb").read()).hexdigest()[:12])
    print("DET %-22s device=%s identical=%s" % (tag, s.cycles.device, hs[0] == hs[1]), hs)
run("gpu_denoise_cpu", "AUTO", True)
run("gpu_nodenoise", "AUTO", False)
run("cpu_denoise", "CPU", True)
