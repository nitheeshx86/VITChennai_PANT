import bpy, sys, os, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "wrapper"))
import eyes
s = bpy.context.scene
eyes.move(0.6, -0.35)
for n in (128, 64, 32):
    s.cycles.samples = n
    t = time.time()
    eyes.render(os.path.join(ROOT, "debug", "spp_%d.png" % n))
    print("SPP", n, "%.1fs" % (time.time() - t))
