# Qwen3.8 Flash-Next on Strix Halo with gufo: setup and measured results

Dated 17 November 2026. Every figure is a measurement on one machine. The date of each measurement is given where it is not 17 November. Speeds are tokens per second (tok/s).

## Summary

- Decode with MTP drafting is 46.9 to 50.1 tok/s on document tasks. Without drafting it is 27.2 to 28.1.
- Prompt reading is 1,556 to 1,871 tok/s from 2K to 243K tokens. The full 262,144 context fits in 123 GiB.
- Decode is at about 92 percent of the memory bandwidth limit. No serve flag raises it.
- The remaining gains are in time to first token on follow-up questions. `--sessions 1` cuts that wait from 22 to 84 seconds down to 1 to 3 seconds on documents of 131K and 243K tokens.
- The disk cache causes pauses of 0.15 to 0.9 seconds inside answers on this NVMe drive. A keep-awake reader removed them in one run.

## Hardware and software

| Item | Value |
| --- | --- |
| Machine | GMKtec NucBox EVO-X2, BIOS 1.12 (9 December 2025) |
| Chip | AMD Ryzen AI Max+ 395, 16 cores, Radeon 8060S (`gfx1151`) |
| Memory | 128 GB LPDDR5X, 123 GiB visible. Modules are rated 8000 MT/s and run at 7500 |
| Graphics memory split | 2 GiB VRAM, 124 GiB GTT. HIP allocates from GTT |
| Disk | YMTC PC411 2 TB NVMe, firmware YM3603B0, ext4 |
| OS | Ubuntu 24.04.4, kernel 7.0.0-28 |
| Kernel command line | `amd_iommu=off amdgpu.gttsize=126976 ttm.pages_limit=32505856 ttm.page_pool_size=32505856` |
| Power | `platform_profile` performance, governor performance, stock limits (85 W STAPM, 120 W fast, 85 W slow) |
| ROCm | 7.2.4 |
| Engine | gufo, built from source on 2 November 2026 at commit `6ab4569`, no local patch |
| Model | Qwen3.8 Flash-Next `UD-Q4_K_XL` (Huihui abliterated build), four shards, 111.3 GB |
| Draft head | `mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf`, 2.79 GB, from `unsloth/Qwen3.8-Flash-Next-GGUF` |
| Vision file | `mmproj-BF16.gguf`, 0.9 GB |

## Build

The released `.deb` needs ROCm 10.1 and `libicu76`, so it does not run on Ubuntu 24.04 with ROCm 7.2.4. This build needs no root.

```bash
micromamba create -y -p ~/mamba/gufo-build -c conda-forge \
  cmake ninja pkg-config icu soxr libsndfile libwebp libjpeg-turbo libpng zlib ffmpeg

cmake -S ~/ai/gufo-src -B ~/ai/gufo-src/build/release \
  -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF -DENGINE_ENABLE_HIP=ON \
  -DCMAKE_PREFIX_PATH="$HOME/mamba/gufo-build;/opt/rocm" \
  -DCMAKE_HIP_COMPILER=/opt/rocm/lib/llvm/bin/clang++ \
  -DCMAKE_HIP_COMPILER_ROCM_ROOT=/opt/rocm \
  -DCMAKE_C_COMPILER=/usr/bin/gcc -DCMAKE_CXX_COMPILER=/usr/bin/g++
cmake --build ~/ai/gufo-src/build/release --parallel 28
```

- CMake 3.28 refuses `hipcc` as the HIP compiler. Use ROCm's `clang++` with `CMAKE_HIP_COMPILER_ROCM_ROOT`.
- Use the system gcc 13.3 as host compiler. Conda gcc 15 fails at the final link.
- From gufo 0.34 the build also needs Rust 1.88.0 from `rustup`.
- `gufo diagnose` must print `Overall Status: [PASS]` and `gfx1151`.

## Serve command in use

```bash
export LD_LIBRARY_PATH=/opt/rocm/lib:$HOME/mamba/gufo-build/lib
gufo serve llm \
  --model  $M/UD-Q4_K_XL/Qwen3.8-Flash-Next-UD-Q4_K_XL-00001-of-00004.gguf \
  --speculative mtp --mtp-model $M/MTP/mtp-Qwen3.8-Flash-Next-shared-Q8_0.gguf \
  --mmproj $M/mmproj-BF16.gguf \
  --sessions 2 --think off \
  --cache-disk ~/ai/cache/flash-next \
  --host <address> --port 8097
```

- No `--context` flag gives the native 262,144.
- `--think off` puts the answer in `message.content`. With thinking on, `content` is empty and the text is in `reasoning_content`.
- The server runs behind llama-swap with `ttl: 14400` and `useModelName: "Qwen3.8 Flash Next"`. gufo answers HTTP 400 to any other model name.
- Usable quants are limited by gufo's expert kernels: Q4_K, Q5_K, Q5_1 and Q8_0 expert tensors, and no Q6_K output head. `UD-IQ4_XS` loads after a whitelist patch and then fails every request.

## Baseline

