# Curriculum data

This directory holds data files that used to live inline as Python dicts in `training_field/web/app.py`. The goal is that **non-engineers can edit them via GitHub's web UI** without touching Python code.

## `curriculum.json`

The list of grade × subject → topic lists the app uses to populate the topic dropdown.

### Schema

```json
{
  "grades": {
    "小6": {
      "code": 6,
      "subjects": {
        "算数": {
          "ja": ["単元A", "単元B", ...],
          "en": ["Topic A", "Topic B", ...]
        },
        "国語": { "ja": [...], "en": [...] }
      }
    }
  }
}
```

Rules:
- **`code` uniqueness**: `小1`=1 … `小6`=6, `中1`=7 … `中3`=9, `高1`=10 … `高3`=12. Don't reuse codes.
- **`ja` / `en` lists must be parallel**: item at index N in `ja` is the same topic as item N in `en`. The topic translation table (`TOPIC_TX_EN`) is built by zipping these two lists. If they have different lengths, the longer list wins the extras and they'll appear untranslated.
- **Keep 6 topics per subject** for now. The UI and pre-test generation assume a reasonable number — adding 30 topics won't break anything, but the picker becomes unwieldy.
- **JSON only.** UTF-8. The Python loader (`training_field/web/app.py`) fails to start if the file is malformed, so double-check commas and brackets before committing.

### How to add a new subject to an existing grade

Open this file on GitHub, press `.` to open the web editor, find the grade block (e.g. `"小6"`), and add a new key under `"subjects"`:

```json
"理科": {
  "ja": ["ものの燃え方", ...],
  "en": ["How Things Burn", ...]
}
```

Commit and open a PR. The app will pick up the new subject automatically after deploy.

### How to add a new grade

Add a new top-level key under `"grades"` with a unique `code`:

```json
"高4": { "code": 13, "subjects": {...} }
```

…but also add the label to `GRADE_CODES` handling if anywhere in the UI enumerates grades explicitly. (The backend loader does this from the JSON, but student-profile input screens may have a hardcoded list.)

### Legacy topic aliases

Older session records may reference topic strings that aren't in `curriculum.json` (e.g. `速さ時間距離` with no middle-dots). Those are handled separately via `LEGACY_TOPIC_ALIASES` in `training_field/web/app.py`. Add to that dict if you need to map an old topic string to a display label.

## Related

- Issue [#9](https://github.com/rojoma/toy-alchemy/issues/9) tracks this externalization.
- Issue [#33](https://github.com/rojoma/toy-alchemy/issues/33) lets end-users type a free-form topic that isn't in this file — so you don't have to add every niche topic here.
