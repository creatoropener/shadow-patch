Applying an overlay whose `update` targets an array replaces the array with an object. `applyOverlay` (exported from src/engine/apply.ts) is supposed to append to an array target, as the README says ("Arrays are appended"), but the array comes back as an object keyed by index and the first elements are lost.

Each example below gives the input document, the whole overlay, and the exact result `applyOverlay` should return for that document and that overlay.

Example 1: an array update value is concatenated onto the array target.

```yaml
# document
tags:
  - name: A
  - name: B
# overlay
overlay: 1.0.0
info:
  title: t
  version: 1.0.0
actions:
  - target: $.tags
    update:
      - name: C
# expected result
tags:
  - name: A
  - name: B
  - name: C
```

Example 2: a value that is not an array is appended as one new element.

```yaml
# document
tags:
  - name: A
# overlay
overlay: 1.0.0
info:
  title: t
  version: 1.0.0
actions:
  - target: $.tags
    update:
      name: B
# expected result
tags:
  - name: A
  - name: B
```

Example 3: the same holds for an array of plain strings.

```yaml
# document
tags: [x, y]
# overlay
overlay: 1.0.0
info:
  title: t
  version: 1.0.0
actions:
  - target: $.tags
    update: [z, w]
# expected result
tags: [x, y, z, w]
```

Example 4: this one already works and must not change. An object target is still deep-merged.

```yaml
# document
info:
  title: T
# overlay
overlay: 1.0.0
info:
  title: t
  version: 1.0.0
actions:
  - target: $.info
    update:
      description: d
# expected result
info:
  title: T
  description: d
```

Regression coverage should call the real exported `applyOverlay` function.