Test load: six knowledge-work tasks about one 21,500-token document, temperature 0, thinking off, one warm-up request first. The decode figure is the median of the six tasks. 12 control runs.

| Measure | Result |
| --- | ---: |
| Decode, MTP, median of six tasks | 46.9 to 50.1 tok/s |
| Decode, MTP, per task | 39.7 to 54.6 tok/s |
| Draft acceptance | 67.3 percent (1,527 of 2,268) |
| Decode, no drafting (11 November) | 27.2 tok/s |
| Prompt reading, 21,533 new tokens | 1,686 to 1,725 tok/s |
| Time to first token, 21.5K document, cold | 12.4 to 12.9 s |
| Time to first token, same document, later tasks | 0.2 s |
| Six tasks, total time | 66 to 68 s |
| Model load | 18 to 52 s |
| Peak graphics memory | 104.3 GiB |

Standard `gufo bench` table, drafting off, measured 1 November 2026:

| Depth | pp512 | pp2048 | tg128 |
| ---: | ---: | ---: | ---: |
| 0 | 1,311 | 1,871 | 28.1 |
| 32,768 | 1,256 | 1,760 | 27.8 |
| 131,072 | 1,191 | 1,657 | 27.4 |

Decode with MTP depends on the text type. With 512 output tokens on 1 November 2026, prose ran at 37.0 tok/s (51 percent acceptance), Python at 66.5 (80 percent) and a code edit at 82.8 (82 percent). `gufo bench` with MTP overstates decode because its prompt makes the model copy text. Use an HTTP harness with real tasks.

Long documents, cold, one question, three hidden codes to find:

| Document | Time to first token | Prompt reading | Codes found |
| --- | ---: | ---: | --- |
| 130,979 tokens | 80.5 s | 1,627 tok/s | 3 of 3 |
| 243,549 tokens | 156.5 s | 1,556 tok/s | 3 of 3 |
| Two documents of 243K at once | 306 s and 316 s | not computed | 3 of 3 each |

## Bandwidth limit

Decode speed is close to memory bandwidth divided by the bytes read per step. The model has 48 layers and 512 experts per layer, with 10 used per token. One step without drafting reads 6.34 GB: 4.19 GB of always-used weights, 1.47 GB of experts and 0.68 GB of output head. At 215 GB/s under load that gives 33.9 tok/s, and the measured 28.1 is 83 percent of it.

With MTP the measured mix is 2.82 drafted and 2.92 emitted tokens per step, about 11.6 GB per step. The limit is 54.3 tok/s, and the measured 49.7 is 92 percent of it. The 215 GB/s figure was measured on 12 November and the draft cost is computed from tensor sizes.

gufo already prunes the draft head. It scores the first 98,304 vocabulary rows plus a table of up to 1,024 extra tokens, and falls back to the full 248,320-row head on a miss.

## Flags and their measured effect

Each candidate ran between two control runs. Decode is the six-task median.

| Change | Decode, tok/s | Other effect | Verdict |
| --- | ---: | --- | --- |
| `--speculative mtp` against `off` (11 November) | 49.6 against 27.2 | plus 82 percent | keep |
| `--draft-tokens` 7, 5, 3 (11 November) | 49.6, 48.5, 46.3 | above 7 the server does not start | keep 7 |
| `--min-draft-tokens` above 1 | none | the server does not start | keep 1 |
| `--prefill-chunk` 256, 1024 | 49.7, 49.3 | none | no gain |
| `--prefill-chunk` 2048 (11 November) | 47.0 | none | worse |
| `--log-level error` | 48.9 | none | no gain |
| `--context 131072` | 48.5 | 6.7 GiB less memory, faster follow-ups, see below | optional |
| `--sessions 1` | 38.0 and 42.0 | 7.3 GiB less memory, faster follow-ups, pauses, see below | see below |
| `--cache-ram-bytes off` | 49.3 | six tasks take 100 s against 66 to 68 | worse |
| no `--cache-disk` | 43.6 | answers differ from every other run | no gain |
| `--cache-disk-bytes` 32 GiB | not measured | no change on long-document follow-ups | no gain |
| no `--mmproj` | 50.2 | gufo finds and loads the vision file anyway | no effect |

Changes outside the serve flags:

| Change | Result |
| --- | --- |
| Power limits raised to 120 W each (2 November) | decode 49.76 and 49.55 against 49.06 and 49.65, prompt reading 1,726 against 1,793, core at 89 to 94 degrees. No gain |
| gufo 0.34.0 against the 2 November build (11 November) | 47.9 against 49.1 to 49.7. About 2.9 percent slower |
| Disk cache across a server restart | the same 21,526-token request took 8.7 s against 20.8 s cold |
| Prompt that states the shape of the answer | 64.9 tok/s at 80.7 percent acceptance against 41.5 at 65.8 percent |
| Memory at 8000 MT/s | not measured. The rated speed is 6.7 percent above the configured speed, and it needs a BIOS setting this board may not expose |

## Follow-up questions on long documents

