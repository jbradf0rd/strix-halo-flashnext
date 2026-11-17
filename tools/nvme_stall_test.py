#!/usr/bin/env python3
"""Does the drive answer slowly when a small read arrives after a short quiet gap, in the time after a large write?

Usage: nvme_stall_test.py READ_FILE WRITE_DIR [SIZE_MB] [AFTER_SECONDS] [BEFORE_SECONDS]

READ_FILE  a large existing file on the drive under test (a model file). It is only read.
WRITE_DIR  a directory on the same drive. The test writes one file of SIZE_MB there and deletes it.
Defaults: SIZE_MB 1448, AFTER_SECONDS 150, BEFORE_SECONDS 45.

One reader. Each cycle it waits 0.15 s, 0.3 s and 0.6 s in turn with no disk activity from this
process, then times one 4 KiB O_DIRECT read. Stage 1 runs before any write. Stage 2 runs after
writing SIZE_MB of random data with fsync. Run it on a machine with no other disk load.
A continuous reader does not show this fault, because the drive is then never quiet.
Linux only.
"""
import mmap, os, random, sys, time

if len(sys.argv) < 3:
    sys.exit(__doc__)
read_file, write_dir = sys.argv[1], sys.argv[2]
size_mb = int(sys.argv[3]) if len(sys.argv) > 3 else 1448
after = int(sys.argv[4]) if len(sys.argv) > 4 else 150
before = int(sys.argv[5]) if len(sys.argv) > 5 else 45
out = os.path.join(write_dir, "nvme-stall-test.bin")
fd = os.open(read_file, os.O_RDONLY | os.O_DIRECT)
buf = mmap.mmap(-1, 4096)
pages = os.path.getsize(read_file) // 4096
rng = random.Random(11)
GAPS = (0.15, 0.3, 0.6)


def run(seconds, label, t_ref):
    rows = []
    end = time.time() + seconds
    while time.time() < end:
        for gap in GAPS:
            time.sleep(gap)
            p = time.perf_counter()
            os.preadv(fd, [buf], rng.randrange(pages) * 4096)
            rows.append((time.time() - t_ref, gap, (time.perf_counter() - p) * 1000))
    for gap in GAPS:
        v = sorted(r[2] for r in rows if r[1] == gap)
        if v:
            print("%-12s gap %.2f s: reads %4d median %6.1f ms max %7.1f ms | over 100 ms: %3d, time lost %.1f s" % (
                label, gap, len(v), v[len(v) // 2], v[-1], sum(x > 100 for x in v), sum(x for x in v if x > 100) / 1000))
    return rows


run(before, "before write", time.time())
block = os.urandom(8 << 20)
w = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
try:
    t = time.time()
    for _ in range(max(1, size_mb // 8)):
        os.write(w, block)
    os.fsync(w)
    os.close(w)
    t_w = time.time()
    print("wrote %d MB in %.1f s" % (size_mb, t_w - t))
    rows = run(after, "after write", t_w)
finally:
    if os.path.exists(out):
        os.unlink(out)
slow = [r for r in rows if r[2] > 100]
print("slow reads after the write (seconds after write, gap, ms):")
for r in slow[:60]:
    print("  %6.1f  %.2f  %6.0f" % r)
if slow:
    print("first slow read %.1f s after the write, last %.1f s after" % (slow[0][0], slow[-1][0]))
else:
    print("  none")
