On any viewport 960px wide or narrower, the .nav-cta "Back home" link is hidden, and privacy.html, terms.html and thank-you.html have no other way back to the homepage.

In styles.css (lines 189–191), the breakpoint hides both .nav and .nav-cta:

css
@media (max-width: 960px) { .nav, .nav-cta { display: none; } .menu-toggle { display: block; } ... }

On index.html this works, because .menu-toggle appears and opens the mobile menu. On privacy.html, terms.html and thank-you.html, the header contains only the brand link and the hidden link:

html
<div class="container nav-wrap">
  <a class="brand" href="index.html">...</a>
  <a class="nav-cta" href="index.html">Back home</a>
</div>

There is no .menu-toggle on these pages, and privacy.html and terms.html have no footer and no in-body link to the homepage. Mobile visitors are stranded.

Expected behavior: at 960px and below, each of these pages shows a visible link or control that leads to index.html. The mobile menu on index.html and the desktop header should not change.
