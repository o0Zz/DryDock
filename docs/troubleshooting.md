# Troubleshooting

Common problems and how to fix them.

## Memory shows `0B / 0B` on the Containers page

**Symptom:** the Memory column shows `0B / 0B` for every container. CPU and the other stats look normal.

**Cause:** the memory cgroup is turned off on the host, so the Docker daemon reports no memory stats. DryDock shows what Docker returns. Raspberry Pi OS turns the memory cgroup off by default.

**Check:** run these on the Docker host.

```bash
docker info 2>&1 | grep -i warn   # look for "No memory limit support"
docker stats --no-stream          # MEM USAGE is 0B / 0B here too
```

If `docker stats` also shows `0B / 0B`, the cause is the host, not DryDock.

**Fix (Raspberry Pi OS):**

1. Open `/boot/firmware/cmdline.txt`. On older releases the file is `/boot/cmdline.txt`.
2. Add `cgroup_enable=memory cgroup_memory=1` to the end of the existing line. The file must stay on a single line.
3. Reboot the Pi.
4. Run `docker stats --no-stream` again. It should show real memory usage.

On other Linux distributions, enable the memory cgroup through the kernel command line in your boot loader (for example `GRUB_CMDLINE_LINUX` in `/etc/default/grub`, then `sudo update-grub`).

## "Are you trying to mount a directory onto a file" after up or update

**Symptom:** **up**, or **update** on a container, fails with an error such as `error mounting "/repo/<stack>/default.conf" ... not a directory`. The container stays down.

**Cause:** the Compose file uses a relative bind mount such as `./default.conf:/etc/nginx/conf.d/default.conf`. Compose turns it into an absolute path from where DryDock sees the file (`/repo/...`). The Docker daemon looks for that path on the host, where it does not exist, and creates an empty directory there instead.

DryDock avoids this by running Compose through the repo's host path. It reads that path from its own `/repo` mount at startup. The log shows `Running Compose through <host path>` when it works.

**Fix:**

1. Check the DryDock log (Logs page) for that line. If it is missing, set `DRYDOCK_REPO_HOST_PATH` to the host folder you mount at `/repo`, for example `/home/pi/docker`, and restart DryDock. Detection fails when the DryDock container has a custom `hostname:`.
2. On the host, remove the empty directories Docker created. Look first, then delete only what Docker made:

   ```bash
   sudo find /repo        # expect only empty folders, e.g. /repo/<stack>/default.conf
   sudo rm -r /repo
   ```

3. Bring the stack up again from DryDock.
