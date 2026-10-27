# Git

DryDock needs the repo's `.git` to commit, push and pull. When your Compose files sit in a sub-folder of the repo, mount the repo root and point `DRYDOCK_REPO_PATH` at the folder:

```yaml
    volumes:
      - /home/pi/homelab:/repo         # the git repo root
    environment:
      - DRYDOCK_REPO_PATH=/repo/docker # your Compose files
```

- A commit takes every change in the repo folder, `.env` files included unless `.gitignore` lists them. The Projects page lists them first.
- git runs as the owner of `.git`, so the files it writes stay yours.
- Commits use the repo's `user.name`. Without one, the author is the DryDock user.
- Push and pull use the git login for the remote's host. https remotes only: DryDock has no SSH keys.
- After a pull, apply the changes with **Reload** on each stack. DryDock never redeploys on its own.
