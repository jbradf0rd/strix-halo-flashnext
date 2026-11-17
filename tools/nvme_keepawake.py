#!/usr/bin/env python3
"""Keep an NVMe drive from going quiet: one 4 KiB direct read every 50 ms (about 80 KB/s).

Usage: nvme_keepawake.py FILE [INTERVAL_SECONDS]
FILE is any file of 8 MiB or more on the drive that the inference engine reads from.
Linux only (O_DIRECT). Stop it with SIGTERM or Ctrl-C.
"""
import mmap, os, random, sys, time

if len(sys.argv) < 2:
    sys.exit(__doc__)
path = sys.argv[1]
interval = float(sys.argv[2]) if len(sys.argv) > 2 else 0.05
fd = os.open(path, os.O_RDONLY | os.O_DIRECT)
buf = mmap.mmap(-1, 4096)          # page-aligned buffer, required by O_DIRECT
pages = os.path.getsize(path) // 4096
if pages < 2048:
    sys.exit("FILE must be 8 MiB or more")
try:
    while True:
        os.preadv(fd, [buf], random.randrange(pages) * 4096)
        time.sleep(interval)
except KeyboardInterrupt:
    pass
