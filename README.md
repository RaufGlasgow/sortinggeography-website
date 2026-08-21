# sortinggeography.com

The marketing website for **Sorting Geography** — a daily geography game for iPhone
and Android. Static HTML, no build step, no framework.

**This repo is PUBLIC on purpose.** Public repositories get unlimited free GitHub
Actions minutes; private ones bill against a monthly allowance. Keeping the website
here and the game private means the site's CI costs nothing to run.

Nothing in this repo comes from the game repo except one generated file — see below.

## Layout

| Path | What |
| --- | --- |
| `index.html` | Landing page |
| `privacy.html` | Privacy policy (**draft** — must be finalised against the shipping build before store submission) |
| `credits.html` | **Generated.** Data-source attribution for every measure in the game |
| `style.css` | The whole stylesheet. App palette: forest green primary, ocean blue secondary, violet for rewards only |
| `scripts/build_credits.py` | Regenerates `credits.html` from the game's dataset |

## Regenerating the credits page

`credits.html` is built from the game's own dataset, so it can never drift from what
the app actually ships:

```sh
python3 scripts/build_credits.py ../Sorting-Geography/pipeline/content/dataset.json
```

Re-run it whenever the dataset version moves. This page is not decoration: World Bank
WDI, Our World in Data and GeoNames all ship under CC BY, which **requires**
attribution, so shipping the app without it is a licence breach.

## House rules

- **No gold, no orange, anywhere.** The app's identity reserves gold for a single
  in-game reward moment and bans it everywhere else. CI enforces this.
- Every page must parse and every local link must resolve. CI enforces both.
- No trackers, no external fonts, no CDN.
