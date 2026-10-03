The contact form uses a root-absolute path:

html
<form action="/thank-you.html" class="contact-form reveal" data-netlify="true" method="POST" ...>

Every other asset and page link in the repository is relative (styles.css, script.js, assets/favicon.svg, privacy.html, terms.html). If the site is served from a subpath such as https://creatoropener.github.io/Tabloop/, an IPFS gateway, a subfolder or a local preview, submitting the form goes to https://creatoropener.github.io/thank-you.html instead of https://creatoropener.github.io/Tabloop/thank-you.html, which returns 404.

Expected behavior: the form's action resolves relative to the page's own location, like the other links. Submitting from /Tabloop/ reaches /Tabloop/thank-you.html.
