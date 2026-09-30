The file cards and download progress use the exported formatting utilities in
lib/utils/format.ts. For values at or above 1024 bytes, formatBytes returns
literal fragments such as v.toFixed(...) and {units[i]}. formatSpeed inherits
the problem. Users cannot read file sizes and transfer speeds correctly.
Expected behavior uses 1024-based units, preserving the current precision rule:
one decimal place below 100 units, no decimal places from 100 units upward.
Function Input Expected output
formatBytes 512 512 B
formatBytes 1024 1.0 KB
formatBytes 1536 1.5 KB
formatBytes 102400 100 KB
formatBytes 1048576 1.0 MB
formatBytes 1073741824 1.0 GB
formatSpeed 1536 1.5 KB/s
Reproduce this by calling the actual exported utility functions. Repair the
formatting without changing their signatures or unrelated behavior. No server,
browser, upload, cloud credentials, or network request is necessary for this case.
ETA formatting is a separate issue and is outside this repair's scope.
Acceptance: an independently generated regression fails with assertion errors on
the original source, passes after the repair, the existing baseline still passes,
the verifier test remains unchanged, and clean sandbox replay succeeds.
