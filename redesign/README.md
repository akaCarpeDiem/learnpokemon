# Redesign layer

A visual layer for learnpokemon.fun: three files that sit on top of the existing build. The app bundle, card data and images are not changed.

| File | What it does |
| --- | --- |
| `assets/lp-redesign.css` | Shared type colours and panel style, one-row phone menu, card tilt/foil/type-hint styles, card-detail styles, battle layouts, Pokédex fixes |
| `assets/lp-redesign.js` | Labels each card tile with its type and foil status, tilts cards toward the pointer, flies a card from the grid into the detail view and back |
| `assets/lp-battle.js` | Turn-based battle on set pages. Replaces `lp-vs-battle.js`; still uses `lp-vs-battle.css` for the attack artwork |
| `apply_redesign.py` | Adds the layer to a build folder, or removes it |

## Put it live

```
python redesign/apply_redesign.py /path/to/dist
```

then deploy `dist` as usual. The script copies the three files into `dist/assets` and edits every `.html` file that loads the old battle script:

```diff
     <link rel="canonical" href="https://learnpokemon.fun/" />
+    <link rel="stylesheet" href="/assets/lp-redesign.css?v=r1" />
   </head>
 ...
     <script src="/assets/lp-type-vfx-override.js?v=fx2b-1008" defer></script>
-    <script src="/assets/lp-vs-battle.js?v=5" defer></script>
+    <script src="/assets/lp-battle.js?v=r1" defer></script>
+    <script src="/assets/lp-redesign.js?v=r1" defer></script>
   </body>
```

Running it twice changes nothing the second time. When the three files change, bump `VERSION` in the script so browsers fetch the new copies.

## Take it out

```
python redesign/apply_redesign.py /path/to/dist --undo
```

This restores the original three tags exactly. The old `lp-vs-battle.js` is never deleted, so nothing has to be put back.

## How it fits the existing build

- The stylesheet loads last, so it overrides `index-*.css` and the other `lp-*.css` files without `!important` (one exception: showing the battle below 1360px, where `lp-vs-battle.css` hides it with `!important`).
- The scripts only read the page and add `data-lp-*` attributes, CSS variables and a few classes. They never move or remove nodes the app owns.
- `lp-battle.js` keeps the DOM and class names `lp-vs-battle.css` expects (`.lp-vs-root`, `.lp-vs-flank`, `.lp-vs-fx[data-kind]`, `is-firing-left/right`, `is-attacking`, `is-hit`).
- With `prefers-reduced-motion: reduce` there is no tilt, no flight and no battle.

## Battle rules

Fighters come from the current set's cards (`/data/cards/<set>.json`, or the Japanese snapshot / TCGdex for `/ja` routes). Each turn the attacker uses one of its printed attacks at its printed damage. The defender's printed weakness (×2 or +N) and resistance (−N) are applied when the attacker's type matches. Damage has a floor of 18% of the defender's HP so a fight ends within about six hits. At 0 HP the Pokémon faints and the next one from the set enters; the winner recovers half its HP and retires after three wins.

Layout switches at 1600px: wider, fighters stand in the page margins behind the cards (as before); narrower, the fight is a band under the set header.

## Note on `scripts/prerender_seo.py`

That script writes its own `<head>` and does not know about any `lp-*` overlay file, including the ones already live. If it is run again, re-run `apply_redesign.py` afterwards.
