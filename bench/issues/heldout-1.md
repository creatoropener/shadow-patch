On any viewport 960px wide or narrower, the .nav-cta "Back home" link is hidden, and privacy.html, terms.html and thank-you.html have no other way back to the homepage.

In styles.css (lines 189–191), the breakpoint hides both .nav and .nav-cta:

css
@media (max-width: 960px) { .nav, .nav-cta { display: none; } .menu-toggle { display: block; } ... }
