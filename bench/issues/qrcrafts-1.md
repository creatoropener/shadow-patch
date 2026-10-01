buildContent in src/utils/qrBuilder.ts inserts SSID and password values into
the WiFi payload without escaping reserved characters. Delimiters in network
credentials can consequently be interpreted as payload structure.

For this repair, prefix each literal semicolon (;), comma (,), colon (:),
backslash (\\), and double quote (") in both SSID and password with one backslash.
Keep field delimiters and the WIFI:T:...;S:...;P:...;; envelope unchanged.

Example 1 — runtime values:

Security: WPA
SSID: Cafe;Guest
Password: pass:word
Exact expected payload (each displayed backslash is one literal character):

WIFI:T:WPA;S:Cafe\;Guest;P:pass\:word;;
Example 2 — runtime values:

Security: WPA
SSID: Office,West\Lab
Password: say"hello
Exact expected payload:

WIFI:T:WPA;S:Office\,West\\Lab;P:say\"hello;;
Ordinary credentials must continue to produce their existing payloads. Preserve
existing trimming, security selection and empty-SSID behavior. This issue does
not request changing how actual CR/LF characters are handled. Use printable
credentials to reproduce the escaping defect; do not introduce control-character
conversion requirements. An apostrophe is not a requested escaping case.

Regression coverage should call the real exported application function.
