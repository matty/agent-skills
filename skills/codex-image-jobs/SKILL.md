---
name: codex-image-jobs
description: Image jobs through the Codex CLI (gpt-image-2, ChatGPT login) that get stuck or go wrong - codex-imagegen hanging, "Reading additional input from stdin", the wrong image under a filename, identical outputs, a reference ignored or a new room invented, quota burnt on retries; batches and chained edits. One safe runner script. One-off icons without a project can stay with the codex-bridge plugin's generate-image and edit-image skills.
---

# Codex image jobs

Run every project or batch image job through the runner. Do not call `codex exec` or `codex-imagegen` by hand for
these jobs.

```bash
python scripts/codex_image.py "<prompt or @prompt.txt>" out.png [--ref room.jpg] [--size 1536x1024] [--force]
```

It prints the absolute output path. Give the Bash call a timeout above the runner's own `--timeout` (default 420 s).

| Exit | Meaning | Do |
|---|---|---|
| 0 | Saved | View the image |
| 1 | Usage, for example the output exists | Fix the call; `--force` replaces an output, never its own reference |
| 2 | Codex ended with no image | Read the printed output, fix the cause, then retry once |
| 3 | The image call left out the reference, so nothing was saved | Retry once with the same command |
| 124 | No session or no image in time | Check `codex login status` and the network |

## Rules

1. **View every output against its brief.** Exit 0 proves one image came from this session, not that it is right.
2. **Chain edits one change at a time:** each output becomes the next `--ref`. Write to a new file each step.
3. **Keep the room:** say what must not change (camera, geometry, openings) and name each reference's role when
   there are two or more. Up to 4 references.
4. **Count the quota.** One run spends one image, and runs can go in parallel, but state the count before a big
   batch and make the first image work before the rest.
5. **PNG references with alpha:** pass `--keep-png-refs`, because JPG conversion flattens them.

## Why the runner exists

Measured with codex-cli 0.164.0 on 2026-11-04, from the session logs of 30 image runs.

| Failure | Cause | What the runner does |
|---|---|---|
| Hangs until the timeout | `codex exec` waits on an open stdin pipe: 45 s with a pipe (stopped by a timeout), 4 s with it closed | Sends the prompt on stdin, then closes it |
| Wrong image under a name | Told to save, Codex searched the shared `~/.codex/generated_images`, took the newest and copied another run's picture | Codex never saves; the runner reads only `generated_images/<its session id>/` |
| Up to 7 image calls for one output | Codex could not find how to save, so it generated again | Stops Codex at the first complete image |
| Reference ignored, room invented | The image tool sees attachments only if the call sets `num_last_images_to_include` | Names the parameter, reads the session log, exit 3 if it was left out |
| Room lost on chained passes | Every furniture pass fed a PNG lost it; JPG with the named parameter kept it (correlation, not a proven cause) | Converts PNG references to JPG when ffmpeg is on PATH |

Checked with the real CLI the same day: three edits, two of them in parallel on a PNG reference, each took about
25 s and one image call, and each kept its own colour change.

## If you must use the plugin's `codex-imagegen`

codex-bridge 1.2.0 has these failures. Call it with `</dev/null`, one job at a time, a JPG reference, and
"call the image tool exactly once with num_last_images_to_include:1" in the prompt, then view the result.
