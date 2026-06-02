# gh-pages branch — JROS landing site

This branch only exists to serve the JROS landing page at
<https://jenkinsrobotics.github.io/JROS/>.

It is **not** a working branch. Source code, dev docs, install
scripts, and CHANGELOG all live on `master`. Don't merge `master`
into here; don't merge here into `master`.

## What's in this branch

- `index.html` — the single-file landing page (embedded CSS + inline
  SVG, JR ecosystem footer)
- `.nojekyll` — tells GitHub Pages to serve files raw, no Jekyll build
- `README.md` — this file

## Editing the site

Edit `index.html` directly on this branch, commit, push to GitHub.
The Pages build is automatic.

```
git checkout gh-pages
# edit index.html
git commit -am "Update landing copy"
git push origin gh-pages
```

To preview locally, just `open index.html` — there is no build step.

## Pages settings

Repo Settings → Pages → Source: **Deploy from a branch** →
Branch: **`gh-pages`** → Folder: **`/ (root)`**.
