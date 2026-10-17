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