gufo sizes its RAM cache from the memory free after load. With two sessions at full context that cache is 5.0 to 5.5 GB. A saved state costs about 133 MB plus 27.5 KB per token, so a 243K-token document needs about 6.8 GB and does not fit. `--sessions 1` or `--context 131072` raises the cache to 9.4 GB.

Time to first token, document A of 131,051 tokens and document B of 243,508 tokens:

| Step | `--sessions 2` | `--sessions 1` |
| --- | ---: | ---: |
| A, first question | 80 to 88 s | 80.2 s |
| A, second question | 22.4 s | 1.7 s |
| B, first question | 158 to 160 s | 157.2 s |
| B, second question | 83.2 s | 2.9 s |
| A again, after B | 80.8 s | 0.9 s (restored from disk cache) |

With `--context 131072` and two sessions, the second question on a 100,025-token document started after 1.4 s against 16.7 s.

Not measured: decode speed on the long documents under either setting, and both settings together.

## NVMe stall after large writes

With the disk cache on, answers pause for 0.15 to 0.94 s. One session had 12 to 15 pauses in six tasks, and two sessions had 7 to 8. With the disk cache off there was no pause in two runs.

Mechanism:

1. gufo reads rows of the model's n-gram table from disk with `O_DIRECT` on the decode path (`src/models/qwen38_flash_next/ngram.cpp`, 128 reader threads). Decode waits for those reads.
2. The disk cache writes about 723 MB per saved document state.
3. For about 7 to 33 s after a large write, this drive answers a 4 KiB direct read in 0.15 to 0.8 s when the read follows a quiet gap of 0.15 s or more. The normal time is 2 to 6 ms.

Evidence:

- Thread samples during the pauses showed 34 gufo threads on average in `blk_io_schedule`, against 0.8 in normal decode. There was no swap activity and no reclaim, and 20 GB was free.
- A test without gufo reproduced it. After a 1,448 MB write, 25 of 399 reads after quiet gaps took 148 to 808 ms. Before the write, 0 of 129 did.
- A reader that never leaves the disk quiet shows nothing, so a continuous benchmark such as `fio` at constant load does not find this fault.

The workaround is a second process that does one 4 KiB direct read every 50 ms. It was measured in one gufo run. In the disk test it gave 0 slow reads in 171. In gufo with `--sessions 1` and the disk cache on it gave 0 pauses in six tasks, with decode of 50.9, 49.5, 54.0 and 49.5 on the four follow-up tasks that paused before.

```python
import mmap, os, random, time
path = "/path/to/any/large/file/on/the/same/drive"
fd = os.open(path, os.O_RDONLY | os.O_DIRECT)
buf = mmap.mmap(-1, 4096)
n = os.path.getsize(path) // 4096
while True:
    os.preadv(fd, [buf], random.randrange(n) * 4096)
    time.sleep(0.05)
```

The same reader with arguments is `tools/nvme_keepawake.py`. The disk test that reproduces the fault without gufo is `tools/nvme_stall_test.py`.

Not established: whether the delay is drive firmware or NVMe power state handling in Linux. `nvme_core.default_ps_max_latency_us` is 100000 on this machine, and setting it to 0 was not tested. Other drives were not tested.

## Open faults

- 9 of 34 model loads took about 305 s against about 20 s. The wait is in the step that pins about 2.1 GiB for the RAM cache. All 9 were in runs with the disk cache on. The cause is not established.
- In 5 of 12 control runs the second answer was written at 11 to 42 tok/s against 51. One such run showed stalls of 23 s and 31 s inside the answer. The NVMe stall is the likely cause and this is not proved.
- Total throughput with two requests at once ranged from 28.5 to 61.0 tok/s across identical runs. No conclusion is drawn about concurrent load.

## Other engines on the same machine

Measured 11 November 2026, same `UD-Q4_K_XL` file, 256K context, prompts of 3.9K, 23.7K and 81.8K tokens of synthetic records. Synthetic records raise draft acceptance, so these decode figures are above the document-task figures.

| Engine | Prompt reading | Decode |
| --- | --- | --- |
| gufo, no drafting | 1,810 / 1,901 / 1,887 | 27.2 / 27.1 / 26.7 |
| gufo, MTP | 1,751 / 1,839 / 1,814 | 56.9 / 54.0 / 60.6 |
| Strata 0.2.13, DFlash2, after `--tune quick` | 358 / 475 / 498 | 38.9 / 47.1 / 45.5 |

## Recommendations for the same hardware

1. Use `UD-Q4_K_XL` with the MTP draft head, draft width 7, and default prefill chunk.
2. Leave power limits at stock.
3. Keep the model loaded with a long idle timeout. A cold request pays the load plus a full prompt read.
4. For single-user document work, test `--sessions 1`. It gives the largest measured gain, on follow-up latency. Check for mid-answer pauses by timing the gaps between streamed chunks.
5. If the pauses appear, test the keep-awake reader before turning the disk cache off. The disk cache is what restores an earlier document in 0.9 s.
6. Measure decode on real tasks over HTTP with a warm-up request, and compare each change against control runs before and after it.

## Status of this setup

The serve command above is the one in service. `--sessions 1` and the keep-awake reader are tested and not yet applied. The reader result rests on one run.
